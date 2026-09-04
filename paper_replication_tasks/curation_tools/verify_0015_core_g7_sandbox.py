#!/usr/bin/env python3
"""Run the clean-room solution with no network or repository read access."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from verify_fixed_sparsity_core_task import program

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0015_core"


def main() -> None:
    from evaluation.framework import compare_output
    tolerance = json.loads((TASK / "hidden/tolerances.json").read_text())
    rows = []
    with tempfile.TemporaryDirectory(prefix="scibench_0015_core_g7_", dir="/tmp") as temporary:
        stage = Path(temporary); solution = stage / "solution.py"; solution.write_text(program("reference"), encoding="utf-8")
        profile = stage / "profile.sb"
        profile.write_text(
            '(version 1)\n(allow default)\n(deny network*)\n'
            f'(deny file-read* (subpath "{ROOT.parent}"))\n', encoding="utf-8"
        )
        for split in ("public", "hidden"):
            for case in sorted((TASK / split / "cases").iterdir()):
                input_path = stage / "input.json"; output_dir = stage / "output"
                shutil.copyfile(case / "input.json", input_path)
                if output_dir.exists(): shutil.rmtree(output_dir)
                completed = subprocess.run(
                    ["/usr/bin/sandbox-exec", "-f", str(profile), "/opt/anaconda3/bin/python", "-I", str(solution),
                     "--input", str(input_path), "--output", str(output_dir)],
                    cwd=stage, env={"PATH": "/usr/bin:/bin:/opt/anaconda3/bin", "PYTHONNOUSERSITE": "1"},
                    timeout=20, capture_output=True, text=True,
                )
                if completed.returncode != 0: raise RuntimeError(f"sandboxed {split}/{case.name} failed: {completed.stderr[:500]}")
                actual = json.loads((output_dir / "output.json").read_text()); expected = json.loads((case / "output.json").read_text())
                passed = compare_output(actual, expected, tolerance)["passed"]
                rows.append({"split": split, "case_id": case.name, "passed": passed})
                input_path.unlink(); shutil.rmtree(output_dir)
    report = {"schema_version": 1, "task_id": TASK.name, "G7": "PASS" if all(r["passed"] for r in rows) else "FAIL",
              "isolation": {"network": "denied by macOS sandbox", "repository_reads": "denied", "environment": "minimal; Python isolated mode", "temporary_workspace_cleaned": True},
              "cases": rows, "score": sum(r["passed"] for r in rows) / len(rows)}
    (ROOT / "curation_reports/0015_core_g7.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["G7"] != "PASS": raise RuntimeError("G7 failed")


if __name__ == "__main__": main()
