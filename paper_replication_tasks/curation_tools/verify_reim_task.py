#!/usr/bin/env python3
"""Scientific, scoring, and evaluator-safety gates for task 0021."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from reim_common import validate_case

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0021"


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
    gates["independent_reference_all_cases"] = all(
        compare_output(
            read_json(ROOT / f"curation_reports/official_runs/0021/independent/{split}_case_{index:02d}.json"),
            read_json(case / "output.json"),
            tolerance,
        )["passed"]
        for split in ("public", "hidden")
        for index, case in enumerate(sorted((source_task / split / "cases").iterdir()), 1)
    )

    rational = read_json(source_task / "public/cases/case_01/input.json")
    invalid = []
    for key, value in (("case_type", "other"), ("M", -1), ("a", -1.0), ("s", 1.5)):
        bad = copy.deepcopy(rational); bad[key] = value; invalid.append(bad)
    bad = copy.deepcopy(rational); del bad["s"]; invalid.append(bad)
    bad = copy.deepcopy(rational); bad["a"] = 2e-6; invalid.append(bad)  # interval not in REIM.m's supported set
    gates["invalid_family_inputs_rejected"] = all(expect_error(validate_case, value) for value in invalid)

    fem = read_json(source_task / "public/cases/case_02/input.json")
    bad = copy.deepcopy(fem); bad["mesh_type"] = "other"
    gates["invalid_fem_mesh_type_rejected"] = expect_error(validate_case, bad)
    bad = copy.deepcopy(fem); bad["res"] = bad["res"][:-1]
    gates["invalid_fem_res_pol_length_rejected"] = expect_error(validate_case, bad)
    bad = copy.deepcopy(fem); bad["pol"][0] = -1.0
    gates["invalid_fem_negative_pole_rejected"] = expect_error(validate_case, bad)

    bdf2 = read_json(source_task / "public/cases/case_03/input.json")
    bad = copy.deepcopy(bdf2); bad["tol"] = -1.0
    gates["invalid_bdf2_tol_rejected"] = expect_error(validate_case, bad)
    bad = copy.deepcopy(bdf2); bad["mesh_h_exponent"] = 0
    gates["invalid_bdf2_mesh_exponent_rejected"] = expect_error(validate_case, bad)

    expected = read_json(source_task / "public/cases/case_01/output.json")
    wrong = copy.deepcopy(expected); wrong["Linf_error"] = [expected["Linf_error"]]
    gates["wrong_output_shape_rejected"] = not compare_output(wrong, expected, tolerance)["passed"]
    nonfinite = copy.deepcopy(expected); nonfinite["Linf_error"] = float("nan")
    gates["nonfinite_output_rejected"] = not compare_output(nonfinite, expected, tolerance)["passed"]
    near = copy.deepcopy(expected); near["Linf_error"] += tolerance["atol"] * 0.5
    far = copy.deepcopy(expected); target = expected["Linf_error"]
    far["Linf_error"] += tolerance["atol"] * 2 + tolerance["rtol"] * abs(target)
    gates["mixed_comparator_accepts_close"] = compare_output(near, expected, tolerance)["passed"]
    gates["mixed_comparator_rejects_far"] = not compare_output(far, expected, tolerance)["passed"]

    with tempfile.TemporaryDirectory(prefix="scibench_0021_gates_") as temporary:
        root = Path(temporary)
        task = root / TASK_ID
        shutil.copytree(source_task, task)
        manifest = {"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6}, "tasks": [{
            "task_id": TASK_ID, "lifecycle": "validated",
            "public_files": file_map(task / "public"), "hidden_files": file_map(task / "hidden"),
        }]}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        nan_json = root / "nan.json"; nan_json.write_text('{"x":NaN}', encoding="utf-8")
        huge_json = root / "huge.json"; huge_json.write_text('{"x":"' + "a" * (16 * 1024 * 1024) + '"}', encoding="utf-8")
        gates["nan_inf_json_rejected"] = expect_error(read_json, nan_json)
        gates["oversized_json_rejected"] = expect_error(read_json, huge_json)
        gates["traversal_rejected"] = expect_error(safe_relative, root, "../escape")
        target_path = root / "target"; target_path.write_text("x", encoding="utf-8")
        link = root / "link"; link.symlink_to(target_path)
        gates["symlink_rejected"] = expect_error(safe_relative, root, "link")

        reference_dir = root / "reference"; reference_dir.mkdir()
        submission = {"schema_version": 4, "task_id": TASK_ID,
                      "entrypoint": [sys.executable, str(ROOT / "reference_cli.py"), "--task-id", TASK_ID]}
        (reference_dir / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
        reference_report_path = root / "reference_report.json"
        reference_report = execute(reference_dir, task, reference_report_path, 600.0)
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
    (ROOT / "curation_reports/0021_validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
