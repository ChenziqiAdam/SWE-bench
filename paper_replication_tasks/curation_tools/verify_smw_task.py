#!/usr/bin/env python3
"""Scientific, official-equivalence, and evaluator-safety gates for task 0014."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

from smw_adapter import validate_case
from smw_scientific import solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0014"


def expect_error(function, *args):
    try:
        function(*args)
    except Exception:
        return True
    raise AssertionError("expected an error")


def main() -> None:
    import sys
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute

    task = ROOT / TASK_ID
    tolerance = read_json(task / "hidden/tolerances.json")
    gates = {}
    gates["independent_reference_all_cases"] = all(
        compare_output(solve(read_json(case / "input.json")), read_json(case / "output.json"), tolerance)["passed"]
        for split in ("public", "hidden") for case in sorted((task / split / "cases").iterdir())
    )
    provenance = read_json(task / "hidden/provenance.json")
    design = provenance["scientific_case_design"]
    gates["large_alpha_case_present"] = design[2]["alpha"] >= 90 and design[2]["k"] == 3
    gates["large_beta_case_present"] = design[3]["beta"] >= 90 and design[3]["k"] == 4
    gates["capacitance_cases_satisfy_theorems"] = all(
        item["theorem_2_assumptions"] and item["theorem_6_assumptions"]
        for row in design[2:4] for item in row["epsilon_validity"]
    )
    sweep_validity = design[4]["epsilon_validity"]
    gates["sweep_crosses_theorem_boundaries"] = (
        any(item["theorem_2_assumptions"] and item["theorem_6_assumptions"] for item in sweep_validity)
        and any(item["theorem_2_assumptions"] and not item["theorem_6_assumptions"] for item in sweep_validity)
        and any(not item["theorem_2_assumptions"] and not item["theorem_6_assumptions"] for item in sweep_validity)
    )
    point = read_json(task / "public/cases/case_01/input.json")
    invalid = []
    bad = copy.deepcopy(point); bad["A"][0].pop(); invalid.append(bad)
    bad = copy.deepcopy(point); bad["U"][0].append(1); invalid.append(bad)
    bad = copy.deepcopy(point); bad["E1"][0][0] = float("nan"); invalid.append(bad)
    bad = copy.deepcopy(point); bad["E2"] = [[0.0]]; invalid.append(bad)
    bad = copy.deepcopy(point); bad["U"] = [[0.0] for _ in bad["U"]]; invalid.append(bad)
    gates["invalid_point_inputs_rejected"] = all(expect_error(validate_case, value) for value in invalid)
    sweep = read_json(task / "public/cases/case_03/input.json")
    invalid_sweeps = []
    for key, value in (("k", sweep["n"]), ("replicates", 0), ("seed", -1), ("epsilon_grid", [1e-6, 0]), ("update_regime", "other")):
        bad = copy.deepcopy(sweep); bad[key] = value; invalid_sweeps.append(bad)
    gates["invalid_sweep_inputs_rejected"] = all(expect_error(validate_case, value) for value in invalid_sweeps)

    expected = read_json(task / "public/cases/case_01/output.json")
    wrong = copy.deepcopy(expected); wrong["epsilon_1"].append(1.0)
    gates["wrong_output_shape_rejected"] = not compare_output(wrong, expected, tolerance)["passed"]
    near = copy.deepcopy(expected); near["forward_full_bound"][0] += tolerance["atol"] * .5
    far = copy.deepcopy(expected); far["forward_full_bound"][0] += tolerance["atol"] * 2 + tolerance["rtol"] * abs(expected["forward_full_bound"][0])
    gates["mixed_comparator_accepts_close"] = compare_output(near, expected, tolerance)["passed"]
    gates["mixed_comparator_rejects_far"] = not compare_output(far, expected, tolerance)["passed"]

    with tempfile.TemporaryDirectory(prefix="scibench_0014_gates_") as temporary:
        root = Path(temporary)
        nan_json = root / "nan.json"; nan_json.write_text('{"x":NaN}', encoding="utf-8")
        huge_json = root / "huge.json"; huge_json.write_text('{"x":"' + "a" * (16 * 1024 * 1024) + '"}', encoding="utf-8")
        gates["nan_inf_rejected"] = expect_error(read_json, nan_json)
        gates["oversized_json_rejected"] = expect_error(read_json, huge_json)
        gates["traversal_rejected"] = expect_error(safe_relative, root, "../escape")
        target = root / "target"; target.write_text("x", encoding="utf-8")
        link = root / "link"; link.symlink_to(target)
        gates["symlink_rejected"] = expect_error(safe_relative, root, "link")

        reference_dir = root / "reference"; reference_dir.mkdir()
        submission = {"schema_version": 4, "task_id": TASK_ID,
                      "entrypoint": [sys.executable, str(ROOT / "reference_cli.py"), "--task-id", TASK_ID]}
        (reference_dir / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
        reference_report_path = root / "reference_report.json"
        reference_report = execute(reference_dir, task, reference_report_path, 30.0)
        reference_report_path.write_text(json.dumps(reference_report), encoding="utf-8")
        reference = evaluate(task, reference_report_path)

        memorizer_dir = root / "memorizer"; memorizer_dir.mkdir()
        public_map = {}
        for case in sorted((task / "public/cases").iterdir()):
            digest = hashlib.sha256((case / "input.json").read_bytes()).hexdigest()
            public_map[digest] = read_json(case / "output.json")
        program = "import argparse,hashlib,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();d=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();m=" + repr(public_map) + "\no=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(m.get(d,{})))\n"
        (memorizer_dir / "solution.py").write_text(program, encoding="utf-8")
        (memorizer_dir / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}), encoding="utf-8")
        memorizer_report_path = root / "memorizer_report.json"
        memorizer_report = execute(memorizer_dir, task, memorizer_report_path, 10.0)
        memorizer_report_path.write_text(json.dumps(memorizer_report), encoding="utf-8")
        memorizer = evaluate(task, memorizer_report_path)
        gates["reference_score_one"] = reference["score"] == 1.0 and reference["full_success"]
        gates["public_memorizer_cap"] = memorizer["score"] <= .4 and not memorizer["full_success"]

        stale_path = root / "stale.json"
        (root / "stale_case_outputs").mkdir()
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
    result = {"task_id": TASK_ID, "status": "passed", "gates": gates, "reference_score": reference["score"],
              "reference_full_success": reference["full_success"], "public_only_memorizer_score": memorizer["score"]}
    (ROOT / "curation_reports/0014_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
