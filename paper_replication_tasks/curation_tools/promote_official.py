#!/usr/bin/env python3
"""Regenerate v4 gold from two pinned official checkouts and record evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scientific import solve  # noqa: E402
from task_registry import TASK_REGISTRY, active_task_ids  # noqa: E402


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(paths: list[Path], base: Path) -> str:
    value = hashlib.sha256()
    for path in sorted(paths):
        value.update(path.relative_to(base).as_posix().encode())
        value.update(b"\0")
        value.update(path.read_bytes())
        value.update(b"\0")
    return value.hexdigest()


def flatten(value: Any, prefix: str = "$") -> dict[str, float]:
    if isinstance(value, dict):
        result: dict[str, float] = {}
        for key in sorted(value):
            result.update(flatten(value[key], f"{prefix}.{key}"))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(flatten(item, f"{prefix}[{index}]"))
        return result
    return {prefix: float(value)}


def audit(official: dict[str, Any], independent: dict[str, Any]) -> dict[str, Any]:
    if "eigenvalues" in official and "eigenvalues" in independent:
        left_eigs = np.asarray([complex(*value) for value in official["eigenvalues"]])
        right_eigs = np.asarray([complex(*value) for value in independent["eigenvalues"]])
        if left_eigs.shape != right_eigs.shape:
            raise RuntimeError("independent eigenvalue shape differs from official output")
        rows, columns = linear_sum_assignment(np.abs(left_eigs[:, None] - right_eigs[None, :]))
        independent = dict(independent)
        reordered = np.empty_like(right_eigs)
        reordered[rows] = right_eigs[columns]
        independent["eigenvalues"] = [[float(value.real), float(value.imag)] for value in reordered]
    left, right = flatten(official), flatten(independent)
    if left.keys() != right.keys():
        raise RuntimeError("independent audit shape differs from official output")
    errors = {key: abs(left[key] - right[key]) for key in left}
    squared = sum(value * value for value in errors.values())
    return {
        "max_abs": max(errors.values(), default=0.0),
        "rmse": (squared / max(len(errors), 1)) ** 0.5,
        "per_field_max_abs": {
            key: max(value for path, value in errors.items() if path.startswith(f"$.{key}"))
            for key in official
        },
    }


def version_record(python: Path) -> dict[str, str]:
    source = (
        "import importlib,importlib.util,json,platform;"
        "v={'python':platform.python_version()};"
        "[(v.__setitem__(n,getattr(importlib.import_module(n),'__version__','unknown'))) "
        "for n in ('numpy','scipy','sympy','numba','dmdlab') if importlib.util.find_spec(n)];"
        "print(json.dumps(v,sort_keys=True))"
    )
    return json.loads(subprocess.check_output([str(python), "-c", source], text=True))


def environment_lock_path(checkout: Path, registry: dict[str, Any]) -> Path:
    curator_lock = registry.get("curator_environment_file")
    if curator_lock is not None:
        return ROOT / curator_lock
    environment_file = registry.get("environment_file")
    if environment_file is None:
        raise RuntimeError("task has no environment lock")
    return checkout / environment_file


def file_map(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def promote(task_id: str, checkouts: list[Path], environment: Path, dependency_artifact: Path | None = None) -> dict[str, Any]:
    registry = TASK_REGISTRY[task_id]
    python = environment / "bin/python"
    if not python.is_file():
        raise RuntimeError(f"environment Python missing: {python}")
    for checkout in checkouts:
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        status = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
        if commit != registry["commit"] or status:
            raise RuntimeError(f"checkout identity/cleanliness failure: {checkout}")
    expected_artifact_hash = registry.get("dependency_artifact_sha256")
    if expected_artifact_hash is not None:
        if dependency_artifact is None or not dependency_artifact.is_file():
            raise RuntimeError("pinned dependency artifact is required")
        if digest(dependency_artifact) != expected_artifact_hash:
            raise RuntimeError("pinned dependency artifact hash mismatch")

    adapter = ROOT / registry.get("adapter_path", "curation_tools/official_adapter.py")
    report_root = ROOT / "curation_reports/official_runs" / task_id[-4:]
    if report_root.exists():
        shutil.rmtree(report_root)
    run_hashes: list[str] = []
    first_outputs: dict[tuple[str, str], Path] = {}
    case_records: list[dict[str, Any]] = []
    for run_index, checkout in enumerate(checkouts, 1):
        generated: list[Path] = []
        for split in ("public", "hidden"):
            for case_root in sorted((ROOT / task_id / split / "cases").iterdir()):
                evidence = report_root / f"run_{run_index}" / f"{split}_{case_root.name}"
                normalized = evidence.with_suffix(".normalized.json")
                raw = evidence.with_suffix(".raw.json")
                command = [
                    str(python), str(adapter), "--task", task_id[-4:],
                    "--checkout", str(checkout), "--input", str(case_root / "input.json"),
                    "--output", str(normalized), "--raw-output", str(raw),
                ]
                subprocess.run(command, check=True)
                generated.append(normalized)
                key = (split, case_root.name)
                if run_index == 1:
                    first_outputs[key] = normalized
                    official = json.loads(normalized.read_text(encoding="utf-8"))
                    independent = solve(task_id, json.loads((case_root / "input.json").read_text(encoding="utf-8")))
                    error = audit(official, independent)
                    case_records.append({
                        "split": split,
                        "case_id": case_root.name,
                        "input_sha256": digest(case_root / "input.json"),
                        "raw_official_sha256": digest(raw),
                        "normalized_output_sha256": digest(normalized),
                        "output_sha256": digest(normalized),
                        "independent_error": error,
                        "checkout_commit": registry["commit"],
                        "environment_lock_sha256": digest(environment_lock_path(checkout, registry)),
                        "dependency_artifact_sha256": expected_artifact_hash,
                        "adapter_sha256": digest(adapter),
                        "command": "<environment>/bin/python curation_tools/official_adapter.py --task " + task_id[-4:] + " --checkout <clean-checkout> --input <input.json> --output <normalized.json> --raw-output <raw.json>",
                    })
                else:
                    first = report_root / "run_1" / normalized.name
                    first_raw = report_root / "run_1" / raw.name
                    if digest(normalized) != digest(first) or digest(raw) != digest(first_raw):
                        raise RuntimeError(f"two official runs differ: {task_id}/{split}/{case_root.name}")
        run_hashes.append(tree_digest(generated, report_root / f"run_{run_index}"))

    if run_hashes[0] != run_hashes[1]:
        raise RuntimeError(f"two normalized bundles differ: {task_id}")
    for (split, case_id), source in first_outputs.items():
        shutil.copyfile(source, ROOT / task_id / split / "cases" / case_id / "output.json")

    versions = version_record(python)
    environment_file = environment_lock_path(checkouts[0], registry)
    max_abs = max(record["independent_error"]["max_abs"] for record in case_records)
    rmse = max(record["independent_error"]["rmse"] for record in case_records)
    floors = {"max_abs": 1e-10, "rmse": 2e-11}
    tolerances = {"max_abs": max(floors["max_abs"], max_abs * 10), "rmse": max(floors["rmse"], rmse * 10)}
    write_json(ROOT / task_id / "hidden/tolerances.json", tolerances)
    provenance = {
        "schema_version": 4,
        "task_id": task_id,
        "repository": registry["repository"],
        "commit": registry["commit"],
        "lifecycle": "validated",
        "gold_source": "pinned_official_checkout",
        "environment": versions,
        "environment_lock_sha256": digest(environment_file),
        "dependency_artifact_sha256": expected_artifact_hash,
        "official_adapter": registry["official_adapter"],
        "parameter_patch": "JSON parameters and JSON output only; plotting/file-output tails are disabled; pinned numerical statements execute unchanged except the documented SciPy pinv compatibility rule for 0011.",
        "generation_command": "python curation_tools/promote_official.py --task ... --checkout ... --environment ...",
        "official_reproduction": {
            "adapter_sha256": digest(adapter),
            "environment": versions,
            "environment_lock_sha256": digest(environment_file),
            "dependency_artifact_sha256": expected_artifact_hash,
            "commands": ["<environment>/bin/python curation_tools/official_adapter.py --task " + task_id[-4:] + " --checkout <clean-checkout> --input <input.json> --output <normalized.json> --raw-output <raw.json>"],
            "clean_checkout_bundle_sha256": run_hashes,
            "raw_and_normalized_outputs": str(report_root.relative_to(ROOT)),
        },
        "independent_audit": {
            "implementation": "scientific.py clean-room formulation (not used for gold generation)",
            "maximum_max_abs": max_abs,
            "maximum_rmse": rmse,
            "derived_tolerances": tolerances,
            "status": "passed",
        },
        "cases": case_records,
    }
    if task_id.endswith("0011"):
        provenance["rank_deficiency_note"] = "Some empirical covariance matrices are singular. SciPy 1.12.0 scipy.linalg.pinv rank selection is an intentional part of the task definition."
    write_json(ROOT / task_id / "hidden/provenance.json", provenance)
    return {
        "task_id": task_id,
        "status": "validated",
        "commit": registry["commit"],
        "environment": versions,
        "environment_lock_sha256": digest(environment_file),
        "adapter_sha256": digest(adapter),
        "dependency_artifact_sha256": expected_artifact_hash,
        "clean_checkout_bundle_sha256": run_hashes,
        "independent_max_abs": max_abs,
        "independent_rmse": rmse,
        "tolerances": tolerances,
    }


def rebuild_manifest() -> None:
    rows = []
    for task_id in active_task_ids():
        registry = TASK_REGISTRY[task_id]
        root = ROOT / task_id
        rows.append({
            "task_id": task_id,
            "lifecycle": registry["status"],
            "public_files": file_map(root / "public"),
            "hidden_files": file_map(root / "hidden"),
        })
    write_json(ROOT / "manifest.json", {"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6}, "tasks": rows})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout", action="append", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--dependency-artifact", type=Path)
    args = parser.parse_args()
    if len(args.checkout) != 2:
        parser.error("exactly two --checkout arguments are required")
    result = promote(args.task, [path.resolve() for path in args.checkout], args.environment.resolve(), args.dependency_artifact.resolve() if args.dependency_artifact else None)
    write_json(ROOT / "curation_reports/official_runs" / f"{args.task[-4:]}_summary.json", result)
    rebuild_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
