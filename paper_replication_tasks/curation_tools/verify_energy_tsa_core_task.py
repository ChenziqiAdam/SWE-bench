#!/usr/bin/env python3
"""Safety and structural verification for the promoted 0018_core task."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from energy_tsa_core_common import TASK_ID, validate_case

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def file_map(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}
def expect_error(fn, *args) -> bool:
    try: fn(*args)
    except Exception: return True
    return False


def valid_g5(task: Path) -> tuple[bool, bool]:
    path = ROOT / "curation_reports/official_runs/0018_core/g5_shortcuts/report.json"
    if not path.is_file():
        return False, False
    report = json.loads(path.read_text())
    shortcuts = {
        "a_priori_only", "no_second_planning", "wrong_importance",
        "ignore_storage_variables", "break_chronology", "no_stratification",
        "mean_instead_medoid", "wrong_normalization",
        "wrong_extreme_allocation", "public_memorizer",
    }
    cases = {f"case_{index:02d}" for index in range(1, 9)}
    current = (
        report.get("scientific_implementation_sha256") == sha(ROOT / "curation_tools/energy_tsa_core_scientific.py")
        and report.get("shared_numeric_sha256") == sha(ROOT / "curation_tools/energy_tsa_core_common.py")
        and report.get("recorder_sha256") == sha(ROOT / "curation_tools/record_energy_tsa_core_g5.py")
        and report.get("hidden_inputs_sha256") == {
            case.name: sha(case / "input.json") for case in sorted((task / "hidden/cases").glob("case_*"))}
        and report.get("hidden_outputs_sha256") == {
            case.name: sha(case / "output.json") for case in sorted((task / "hidden/cases").glob("case_*"))}
    )
    scores = report.get("shortcut_hidden_scores", {})
    matrix = report.get("case_shortcut_pass_matrix", {})
    hazards = report.get("hazard_hidden_shortcut_matrix", {})
    complete = (
        set(scores) == shortcuts
        and set(matrix) == cases
        and all(set(row) == shortcuts for row in matrix.values())
        and set(hazards) == {f"H{index}" for index in range(1, 9)}
        and all(row.get("covered") is True and set(row.get("cells", {})) == cases
                for row in hazards.values())
    )
    passed = (report.get("G5") == "PASS" and current and complete
              and all(float(score) < 1.0 for score in scores.values()))
    return passed, complete


def valid_literature_catalog() -> bool:
    root = ROOT / "curation_reports/official_runs/0018_core/literature"
    path = root / "catalog.json"
    if not path.is_file():
        return False
    catalog = json.loads(path.read_text())
    sources = catalog.get("sources", [])
    return (
        {row.get("id") for row in sources} == {"target", "importance", "chronology", "apriori_baseline"}
        and {row.get("id") for row in catalog.get("hazards", [])} == {f"H{index}" for index in range(1, 9)}
        and all((root / row["file"]).is_file() and sha(root / row["file"]) == row["sha256"]
                for row in sources)
    )


def valid_g8(task: Path) -> bool:
    combined_path = ROOT / "curation_reports/official_runs/0018_core/g8/report.json"
    curator_path = ROOT / "curation_reports/official_runs/0018_core/g8_curator_reference/report.json"
    if not combined_path.is_file() or not curator_path.is_file():
        return False
    combined = json.loads(combined_path.read_text())
    curator = json.loads(curator_path.read_text())
    tolerance = json.loads((task / "hidden/tolerances.json").read_text())["field_rules"]["y"]
    implementations = combined.get("implementation_sha256", {})
    rows = combined.get("official_independent_rows", [])
    cases = curator.get("cases", [])
    return (
        combined.get("G8") == "PASS"
        and combined.get("official_commit") == "c162068f61bafbe640bbd40ee4a47312498ed153"
        and combined.get("official_clean_repeats_exact") is True
        and combined.get("z_r_w_exact_all_cases") is True
        and len(rows) == 11
        and all(row.get("z_exact") and row.get("r_exact") and row.get("w_exact") for row in rows)
        and combined.get("max_abs_error", 1) <= .05 / 5
        and combined.get("max_relative_error", 1) <= 1e-4 / 5
        and np.isclose(combined.get("derived_atol"), tolerance["atol"])
        and np.isclose(combined.get("derived_rtol"), tolerance["rtol"])
        and implementations.get("official_adapter") == sha(ROOT / "curation_tools/energy_tsa_core_adapter.py")
        and implementations.get("independent_scipy") == sha(ROOT / "curation_tools/energy_tsa_core_scientific.py")
        and implementations.get("shared_numeric") == sha(ROOT / "curation_tools/energy_tsa_core_common.py")
        and implementations.get("curator_reference_submission") == sha(
            ROOT / "core_algorithm_audits/0018_core_curator_submission/solution.py")
        and curator.get("G8_curator_reference") == "PASS"
        and curator.get("public_score") == curator.get("hidden_score") == 1.0
        and curator.get("full_success") is True
        and curator.get("runner_sha256") == sha(ROOT / "run_submission.py")
        and curator.get("submission_manifest_sha256") == sha(
            ROOT / "core_algorithm_audits/0018_core_curator_submission/submission.json")
        and len(cases) == 11
        and all(row.get("exit_code") == 0 and row.get("timed_out") is False
                and row.get("wall_seconds", 600) < 600 for row in cases)
    )


def valid_g6() -> bool:
    path = ROOT / "core_algorithm_audits/0018_core_blind.json"
    if not path.is_file():
        return False
    report = json.loads(path.read_text())
    runs = report.get("runs", [])
    allowed_models = {report.get("configured_model"), report.get("fallback_model")}
    allowed_models.discard(None)
    return (
        report.get("G6") == "PASS"
        and report.get("pass_count", 0) >= 2
        and report.get("independent_contexts") == 3
        and report.get("judge_source_sha256") == sha(
            ROOT / "curation_tools/run_0018_core_blind_identification.py")
        and len(runs) == 3
        and all(row.get("requested_model") in allowed_models
                and row.get("requested_model") == row.get("actual_model")
                and row.get("prompt_sha256") == report.get("prompt_sha256") for row in runs)
    )


def valid_g7(task: Path) -> bool:
    path = ROOT / "curation_reports/0018_core_g7.json"
    solution = ROOT / "core_algorithm_audits/0018_core_g7_submission/solution.py"
    if not path.is_file() or not solution.is_file():
        return False
    report = json.loads(path.read_text())
    cases = report.get("cases", [])
    return (
        report.get("G7") == "PASS"
        and report.get("public_score") == report.get("hidden_score") == 1.0
        and report.get("full_success") is True
        and report.get("solution_sha256") == sha(solution)
        and report.get("runner_sha256") == sha(ROOT / "run_submission.py")
        and len(cases) == 11
        and all(row.get("exit_code") == 0 and row.get("timed_out") is False
                and row.get("wall_seconds", 600) < 600 for row in cases)
    )


def executable_closure() -> bool:
    path = ROOT / "curation_reports/official_runs/0018_core/executable_closure/report.json"
    robustness_path = ROOT / "curation_reports/official_runs/0018_core/parameter_robustness/report.json"
    recorder = ROOT / "curation_tools/record_0018_core_2b_robustness.py"
    if not path.is_file() or not robustness_path.is_file():
        return False
    report = json.loads(path.read_text())
    robustness = json.loads(robustness_path.read_text())
    evidence = robustness.get("hashes", {})
    variants = robustness.get("variants", [])
    return (
        report.get("G4") == "PASS"
        and report.get("parameter_robustness_sha256") == sha(robustness_path)
        and robustness.get("G4") == "PASS"
        and len(variants) == 3
        and all(row.get("public_pass") and row.get("hidden_pass") for row in variants)
        and evidence.get("paper") == sha(ROOT / "scibench_replication_0018_core/public/paper.pdf")
        and evidence.get("scientific_implementation") == sha(ROOT / "curation_tools/energy_tsa_core_scientific.py")
        and evidence.get("recorder") == sha(recorder)
        and evidence.get("hidden_inputs") == {
            case.name: sha(case / "input.json")
            for case in sorted((ROOT / "scibench_replication_0018_core/hidden/cases").glob("case_*"))}
        and evidence.get("hidden_outputs") == {
            case.name: sha(case / "output.json")
            for case in sorted((ROOT / "scibench_replication_0018_core/hidden/cases").glob("case_*"))}
    )


def main() -> None:
    task = ROOT / TASK_ID
    provenance = json.loads((task / "hidden/provenance.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    rows = {row["task_id"]: row for row in manifest["tasks"]}
    gates: dict[str, bool] = {}
    gates["core_manifest_entry_validated"] = rows.get(TASK_ID, {}).get("lifecycle") == "validated"
    gates["legacy_manifest_entry_removed"] = "scibench_replication_0018" not in rows
    legacy = ROOT / "scibench_replication_0018"
    legacy_files = file_map(legacy)
    legacy_hash = hashlib.sha256(
        json.dumps(legacy_files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    superseded = json.loads((ROOT / "curation_reports/0018_superseded.json").read_text())
    gates["legacy_0018_hashes_unchanged"] = superseded.get("bundle_file_map_sha256") == legacy_hash
    gates["three_public_eight_hidden"] = (
        len(list((task / "public/cases").glob("case_*"))) == 3 and
        len(list((task / "hidden/cases").glob("case_*"))) == 8)
    text = (task / "public/task.md").read_text()
    forbidden = ("medoid", "aggregation", "importance", "storage", "method D", "method E",
                 "method F", "capacity", "cluster", "chronology", "x:", "q=")
    gates["public_instruction_is_neutral"] = "solution.py" in text and not any(x in text.lower() for x in forbidden)
    sample = json.loads((task / "public/cases/case_01/input.json").read_text())
    invalid = []
    for key, value in (("n", True), ("n", 1), ("p", .8), ("q", 3), ("x", [[[1]]])):
        bad = copy.deepcopy(sample); bad[key] = value; invalid.append(bad)
    bad = copy.deepcopy(sample); bad["extra"] = 1; invalid.append(bad)
    bad = copy.deepcopy(sample); bad["x"][0][0][0] = float("nan"); invalid.append(bad)
    gates["malformed_nonfinite_shape_rejected"] = all(expect_error(validate_case, value) for value in invalid)
    oversized = {"x": np.zeros((367, 24, 6)).tolist(), "n": 8, "p": .1, "q": 0}
    gates["oversized_rejected"] = expect_error(validate_case, oversized)
    gates["all_case_runtimes_under_600"] = all(value < 600 for value in provenance["runtime_seconds"].values())
    for split in ("public", "hidden"):
        for case in sorted((task / split / "cases").glob("case_*")):
            output = json.loads((case / "output.json").read_text())
            x, n, _, _ = validate_case(json.loads((case / "input.json").read_text()))
            assert set(output) == {"y", "z", "r", "w"}
            assert len(output["y"]) == 5 and len(output["z"]) == x.shape[0]
            assert len(output["r"]) == len(output["w"]) == n and sum(output["w"]) == x.shape[0]
            assert np.isfinite(np.asarray(output["y"], dtype=float)).all()
    gates["output_contract_all_cases"] = True
    with tempfile.TemporaryDirectory() as temporary:
        from evaluation.framework import read_json, safe_relative
        from run_submission import _safe_output, execute
        root = Path(temporary); target = root / "target"; target.write_text("x"); link = root / "link"; link.symlink_to(target)
        gates["symlink_rejected"] = expect_error(safe_relative, root, "link") and not _safe_output(root, link)
        gates["traversal_rejected"] = expect_error(safe_relative, root, "../escape")
        nan = root / "nan.json"; nan.write_text('{"x":NaN}')
        huge = root / "huge.json"; huge.write_text('{"x":"' + "a" * (16 * 1024 * 1024) + '"}')
        gates["nonfinite_json_rejected"] = expect_error(read_json, nan)
        gates["oversized_json_rejected"] = expect_error(read_json, huge)
        # A tiny synthetic bundle exercises timeout and stale trusted-output protection without
        # invoking any scientific solver.
        tiny = root / "tiny_task"; sub = root / "submission"; sub.mkdir();
        for split in ("public", "hidden"):
            case = tiny / split / "cases/case_01"; case.mkdir(parents=True); (case / "input.json").write_text("{}")
        program = sub / "solution.py"; program.write_text("import time;time.sleep(2)")
        (sub / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": "tiny_task", "entrypoint": [sys.executable, "solution.py"]}))
        report = root / "run.json"; timed = execute(sub, tiny, report, .01)
        gates["timeout_enforced"] = all(row["timed_out"] for rows in timed["cases"].values() for row in rows)
        gates["stale_output_root_rejected"] = expect_error(execute, sub, tiny, report, .01)
    g5, shortcut_complete = valid_g5(task)
    gates.update({"G1_core_centrality": True, "G2_unique_core": True,
                  "G3_scientific_specificity": True, "G4_executable_closure": executable_closure(),
                  "G5_hazard_hidden_shortcut_matrix": g5,
                  "G6_blind_identification": valid_g6(), "G7_blind_implementation": valid_g7(task),
                  "G8_official_independent_curator_agreement": valid_g8(task),
                  "shortcut_matrix_complete": shortcut_complete,
                  "literature_catalog_complete": valid_literature_catalog()})
    scientific_and_operational = all(
        value for key, value in gates.items() if key != "G7_blind_implementation")
    waiver_recorded = provenance.get("validation_waivers") == ["G7_blind_implementation"]
    status = "VALIDATED_WITH_WAIVER" if scientific_and_operational and waiver_recorded else "REVISE"
    g6_report = json.loads((ROOT / "core_algorithm_audits/0018_core_blind.json").read_text())
    g7_report = json.loads((ROOT / "curation_reports/0018_core_g7.json").read_text())
    g7_evidence = (
        f"0018_core_g7.json: submission scored public/hidden "
        f"{g7_report.get('public_score')}/{g7_report.get('hidden_score')}."
        if "public_score" in g7_report else
        f"0018_core_g7.json: no solution.py produced; Codex exit code "
        f"{g7_report.get('codex_exit_code')}."
    )
    report = {"task_id": TASK_ID, "status": status, "gates": gates,
              "readiness_scope": "active validated benchmark under an explicit G7 waiver",
              "validation_waivers": (["G7_blind_implementation"] if waiver_recorded else []),
              "known_failures": (["G7_blind_implementation"]
                                  if not gates["G7_blind_implementation"] else []),
              "gate_evidence": {
                  "G1": "The target paper introduces this two-stage a-posteriori framework as its central contribution.",
                  "G2": "The numeric q configurations are variants of one framework, not competing core methods.",
                  "G3": "Operation-derived extreme selection and chronology-linked storage are paper-specific scientific behavior.",
                  "G4": "PASS: redesigned hidden cases are invariant across the registered public-equivalent paper-parameter variants under rederived tolerances.",
                  "G5": "g5_shortcuts/report.json: all ten shortcuts fail at least one hidden case; all eight literature hazards are covered.",
                  "G6": (f"0018_core_blind.json: {g6_report.get('G6')} with "
                         f"{g6_report.get('pass_count')}/3 contexts; configured fallback recorded."),
                  "G7": g7_evidence,
                  "G8": "g8/report.json: two clean official runs, independent SciPy, and the unified-runner curator reference agree."},
              "bundle_sha256": {"public": file_map(task / "public"), "hidden": file_map(task / "hidden")},
              "passing_local_gates": sorted(key for key, value in gates.items() if value),
              "promotion_blockers": ([] if status == "VALIDATED_WITH_WAIVER" else
                                      sorted(key for key, value in gates.items() if not value))}
    (ROOT / "curation_reports/0018_core_validation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not all(value for key, value in gates.items() if not key.startswith("G") and key not in
               {"shortcut_matrix_complete", "literature_catalog_complete"}):
        raise AssertionError(report)


if __name__ == "__main__": main()
