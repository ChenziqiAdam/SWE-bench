#!/usr/bin/env python3
"""Atomically replace active 0015 with validated 0015_core in the manifest."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "scibench_replication_0015"
NEW = "scibench_replication_0015_core"


def file_map(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def atomic_json(path: Path, value) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle: json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def main() -> None:
    validation = json.loads((ROOT / "curation_reports/0015_core_validation.json").read_text())
    blind = json.loads((ROOT / "core_algorithm_audits/0015_core_blind.json").read_text())
    oracle = json.loads((ROOT / "curation_reports/0015_core_oracle.json").read_text())
    if validation.get("status") != "passed" or not all(validation.get("gates", {}).values()) or blind.get("G6") != "PASS" or oracle.get("G8") != "PASS":
        raise RuntimeError("G1-G8 have not all passed")
    path = ROOT / "manifest.json"; manifest = json.loads(path.read_text())
    matches = [i for i, row in enumerate(manifest["tasks"]) if row.get("task_id") == OLD]
    if len(matches) != 1 or any(row.get("task_id") == NEW for row in manifest["tasks"]): raise RuntimeError("unexpected active manifest state")
    index = matches[0]; old_row = manifest["tasks"][index]; old_root = ROOT / OLD
    if old_row["public_files"] != file_map(old_root / "public") or old_row["hidden_files"] != file_map(old_root / "hidden"):
        raise RuntimeError("legacy task changed before promotion")
    new_root = ROOT / NEW
    manifest["tasks"][index] = {"task_id": NEW, "lifecycle": "validated", "public_files": file_map(new_root / "public"), "hidden_files": file_map(new_root / "hidden")}
    legacy = {"schema_version": 1, "task_id": OLD, "lifecycle": "legacy_experiment_replication", "retired_from_active_manifest": str(date.today()),
              "replacement": NEW, "preserved_public_files": old_row["public_files"], "preserved_hidden_files": old_row["hidden_files"],
              "reason": "Replaced only after the core-algorithm task passed G1-G8; directory bytes remain unchanged."}
    atomic_json(ROOT / "curation_reports/0015_legacy.json", legacy)
    atomic_json(path, manifest)


if __name__ == "__main__": main()
