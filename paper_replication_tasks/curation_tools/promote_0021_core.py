#!/usr/bin/env python3
"""Fail-closed promotion of 0021_core after every G1-G8 gate passes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "scibench_replication_0021"
NEW = "scibench_replication_0021_core"


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def files(root: Path) -> dict[str, str]: return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def atomic(path: Path, text: str) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle: handle.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
def atomic_json(path: Path, value) -> None: atomic(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main() -> None:
    validation = json.loads((ROOT / "curation_reports/0021_core_validation.json").read_text())
    g6 = json.loads((ROOT / "core_algorithm_audits/0021_core_blind.json").read_text())
    g7 = json.loads((ROOT / "curation_reports/0021_core_g7.json").read_text())
    oracle = json.loads((ROOT / "curation_reports/0021_core_oracle.json").read_text())
    if validation.get("status") != "ACCEPT" or not all(validation.get("gates", {}).values()) or g6.get("G6") != "PASS" or g7.get("G7") != "PASS" or oracle.get("G8") != "PASS":
        raise RuntimeError("G1-G8 are not all passing; legacy 0021 remains active")
    legacy = ROOT / OLD; baseline = json.loads((ROOT / "curation_reports/0021_core_legacy_baseline.json").read_text())["preserved_files"]
    if files(legacy) != baseline: raise RuntimeError("legacy 0021 substantive bytes changed")
    hashes = oracle["provenance"]
    expected = [hashes[key] for key in ("official_adapter_sha256", "independent_implementation_sha256", "curator_reference_sha256", "blind_submission_sha256")]
    if any(value is None for value in expected) or len(set(expected)) != 4: raise RuntimeError("G8 four-way provenance is absent or not distinct")
    task = ROOT / NEW; provenance_path = task / "hidden/provenance.json"; provenance = json.loads(provenance_path.read_text()); provenance["lifecycle"] = "validated"; provenance["gold_source"] = "pinned_official_checkout"; atomic_json(provenance_path, provenance)
    manifest_path = ROOT / "manifest.json"; manifest = json.loads(manifest_path.read_text()); matches = [i for i, row in enumerate(manifest["tasks"]) if row["task_id"] == OLD]
    if len(matches) != 1 or any(row["task_id"] == NEW for row in manifest["tasks"]): raise RuntimeError("unexpected manifest state")
    old_row = manifest["tasks"][matches[0]]
    if old_row["public_files"] != files(legacy / "public") or old_row["hidden_files"] != files(legacy / "hidden"): raise RuntimeError("legacy manifest hashes differ")
    manifest["tasks"][matches[0]] = {"task_id": NEW, "lifecycle": "validated", "public_files": files(task / "public"), "hidden_files": files(task / "hidden")}
    registry_path = ROOT / "task_registry.py"; registry = registry_path.read_text(); old_start = f'    "{OLD}": '; candidate_start = f'    "{NEW}": '
    old_lines = [line for line in registry.splitlines() if line.startswith(old_start)]; candidate_lines = [line for line in registry.splitlines() if line.startswith(candidate_start)]
    if len(old_lines) != 1 or len(candidate_lines) != 1: raise RuntimeError("unexpected registry state")
    promoted = candidate_lines[0].replace(candidate_start, candidate_start, 1).replace('"status": "revise"', '"status": "validated"').replace(', "promotion_blockers": ["G7"]', '')
    registry = registry.replace(old_lines[0], promoted).replace(candidate_lines[0] + "\n", "", 1)
    papers_path = ROOT / "papers.json"; papers = json.loads(papers_path.read_text()); rows = [row for row in papers["papers"] if row.get("task_id") == OLD]
    if len(rows) != 1: raise RuntimeError("unexpected papers registry state")
    rows[0]["task_id"] = NEW
    atomic_json(ROOT / "curation_reports/0021_legacy.json", {"schema_version": 1, "task_id": OLD, "lifecycle": "legacy_experiment_replication", "retired_from_active_manifest": str(date.today()), "replacement": NEW, "preserved_public_files": old_row["public_files"], "preserved_hidden_files": old_row["hidden_files"], "removed_validator_junk": {".DS_Store": "52650335fd360683d8077153d5baf326003891d6fb950e79dc886e937883a59a"}})
    atomic(registry_path, registry); atomic_json(papers_path, papers); atomic_json(manifest_path, manifest)
    print(f"promoted {NEW}; legacy bytes preserved")


if __name__ == "__main__": main()
