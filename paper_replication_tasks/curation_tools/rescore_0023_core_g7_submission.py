#!/usr/bin/env python3
"""Re-score the retained 0023_core G7 blind submission against the current gold.

Use after a tolerance or gold change to check whether the already-generated blind
``solution.py`` now passes, without re-running the (billed) codex generation.  The
submission itself is not modified.  Updates ``curation_reports/0023_core_g7.json``
in place with the new score and a ``rescored_at`` marker.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0023_core"
SUBMISSION = ROOT / "core_algorithm_audits/0023_core_g7_submission"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import evaluate
    from run_submission import execute

    with tempfile.TemporaryDirectory(prefix="rescore_0023_g7_", dir="/tmp") as tmp:
        stage = Path(tmp)
        staged = stage / TASK.name
        shutil.copytree(TASK, staged)
        prov = json.loads((staged / "hidden/provenance.json").read_text())
        prov["lifecycle"] = "validated"
        prov["gold_source"] = "pinned_official_checkout"
        (staged / "hidden/provenance.json").write_text(json.dumps(prov))
        (stage / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 4,
                    "scoring": {"public_weight": 0.4, "hidden_weight": 0.6},
                    "tasks": [
                        {
                            "task_id": TASK.name,
                            "lifecycle": "validated",
                            "public_files": files(staged / "public"),
                            "hidden_files": files(staged / "hidden"),
                        }
                    ],
                }
            )
        )
        sub = stage / "submission"
        sub.mkdir()
        shutil.copyfile(SUBMISSION / "solution.py", sub / "solution.py")
        (sub / "submission.json").write_text(
            json.dumps({"schema_version": 4, "task_id": TASK.name, "entrypoint": [sys.executable, "solution.py"]})
        )
        report_path = stage / "execution.json"
        report = execute(sub, staged, report_path, 300)
        report_path.write_text(json.dumps(report))
        score = evaluate(staged, report_path)

    out_path = ROOT / "curation_reports/0023_core_g7.json"
    record = json.loads(out_path.read_text()) if out_path.is_file() else {"schema_version": 1, "task_id": TASK.name}
    record.update(
        {
            "G7": "PASS" if score["full_success"] else "FAIL",
            "score": score["score"],
            "public_score": score["public_score"],
            "hidden_score": score["hidden_score"],
            "full_success": score["full_success"],
            "cases": score["checks"],
            "solution_sha256": sha(SUBMISSION / "solution.py"),
            "rescored_at": datetime.now(timezone.utc).isoformat(),
            "rescore_note": "Re-scored the retained blind submission against updated gold/tolerances; "
            "generation not re-run.",
        }
    )
    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(out_path)
    print(json.dumps(
        {"G7": record["G7"], "score": round(score["score"], 4),
         "public": round(score["public_score"], 4), "hidden": round(score["hidden_score"], 4),
         "failed_cases": [c["id"] for c in score["checks"] if not c["passed"]]},
        indent=2,
    ))


if __name__ == "__main__":
    main()
