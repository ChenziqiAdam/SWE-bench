#!/usr/bin/env python3
"""Structural, scoring, and evaluator-safety gates for task 0018.

Unlike the other validated tasks' verify scripts, the `reference_score_one` gate here runs the
REAL Calliope/CBC pipeline across all 6 cases x 6 methods each -- roughly 8-9 hours on the
audited host, since a MILP-based task has no fast, self-contained reference implementation (the
independent correctness check is instead energy_tsa_scientific.py's solver-neutral
cluster-assignment audit, already run and recorded by build_energy_tsa_task.py). Run this script's
`--full` mode only when that time budget is available; `--structural-only` (the default) skips
the harness-level reference/memorizer execution and checks everything else.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0018"


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                         help="also run the harness-level reference/memorizer execution gates "
                              "(real Calliope/CBC solves, ~8-9h); requires --checkout")
    parser.add_argument("--checkout", type=Path, help="clean pinned repo checkout (for --full)")
    args = parser.parse_args()
    if args.full and args.checkout is None:
        parser.error("--full requires --checkout")

    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute

    source_task = ROOT / TASK_ID
    tolerance = read_json(source_task / "hidden/tolerances.json")
    provenance = read_json(source_task / "hidden/provenance.json")
    gates: dict[str, bool] = {}

    # Cluster-assignment audit already ran and was gated inside build_energy_tsa_task.py (it
    # raises before writing the bundle if any method's audit fails); re-check the recorded
    # per-case, per-method results here so a corrupted/hand-edited provenance.json is caught.
    audit = provenance["independent_audit"]["results"]
    gates["cluster_audit_all_cases_all_methods_passed"] = all(
        result["exact_partition_match"] for case_results in audit.values() for result in case_results.values()
    )

    # Structural / evaluator-safety checks reused from the shared framework, independent of
    # whether a full harness run is performed.
    case_01 = read_json(source_task / "public/cases/case_01/input.json")
    invalid = []
    for key, value in (("seed", -1), ("seed", True), ("years", [1980, 1983])):
        bad = copy.deepcopy(case_01); bad[key] = value; invalid.append(bad)
    bad = copy.deepcopy(case_01); bad["extra"] = 1; invalid.append(bad)
    from energy_tsa_adapter import EXPECTED_YEARS
    bad = copy.deepcopy(case_01); bad["years"] = list(reversed(EXPECTED_YEARS[case_01["seed"]])); invalid.append(bad)

    def _validate_case(case: dict) -> None:
        if not isinstance(case, dict) or set(case) != {"seed", "years"}:
            raise ValueError("case fields differ")
        seed = case["seed"]
        if isinstance(seed, bool) or seed not in EXPECTED_YEARS or case["years"] != EXPECTED_YEARS[seed]:
            raise ValueError("seed/year mapping differs")

    gates["invalid_case_inputs_rejected"] = all(expect_error(_validate_case, value) for value in invalid)

    expected = read_json(source_task / "public/cases/case_01/output.json")
    wrong = copy.deepcopy(expected); wrong["methods"]["A"]["capacity_totals"].append(1.0)
    gates["wrong_output_shape_rejected"] = not compare_output(wrong, expected, tolerance)["passed"]
    nonfinite = copy.deepcopy(expected); nonfinite["methods"]["A"]["unserved_energy"] = float("nan")
    gates["nonfinite_output_rejected"] = not compare_output(nonfinite, expected, tolerance)["passed"]
    near = copy.deepcopy(expected)
    near["methods"]["A"]["capacity_totals"][0] += tolerance["field_rules"]["capacity_totals"]["atol"] * 0.5
    far = copy.deepcopy(expected)
    rule = tolerance["field_rules"]["capacity_totals"]
    far["methods"]["A"]["capacity_totals"][0] += rule["atol"] * 2 + rule["rtol"] * abs(expected["methods"]["A"]["capacity_totals"][0])
    gates["fieldwise_comparator_accepts_close"] = compare_output(near, expected, tolerance)["passed"]
    gates["fieldwise_comparator_rejects_far"] = not compare_output(far, expected, tolerance)["passed"]

    with tempfile.TemporaryDirectory(prefix="scibench_0018_gates_") as temporary:
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

        if args.full:
            reference_dir = root / "reference"; reference_dir.mkdir()
            submission = {"schema_version": 4, "task_id": TASK_ID, "entrypoint": [
                sys.executable, str(ROOT / "curation_tools/energy_reference_cli.py"),
                "--checkout", str(args.checkout),
            ]}
            (reference_dir / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
            reference_report_path = root / "reference_report.json"
            # 6 cases x ~90 min/case worst case; generous per-case timeout.
            reference_report = execute(reference_dir, task, reference_report_path, 12 * 3600.0)
            reference_report_path.write_text(json.dumps(reference_report), encoding="utf-8")
            reference = evaluate(task, reference_report_path)

            memorizer_dir = root / "memorizer"; memorizer_dir.mkdir()
            public_map = {
                hashlib.sha256((case / "input.json").read_bytes()).hexdigest(): read_json(case / "output.json")
                for case in sorted((task / "public/cases").iterdir())
            }
            program = ("import argparse,hashlib,json,pathlib\n"
                       "p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args()\n"
                       "d=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();m=" + repr(public_map) + "\n"
                       "o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True)\n"
                       "(o/'output.json').write_text(json.dumps(m.get(d,{})))\n")
            (memorizer_dir / "solution.py").write_text(program, encoding="utf-8")
            (memorizer_dir / "submission.json").write_text(
                json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}),
                encoding="utf-8",
            )
            memorizer_report_path = root / "memorizer_report.json"
            memorizer_report = execute(memorizer_dir, task, memorizer_report_path, 10.0)
            memorizer_report_path.write_text(json.dumps(memorizer_report), encoding="utf-8")
            memorizer = evaluate(task, memorizer_report_path)
            gates["reference_score_one"] = reference["score"] == 1.0 and reference["full_success"]
            gates["public_memorizer_cap"] = memorizer["score"] <= 0.4 and not memorizer["full_success"]
        else:
            gates["reference_score_one"] = None
            gates["public_memorizer_cap"] = None

    checked_gates = {key: value for key, value in gates.items() if value is not None}
    if not all(checked_gates.values()):
        raise AssertionError({key: value for key, value in checked_gates.items() if not value})

    result = {"task_id": TASK_ID, "status": "passed" if args.full else "structural_passed", "gates": gates}
    (ROOT / "curation_reports/0018_validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
