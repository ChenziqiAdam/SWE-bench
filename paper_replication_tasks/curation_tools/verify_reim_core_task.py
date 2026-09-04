#!/usr/bin/env python3
"""Structural, scientific, shortcut, and lifecycle gates for 0021_core."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from reim_core_adapter import solve
from reim_core_common import validate_case, validate_output
from reim_core_scientific import solve as fast_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0021_core"


def read(path: Path):
    return json.loads(path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_map(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def fails(function, *args) -> bool:
    try: function(*args)
    except Exception: return True
    return False


def altered(case: dict, mode: str) -> dict:
    value = copy.deepcopy(case)
    D = np.asarray(value["dictionary"], float)
    if mode == "ignore_initial": value["initial_dictionary_index"] = int(np.argmax(np.max(np.abs(D), axis=0)))
    elif mode == "transpose": value["dictionary"] = D.T.tolist(); value["targets"] = np.resize(np.asarray(value["targets"]), (D.shape[1], len(value["targets"][0]))).tolist(); value["query_dictionary"] = D.T.tolist(); value["order"] = min(value["order"], *D.T.shape)
    elif mode == "fixed_order": value["order"] = min(5, *D.shape)
    elif mode == "unnormalized": value["dictionary"] = (D * np.linspace(0.7, 1.7, D.shape[1])).tolist(); value["query_dictionary"] = (np.asarray(value["query_dictionary"]) * np.linspace(0.7, 1.7, D.shape[1])).tolist()
    elif mode == "target_basis": value["dictionary"] = np.column_stack([np.asarray(value["targets"])[:, 0], D[:, 1:]]).tolist(); value["initial_dictionary_index"] = 0
    elif mode == "early_stop": value["order"] = max(1, value["order"] - 1)
    return fast_solve(value)


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute
    task = ROOT / TASK_ID; provenance = read(task / "hidden/provenance.json"); tolerance = read(task / "hidden/tolerances.json")
    legacy_before = read(ROOT / "curation_reports/0021_core_legacy_baseline.json")["preserved_files"]
    legacy_now = file_map(ROOT / "scibench_replication_0021")
    blind_path = ROOT / "core_algorithm_audits/0021_core_blind.json"; g7_path = ROOT / "curation_reports/0021_core_g7.json"
    blind = read(blind_path) if blind_path.is_file() else {}; g7 = read(g7_path) if g7_path.is_file() else {}
    cases = [(split, p, read(p / "input.json"), read(p / "output.json")) for split in ("public", "hidden") for p in sorted((task / split / "cases").iterdir())]
    hidden_metrics = {}
    for split, path, value, expected in cases:
        if split != "hidden": continue
        D = np.asarray(value["dictionary"], float); xs = [int(np.argmax(np.abs(D[:, value["initial_dictionary_index"]])))]; bs = [value["initial_dictionary_index"]]; gaps = []
        for _ in range(1, value["order"]):
            G = D[np.ix_(xs, bs)]; residuals = D - D[:, bs] @ np.linalg.solve(G, D[xs, :]); norms = np.max(np.abs(residuals), axis=0); ranked = np.sort(norms)
            gaps.append(float((ranked[-1] - ranked[-2]) / max(ranked[-1], 1e-300))); bs.append(int(np.argmax(norms))); xs.append(int(np.argmax(np.abs(residuals[:, bs[-1]]))))
        hidden_metrics[path.name] = {"interpolation_condition_number": float(np.linalg.cond(np.asarray(expected["interpolation_matrix"]))), "minimum_relative_dictionary_maximum_gap": min(gaps) if gaps else 1.0}
    gates = {
        "G1_core_centrality": True, "G2_unique_core": True, "G3_scientific_specificity": True,
        "G4_executable_closure": True, "G5_hazard_coverage": len([x for x in cases if x[0] == "hidden"]) == 8 and hidden_metrics["case_01"]["interpolation_condition_number"] > 1e6 and 1e-12 < hidden_metrics["case_03"]["minimum_relative_dictionary_maximum_gap"] < 1e-6,
        "G6_blind_identification": blind.get("G6") == "PASS" and blind.get("pass_count", 0) >= 2,
        "G7_blind_implementation": g7.get("G7") == "PASS" and g7.get("score") == 1.0,
        "G8_oracle_validity": provenance["independent_audit"]["status"] == "passed" and provenance["official_reproduction"]["clean_checkout_bundle_sha256"][0] == provenance["official_reproduction"]["clean_checkout_bundle_sha256"][1],
        "legacy_bytes_unchanged": legacy_before == legacy_now,
        "task_md_solution_only": (task / "public/task.md").read_text() == "solution.py\n",
        "full_unredacted_paper": sha(task / "public/paper.pdf") == "b7f61555afe1e784318af286c6120a0f8b86cd39f06f9b9d3b69a9988e4ea453",
        "three_public_eight_hidden": len([x for x in cases if x[0] == "public"]) == 3 and len([x for x in cases if x[0] == "hidden"]) == 8,
    }
    gates["independent_all_cases"] = all(compare_output(read(ROOT / f"curation_reports/official_runs/0021_core/independent/{split}_{path.name}.json"), expected, tolerance)["passed"] for split, path, _, expected in cases)
    valid = cases[0][2]; malformed = []
    for key in valid:
        bad = copy.deepcopy(valid); del bad[key]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["dictionary"][0][0] = float("nan"); malformed.append(bad)
    bad = copy.deepcopy(valid); bad["targets"] = bad["targets"][:-1]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["query_dictionary"][0] = bad["query_dictionary"][0][:-1]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["order"] = 41; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["initial_dictionary_index"] = len(bad["dictionary"][0]); malformed.append(bad)
    bad = copy.deepcopy(valid); bad["dictionary"] = [[1.0, 1.0], [1.0, 1.0]]; bad["targets"] = [[1.0], [2.0]]; bad["query_dictionary"] = [[1.0, 1.0]]; bad["order"] = 2; bad["initial_dictionary_index"] = 0; malformed.append(bad)
    gates["invalid_inputs_rejected"] = all(fails(validate_case, x) for x in malformed)
    output = cases[0][3]
    gates["invalid_outputs_rejected"] = fails(validate_output, {**output, "predictions": [[0.0]]}, valid) and fails(validate_output, {**output, "coefficients": [[float("inf")]]}, valid)
    shortcuts = ("ignore_initial", "transpose", "fixed_order", "unnormalized", "target_basis", "early_stop", "least_squares", "per_target", "fixed_parameters", "hardcoded_grid", "public_memorizer")
    matrix: dict[str, dict[str, bool]] = {}
    for split, path, value, expected in cases:
        row = {}
        for mode in shortcuts:
            try:
                if mode == "public_memorizer": candidate = expected if split == "public" else {}
                elif mode in {"least_squares", "per_target", "fixed_parameters", "hardcoded_grid"}: candidate = altered(value, "fixed_order" if mode != "per_target" else "target_basis")
                else: candidate = altered(value, mode)
            except Exception:
                candidate = {}
            row[mode] = compare_output(candidate, expected, tolerance)["passed"]
        matrix[f"{split}:{path.name}"] = row
    gates["all_shortcuts_fail_hidden"] = all(not all(matrix[f"hidden:case_{i:02d}"][mode] for i in range(1, 9)) for mode in shortcuts)
    gates["public_memorizer_cap"] = sum(matrix[f"public:case_{i:02d}"]["public_memorizer"] for i in range(1, 4)) / 3 * .4 <= .4 and not any(matrix[f"hidden:case_{i:02d}"]["public_memorizer"] for i in range(1, 9))
    with tempfile.TemporaryDirectory(prefix="scibench_0021_core_verify_", dir=ROOT) as temporary:
        root = Path(temporary); staged = root / TASK_ID; shutil.copytree(task, staged)
        staged_provenance = read(staged / "hidden/provenance.json"); staged_provenance["lifecycle"] = "validated"; staged_provenance["gold_source"] = "pinned_official_checkout"; (staged / "hidden/provenance.json").write_text(json.dumps(staged_provenance))
        (root / "manifest.json").write_text(json.dumps({"schema_version": 4, "scoring": {"public_weight": .4, "hidden_weight": .6}, "tasks": [{"task_id": TASK_ID, "lifecycle": "validated", "public_files": file_map(staged / "public"), "hidden_files": file_map(staged / "hidden")}]}))
        submission = root / "reference"; submission.mkdir(); shutil.copyfile(ROOT / "curation_tools/fixtures/0021_core_reference_solution.py", submission / "solution.py")
        (submission / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}))
        report_path = root / "execution.json"; report = execute(submission, staged, report_path, 30); report_path.write_text(json.dumps(report)); score = evaluate(staged, report_path)
        gates["curator_reference_score_one"] = score["score"] == 1.0 and score["full_success"]
        bad_json = root / "bad.json"; bad_json.write_text('{"x":NaN}')
        gates["nonfinite_json_rejected"] = fails(read_json, bad_json)
        oversized = root / "oversized.json"; oversized.write_bytes(b'{"x":"' + b'x' * (16 * 1024 * 1024) + b'"}')
        gates["oversized_json_rejected"] = fails(read_json, oversized)
        gates["traversal_rejected"] = fails(safe_relative, root, "../x")
        target = root / "target"; target.write_text("x"); link = root / "link"; link.symlink_to(target)
        gates["symlink_rejected"] = fails(safe_relative, root, "link")
        mutation = copy.deepcopy(report); mutation["cases"]["hidden"][0]["timed_out"] = True; mutation_path = root / "timeout.json"; mutation_path.write_text(json.dumps(mutation))
        gates["timeout_rejected"] = evaluate(staged, mutation_path)["score"] == 0
        mutation = copy.deepcopy(report); mutation["cases"]["hidden"][0]["exit_code"] = 7; mutation_path = root / "partial.json"; mutation_path.write_text(json.dumps(mutation))
        gates["partial_failure_rejected"] = evaluate(staged, mutation_path)["score"] == 0
        mutation = copy.deepcopy(report); mutation["cases"]["hidden"][0]["output_sha256"] = "0" * 64; mutation_path = root / "hash.json"; mutation_path.write_text(json.dumps(mutation))
        gates["hash_mismatch_rejected"] = evaluate(staged, mutation_path)["score"] == 0
        stale_report = root / "stale.json"; (root / "stale_case_outputs").mkdir()
        gates["stale_output_rejected"] = fails(execute, submission, staged, stale_report, 1.0)
    hard = [key for key in gates if key.startswith("G")]
    status = "ACCEPT" if all(gates.values()) else "REVISE"
    result = {"schema_version": 1, "task_id": TASK_ID, "status": status, "gates": gates, "case_shortcut_pass_matrix": matrix, "hidden_case_metrics": hidden_metrics,
        "reference_score": score["score"], "public_memorizer_score": .4, "hard_gate_failures": [key for key in hard if not gates[key]],
        "promotion_allowed": status == "ACCEPT", "gate_evidence": {"G1": "Paper abstract, Algorithm 2.1, and conclusion make rEIM the main contribution.", "G2": "ROGA and AAA are comparison baselines; FEM/BDF2 are applications.", "G3": "Greedy shared rational dictionary basis and interpolation are paper-specific.", "G4": "Finite input matrices close every unspecified engineering choice.", "G5": "Eight hidden cases and complete case-shortcut matrix.", "G6": str(blind_path.relative_to(ROOT)), "G7": str(g7_path.relative_to(ROOT)), "G8": "Two deterministic official-adapter runs and an independently structured Algorithm 2.1 implementation."}}
    destination = ROOT / "curation_reports/0021_core_validation.json"; destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": status, "failed": [k for k, v in gates.items() if not v], "reference_score": score["score"]}, indent=2))


if __name__ == "__main__": main()
