#!/usr/bin/env python3
"""Run and record the 0018_core curator reference through the real evaluator."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
SUBMISSION = ROOT / "core_algorithm_audits/0018_core_curator_submission"
REPORT = ROOT / "curation_reports/official_runs/0018_core/g8_curator_reference/report.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_map(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def main() -> None:
    import sys
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import evaluate
    from run_submission import execute

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scibench_0018_core_curator_", dir="/tmp") as temporary:
        stage = Path(temporary)
        benchmark = stage / "benchmark"
        staged_task = benchmark / TASK.name
        shutil.copytree(TASK, staged_task)
        provenance_path = staged_task / "hidden/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["lifecycle"] = "validated"
        provenance["gold_source"] = "pinned_official_checkout"
        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        (benchmark / "manifest.json").write_text(json.dumps({
            "schema_version": 4,
            "scoring": {"public_weight": .4, "hidden_weight": .6},
            "tasks": [{"task_id": TASK.name, "lifecycle": "validated",
                       "public_files": file_map(staged_task / "public"),
                       "hidden_files": file_map(staged_task / "hidden")}],
        }, indent=2, sort_keys=True) + "\n")
        execution_path = stage / "execution.json"
        execution = execute(SUBMISSION, staged_task, execution_path, 600.0)
        execution_path.write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
        score = evaluate(staged_task, execution_path)
        cases = [{"split": split, "case_id": row["case_id"],
                  "exit_code": row["exit_code"], "timed_out": row["timed_out"],
                  "wall_seconds": row["wall_seconds"], "output_sha256": row["output_sha256"]}
                 for split, rows in execution["cases"].items() for row in rows]
    report = {
        "schema_version": 1,
        "task_id": TASK.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "G8_curator_reference": "PASS" if score["full_success"] else "FAIL",
        "score": score["score"],
        "public_score": score["public_score"],
        "hidden_score": score["hidden_score"],
        "full_success": score["full_success"],
        "cases": cases,
        "submission_sha256": sha(SUBMISSION / "solution.py"),
        "submission_manifest_sha256": sha(SUBMISSION / "submission.json"),
        "runner_sha256": sha(ROOT / "run_submission.py"),
        "scientific_dispatch_sha256": sha(ROOT / "scientific.py"),
        "scientific_implementation_sha256": sha(ROOT / "curation_tools/energy_tsa_core_scientific.py"),
        "provenance": (
            "Curator-authored evaluator reference wrapper over the registered scientific "
            "implementation. It is distinct from the official adapter and blind agent, and "
            "validates only the unified runner/full-score path; it is not claimed as a second "
            "independent scientific derivation."
        ),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "redaction": "No credentials, endpoint, provider/user/request IDs, or external calls.",
    }
    temporary_report = REPORT.with_suffix(".tmp")
    temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_report, REPORT)
    if not score["full_success"]:
        raise RuntimeError(f"curator reference failed: {score}")


if __name__ == "__main__":
    main()
