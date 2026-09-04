#!/usr/bin/env python3
"""Scientific, scoring, and evaluator-safety gates for task 0022.
Structural analog of verify_reim_task.py; NOT run in this curation session
(the task hasn't been built yet -- see build_ssarnoldi_task.py's notes on
the still-unwired independent audit)."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from ssarnoldi_common import validate_case

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0022"


def expect_error(function, *args):
    try:
        function(*args)
    except Exception:
        return True
    raise AssertionError("expected an error")


def file_map(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute

    source_task = ROOT / TASK_ID
    tolerance = read_json(source_task / "hidden/tolerances.json")
    gates: dict[str, bool] = {}

    case1 = read_json(source_task / "public/cases/case_01/input.json")
    invalid = []
    for key, value in (("case_type", "other"), ("p", -1), ("t", 0), ("s", -1.0), ("matrix", "Foo/bar")):
        bad = copy.deepcopy(case1); bad[key] = value; invalid.append(bad)
    bad = copy.deepcopy(case1); del bad["condbound"]; invalid.append(bad)
    bad = copy.deepcopy(case1); bad["condbound"] = "not-inf"; invalid.append(bad)
    bad = copy.deepcopy(case1); bad["t"] = bad["p"] + 1; invalid.append(bad)  # t must be <= p
    bad = copy.deepcopy(case1); bad["v0"] = bad["v0"][:-1]; invalid.append(bad)  # wrong length
    bad = copy.deepcopy(case1); bad["D"] = [2] + bad["D"][1:]; invalid.append(bad)  # not +-1
    bad = copy.deepcopy(case1); bad["perm"] = [bad["perm"][0]] * len(bad["perm"]); invalid.append(bad)  # not distinct
    bad = copy.deepcopy(case1); del bad["v0"]; invalid.append(bad)  # missing field
    gates["invalid_inputs_rejected"] = all(expect_error(validate_case, value) for value in invalid)

    expected = read_json(source_task / "public/cases/case_01/output.json")
    wrong = copy.deepcopy(expected); wrong["cond_truncated"] = expected["cond_truncated"][:-1]
    gates["wrong_output_shape_rejected"] = not compare_output(wrong, expected, tolerance)["passed"]
    nonfinite = copy.deepcopy(expected); nonfinite["cond_truncated"][0] = float("nan")
    gates["nonfinite_output_rejected"] = not compare_output(nonfinite, expected, tolerance)["passed"]

    with tempfile.TemporaryDirectory(prefix="scibench_0022_gates_") as temporary:
        root = Path(temporary)
        task = root / TASK_ID
        shutil.copytree(source_task, task)
        manifest = {"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6}, "tasks": [{
            "task_id": TASK_ID, "lifecycle": "validated",
            "public_files": file_map(task / "public"), "hidden_files": file_map(task / "hidden"),
        }]}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        gates["traversal_rejected"] = expect_error(safe_relative, root, "../escape")
        target_path = root / "target"; target_path.write_text("x", encoding="utf-8")
        link = root / "link"; link.symlink_to(target_path)
        gates["symlink_rejected"] = expect_error(safe_relative, root, "link")

        reference_dir = root / "reference"; reference_dir.mkdir()
        submission = {"schema_version": 4, "task_id": TASK_ID,
                      "entrypoint": [sys.executable, str(ROOT / "reference_cli.py"), "--task-id", TASK_ID]}
        (reference_dir / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
        reference_report_path = root / "reference_report.json"
        reference_report = execute(reference_dir, task, reference_report_path, 1800.0)
        reference_report_path.write_text(json.dumps(reference_report), encoding="utf-8")
        reference = evaluate(task, reference_report_path)

        memorizer_dir = root / "memorizer"; memorizer_dir.mkdir()
        public_map = {
            hashlib.sha256((case / "input.json").read_bytes()).hexdigest(): read_json(case / "output.json")
            for case in sorted((task / "public/cases").iterdir())
        }
        program = "import argparse,hashlib,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();d=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();m=" + repr(public_map) + "\no=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(m.get(d,{})))\n"
        (memorizer_dir / "solution.py").write_text(program, encoding="utf-8")
        (memorizer_dir / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}), encoding="utf-8")
        memorizer_report_path = root / "memorizer_report.json"
        memorizer_report = execute(memorizer_dir, task, memorizer_report_path, 60.0)
        memorizer_report_path.write_text(json.dumps(memorizer_report), encoding="utf-8")
        memorizer = evaluate(task, memorizer_report_path)
        gates["reference_score_one"] = reference["score"] == 1.0 and reference["full_success"]
        gates["public_memorizer_cap"] = memorizer["score"] <= 0.4 and not memorizer["full_success"]

        stale_path = root / "stale.json"; (root / "stale_case_outputs").mkdir()
        gates["stale_output_rejected"] = expect_error(execute, reference_dir, task, stale_path, 1.0)
        mutations = {}
        partial = copy.deepcopy(reference_report); partial["cases"]["hidden"][0]["exit_code"] = 1; mutations["partial_failure"] = partial
        timeout = copy.deepcopy(reference_report); timeout["cases"]["hidden"][0]["timed_out"] = True; mutations["timeout"] = timeout
        mismatch = copy.deepcopy(reference_report); mismatch["cases"]["hidden"][0]["output_sha256"] = "0" * 64; mutations["hash_mismatch"] = mismatch
        for name, report in mutations.items():
            path = root / f"{name}.json"; path.write_text(json.dumps(report), encoding="utf-8")
            result = evaluate(task, path)
            gates[f"{name}_rejected"] = result["score"] == 0 and not result["valid_execution"]
        wrong_task = copy.deepcopy(reference_report); wrong_task["task_id"] = "wrong"
        wrong_path = root / "wrong.json"; wrong_path.write_text(json.dumps(wrong_task), encoding="utf-8")
        gates["wrong_task_id_rejected"] = expect_error(evaluate, task, wrong_path)

    if not all(gates.values()):
        raise AssertionError({key: value for key, value in gates.items() if not value})
    result = {"task_id": TASK_ID, "status": "passed", "gates": gates,
              "reference_score": reference["score"], "reference_full_success": reference["full_success"],
              "public_only_memorizer_score": memorizer["score"]}
    (ROOT / "curation_reports/0022_validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
