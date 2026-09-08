#!/usr/bin/env python3
"""Record, without modifying, the historical unregistered 0022 draft."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
legacy = ROOT / "scibench_replication_0022"
files = {p.relative_to(legacy).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(legacy.rglob("*")) if p.is_file()}
bundle = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
report = {"schema_version": 1, "task_id": legacy.name, "status": "historical_unregistered_preserved",
          "replacement_candidate": "scibench_replication_0022_core", "file_count": len(files),
          "bundle_file_map_sha256": bundle, "preserved_files": files}
(ROOT / "curation_reports/0022_legacy_preservation.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
