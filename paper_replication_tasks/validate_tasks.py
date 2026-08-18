#!/usr/bin/env python3
"""Fail-closed structural and official-reproduction validation for v4 bundles."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from evaluation.framework import read_json, sha256_file
from task_registry import TASK_REGISTRY, active_task_ids, validated_task_ids

ROOT = Path(__file__).resolve().parent
LEGACY = {"masked_paper.pdf", "submission_schema.json", "gold_output.json", "evaluator.py", "results.json", ".DS_Store"}
PUBLIC_COUNTS = {"scibench_replication_0011": 1, "scibench_replication_0014": 3, "scibench_replication_0017": 3, "scibench_replication_0015": 3, "scibench_replication_0019": 3}


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def file_map(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def validate_checkout(checkout: Path, task_id: str) -> None:
    require(checkout.is_dir(), f"official checkout missing: {checkout}")
    commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    require(commit == TASK_REGISTRY[task_id]["commit"], f"official commit mismatch: {task_id}")
    status = subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain"], text=True
    )
    require(not status.strip(), f"official checkout is dirty: {task_id}")
    environment_file = TASK_REGISTRY[task_id].get("environment_file")
    if environment_file is not None:
        require((checkout / environment_file).is_file(), f"official environment file missing: {task_id}")


def environment_lock(checkout: Path, task_id: str) -> Path:
    registry = TASK_REGISTRY[task_id]
    curator_lock = registry.get("curator_environment_file")
    return ROOT / curator_lock if curator_lock else checkout / registry["environment_file"]


def validate_official(root: Path) -> None:
    """Recreate official environments and rerun every validated case twice."""
    pending: list[str] = []
    for task_id in active_task_ids():
        provenance = read_json(ROOT / task_id / "hidden/provenance.json")
        if TASK_REGISTRY[task_id]["status"] != "validated":
            # A single checkout is enough to audit the pinned identity of pending
            # work; validated tasks below require two independent checkouts.
            validate_checkout(root / task_id[-4:], task_id)
            pending.append(task_id)
            continue
        checkout_roots = [root / task_id[-4:] / name for name in ("run_1", "run_2")]
        for checkout in checkout_roots:
            validate_checkout(checkout, task_id)
        require(provenance.get("gold_source") == "pinned_official_checkout", f"non-official gold source: {task_id}")
        reproduction = provenance.get("official_reproduction")
        require(isinstance(reproduction, dict), f"official reproduction record missing: {task_id}")
        adapter = ROOT / TASK_REGISTRY[task_id].get("adapter_path", "curation_tools/official_adapter.py")
        require(reproduction.get("adapter_sha256") == sha256_file(adapter), f"adapter hash mismatch: {task_id}")
        environment_file = environment_lock(checkout_roots[0], task_id)
        require(environment_file.is_file(), f"official environment is not pinned: {task_id}")
        artifact_hash = TASK_REGISTRY[task_id].get("dependency_artifact_sha256")
        if artifact_hash is not None:
            artifact = root / "artifacts/dmdlab-0.1.1-py3-none-any.whl"
            require(artifact.is_file() and sha256_file(artifact) == artifact_hash, f"dependency artifact mismatch: {task_id}")
        run_hashes: list[list[str]] = []
        for run_number, checkout in enumerate(checkout_roots, 1):
            with tempfile.TemporaryDirectory(prefix=f"scibench_{task_id[-4:]}_env_") as environment_dir:
                conda_environment = os.environ.copy()
                subprocess.run(
                    ["conda", "env", "create", "--quiet", "--prefix", environment_dir, "--file", str(environment_file)],
                    check=True,
                    env=conda_environment,
                )
                if artifact_hash is not None:
                    subprocess.run(
                        ["conda", "run", "--prefix", environment_dir, "python", "-m", "pip", "install", "--force-reinstall", "--no-deps", str(artifact)],
                        check=True,
                    )
                hashes: list[str] = []
                for split in ("public", "hidden"):
                    for case in sorted((ROOT / task_id / split / "cases").iterdir()):
                        with tempfile.TemporaryDirectory(prefix="scibench_official_output_") as output_dir:
                            output = Path(output_dir) / "output.json"
                            command = [
                                "conda", "run", "--prefix", environment_dir, "python", str(adapter),
                                "--task", task_id[-4:], "--checkout", str(checkout),
                                "--input", str(case / "input.json"), "--output", str(output),
                            ]
                            subprocess.run(command, check=True)
                            require(sha256_file(output) == sha256_file(case / "output.json"), f"regenerated gold mismatch: {task_id}/{split}/{case.name}/run_{run_number}")
                            hashes.append(sha256_file(output))
                run_hashes.append(hashes)
        require(run_hashes[0] == run_hashes[1], f"two clean official runs differ: {task_id}")
    if pending:
        raise ValidationError(
            "official reproduction is incomplete; pending tasks: " + ", ".join(pending)
        )


def validate_bundle() -> tuple[int, int]:
    manifest = read_json(ROOT / "manifest.json")
    require(manifest.get("schema_version") == 4, "manifest schema mismatch")
    require(manifest.get("scoring") == {"public_weight": 0.4, "hidden_weight": 0.6}, "scoring mismatch")
    rows = {row["task_id"]: row for row in manifest.get("tasks", [])}
    require(set(rows) == set(active_task_ids()), "manifest task set mismatch")
    audit = read_json(ROOT / "curation_reports/retained_task_official_gold_audit.json")
    for adapter_record in audit["adapters"]:
        adapter = ROOT / adapter_record["path"]
        require(adapter_record["sha256"] == sha256_file(adapter), "curator adapter hash mismatch")
    validated = 0
    pending = 0
    for task_id in active_task_ids():
        registry = TASK_REGISTRY[task_id]
        adapter = ROOT / registry.get("adapter_path", "curation_tools/official_adapter.py")
        row = rows[task_id]
        require(row.get("lifecycle") == registry["status"], f"manifest lifecycle mismatch: {task_id}")
        root = ROOT / task_id
        public, hidden = root / "public", root / "hidden"
        require({path.name for path in public.iterdir() if path.is_file()} == {"paper.pdf", "task.md", "interface.schema.json"}, f"bad public layout: {task_id}")
        require({path.name for path in hidden.iterdir() if path.is_file()} == {"provenance.json", "tolerances.json"}, f"bad hidden layout: {task_id}")
        require(not any(path.name in LEGACY for path in root.rglob("*")), f"legacy file present: {task_id}")
        paper_data = (public / "paper.pdf").read_bytes()
        require(len(paper_data) > 50_000 and paper_data.startswith(b"%PDF-") and b"%%EOF" in paper_data[-4096:], f"invalid paper: {task_id}")
        schema = read_json(public / "interface.schema.json")
        require(schema["properties"]["schema_version"]["const"] == 4, f"interface schema mismatch: {task_id}")
        public_cases = sorted(path for path in (public / "cases").iterdir() if path.is_dir())
        hidden_cases = sorted(path for path in (hidden / "cases").iterdir() if path.is_dir())
        require(len(public_cases) == PUBLIC_COUNTS[task_id] and len(hidden_cases) == 5, f"case count mismatch: {task_id}")
        provenance = read_json(hidden / "provenance.json")
        require(provenance.get("repository") == registry["repository"], f"repository mismatch: {task_id}")
        require(provenance.get("commit") == registry["commit"], f"commit mismatch: {task_id}")
        require("maximum_observed_error" not in json.dumps(provenance), f"unsupported zero-error claim: {task_id}")
        require(provenance.get("lifecycle") == registry["status"], f"provenance lifecycle mismatch: {task_id}")
        compatibility_patch = registry.get("compatibility_patch_path")
        if compatibility_patch is not None:
            patch_path = ROOT / compatibility_patch
            require(patch_path.is_file() and provenance.get("patch_sha256") == sha256_file(patch_path), f"compatibility patch provenance mismatch: {task_id}")
        case_records = {(record["split"], record["case_id"]): record for record in provenance["cases"]}
        for split, cases in (("public", public_cases), ("hidden", hidden_cases)):
            for case in cases:
                require({path.name for path in case.iterdir()} == {"input.json", "output.json"}, f"bad case layout: {task_id}/{split}/{case.name}")
                record = case_records.get((split, case.name))
                require(record is not None, f"case provenance missing: {task_id}/{split}/{case.name}")
                require(record["input_sha256"] == sha256_file(case / "input.json"), f"input hash mismatch: {task_id}/{split}/{case.name}")
                require(record["output_sha256"] == sha256_file(case / "output.json"), f"output hash mismatch: {task_id}/{split}/{case.name}")
        require(row["public_files"] == file_map(public), f"public manifest mismatch: {task_id}")
        require(row["hidden_files"] == file_map(hidden), f"hidden manifest mismatch: {task_id}")
        if registry["status"] == "validated":
            require(provenance.get("gold_source") == "pinned_official_checkout", f"validated task lacks official gold: {task_id}")
            reproduction = provenance.get("official_reproduction")
            require(isinstance(reproduction, dict), f"official reproduction missing: {task_id}")
            require(reproduction.get("adapter_sha256") == sha256_file(adapter), f"adapter provenance mismatch: {task_id}")
            require(reproduction.get("environment_lock_sha256") == provenance.get("environment_lock_sha256"), f"environment lock mismatch: {task_id}")
            expected_artifact = registry.get("dependency_artifact_sha256")
            require(provenance.get("dependency_artifact_sha256") == expected_artifact, f"dependency artifact provenance mismatch: {task_id}")
            require(reproduction.get("dependency_artifact_sha256") == expected_artifact, f"dependency artifact reproduction mismatch: {task_id}")
            bundle_hashes = reproduction.get("clean_checkout_bundle_sha256")
            require(isinstance(bundle_hashes, list) and len(bundle_hashes) == 2 and bundle_hashes[0] == bundle_hashes[1], f"clean official run hashes differ: {task_id}")
            independent = provenance.get("independent_audit")
            require(isinstance(independent, dict) and independent.get("status") == "passed", f"independent audit missing: {task_id}")
            require(independent.get("derived_tolerances") == read_json(hidden / "tolerances.json"), f"derived tolerance mismatch: {task_id}")
            evidence_root = ROOT / reproduction["raw_and_normalized_outputs"]
            for record in case_records.values():
                stem = f"{record['split']}_{record['case_id']}"
                for run_number in (1, 2):
                    raw = evidence_root / f"run_{run_number}/{stem}.raw.json"
                    normalized = evidence_root / f"run_{run_number}/{stem}.normalized.json"
                    require(raw.is_file() and normalized.is_file(), f"official evidence missing: {task_id}/{stem}/run_{run_number}")
                    require(sha256_file(raw) == record["raw_official_sha256"], f"raw official hash mismatch: {task_id}/{stem}/run_{run_number}")
                    require(sha256_file(normalized) == record["normalized_output_sha256"], f"normalized official hash mismatch: {task_id}/{stem}/run_{run_number}")
                require(record["normalized_output_sha256"] == record["output_sha256"], f"gold normalization hash mismatch: {task_id}/{stem}")
                if task_id.endswith("0014"):
                    require(record.get("checkout_commit") == registry["commit"], f"case checkout provenance mismatch: {task_id}/{stem}")
                    require(record.get("environment_lock_sha256") == provenance.get("environment_lock_sha256"), f"case environment provenance mismatch: {task_id}/{stem}")
                    require(record.get("dependency_artifact_sha256") == expected_artifact, f"case dependency provenance mismatch: {task_id}/{stem}")
                    require(record.get("adapter_sha256") == sha256_file(adapter), f"case adapter provenance mismatch: {task_id}/{stem}")
                    require(isinstance(record.get("command"), str) and "adapter.py" in record["command"], f"case command provenance missing: {task_id}/{stem}")
            validated += 1
        else:
            require(provenance.get("gold_source") == "unverified_candidate", f"pending task is not marked candidate: {task_id}")
            pending += 1
    require(validated == len(validated_task_ids()), "validated lifecycle count mismatch")
    return validated, pending


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-root", type=Path)
    parser.add_argument("--reproduce-official", action="store_true")
    args = parser.parse_args()
    try:
        validated, pending = validate_bundle()
        if args.reproduce_official:
            require(args.official_root is not None, "--reproduce-official requires --official-root")
            validate_official(args.official_root)
        elif args.official_root is not None:
            parser.error("--official-root is only used with --reproduce-official")
    except (ValidationError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"audited {validated + pending} v4 bundles: {validated} validated, {pending} pending official regeneration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
