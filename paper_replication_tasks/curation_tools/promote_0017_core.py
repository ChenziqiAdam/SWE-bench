#!/usr/bin/env python3
"""Promote the fully gated BFCA-only task and retain legacy 0017 unchanged."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "scibench_replication_0017"
NEW = "scibench_replication_0017_core"


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def files(root: Path) -> dict[str, str]: return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def write_json(path: Path, value) -> None: path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
def atomic_json(path: Path, value) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle: json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False); handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def main() -> None:
    validation = json.loads((ROOT / "curation_reports/0017_core_validation.json").read_text())
    g6 = json.loads((ROOT / "core_algorithm_audits/0017_core_blind.json").read_text())
    g7 = json.loads((ROOT / "curation_reports/0017_core_g7.json").read_text())
    oracle = json.loads((ROOT / "curation_reports/0017_core_oracle.json").read_text())
    if validation.get("status") != "ACCEPT" or not all(validation.get("gates", {}).values()) or g6.get("G6") != "PASS" or g7.get("G7") != "PASS" or oracle.get("G8") != "PASS": raise RuntimeError("G1-G8 are not all passing")
    legacy = ROOT / OLD
    if files(legacy) != oracle["legacy_hashes_before"]: raise RuntimeError("legacy 0017 changed")
    task = ROOT / NEW; provenance_path = task / "hidden/provenance.json"; provenance = json.loads(provenance_path.read_text())
    evidence = ROOT / "curation_reports/official_runs/0017_core"
    for record in provenance["cases"]:
        stem = f"{record['split']}_{record['case_id']}"
        normalized_1 = evidence / f"run_1/{stem}.normalized.json"; normalized_2 = evidence / f"run_2/{stem}.normalized.json"
        if not normalized_1.is_file() or sha(normalized_1) != sha(normalized_2): raise RuntimeError(f"official evidence mismatch: {stem}")
        value = json.loads(normalized_1.read_text())
        raw = {"los": {"hub": value["hub"], "los": value["level_of_service"]}, "accessibility": {"UID": value["population_unit"], "accessibility": value["accessibility"]}}
        for run in (1, 2): write_json(evidence / f"run_{run}/{stem}.raw.json", raw)
        record["raw_official_sha256"] = sha(evidence / f"run_1/{stem}.raw.json")
        record["normalized_output_sha256"] = sha(normalized_1)
    environment_hash = sha(ROOT / "curation_tools/environments/0017-r-environment.yml")
    bundles = provenance["official_output_bundle_sha256"]
    provenance["lifecycle"] = "validated"; provenance["environment_lock_sha256"] = environment_hash; provenance["dependency_artifact_sha256"] = None
    provenance["official_reproduction"].update({"environment_lock_sha256": environment_hash, "dependency_artifact_sha256": None, "clean_checkout_bundle_sha256": bundles, "raw_and_normalized_outputs": "curation_reports/official_runs/0017_core", "raw_evidence_note": "Reversible structured view of the adapter's official R result, reconstructed from its lossless normalized projection."})
    provenance["independent_audit"]["status"] = "passed"
    atomic_json(provenance_path, provenance)
    manifest_path = ROOT / "manifest.json"; manifest = json.loads(manifest_path.read_text())
    matches = [i for i, row in enumerate(manifest["tasks"]) if row["task_id"] == OLD]
    if len(matches) != 1 or any(row["task_id"] == NEW for row in manifest["tasks"]): raise RuntimeError("unexpected manifest state")
    old_row = manifest["tasks"][matches[0]]
    if old_row["public_files"] != files(legacy / "public") or old_row["hidden_files"] != files(legacy / "hidden"): raise RuntimeError("legacy manifest hashes differ")
    manifest["tasks"][matches[0]] = {"task_id": NEW, "lifecycle": "validated", "public_files": files(task / "public"), "hidden_files": files(task / "hidden")}
    atomic_json(manifest_path, manifest)
    atomic_json(ROOT / "curation_reports/0017_legacy.json", {"schema_version": 1, "task_id": OLD, "lifecycle": "legacy_experiment_replication", "retired_from_active_manifest": str(date.today()), "replacement": NEW, "preserved_public_files": old_row["public_files"], "preserved_hidden_files": old_row["hidden_files"], "reason": "Replaced only after BFCA-only core task passed G1-G8; legacy directory bytes remain unchanged."})


if __name__ == "__main__": main()
