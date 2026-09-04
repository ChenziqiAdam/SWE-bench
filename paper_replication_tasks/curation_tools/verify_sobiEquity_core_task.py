#!/usr/bin/env python3
"""G1-G8, scientific hazards, shortcuts, and evaluator gates for 0017_core."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from sobiEquity_core_common import filtered_data, load_fixture, validate_case, validate_output
from sobiEquity_core_scientific import scientific_metrics, solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0017_core"
LEGACY_ID = "scibench_replication_0017"
SHORTCUTS = ("conventional_2sfca", "origin_only", "hub_only", "swapped_denominators", "global_normalization", "strict_threshold", "ignore_threshold", "ignore_hub_filter", "uniform_population", "uniform_rack_capacity", "distance_decay", "retain_zero_denominators")


def read(path: Path): return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def file_map(root: Path) -> dict[str, str]: return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def expect_error(function, *args) -> bool:
    try: function(*args)
    except Exception: return True
    return False


def shortcut_solve(case: dict, mode: str) -> dict:
    clean = validate_case(case)
    hub_filter = "conventional_active" if mode == "ignore_hub_filter" else clean["hub_filter"]
    data = filtered_data(hub_filter)
    threshold = 30.0 if mode == "ignore_threshold" else clean["threshold"]
    boundary = data["travel_time"].lt(threshold) if mode == "strict_threshold" else data["travel_time"].le(threshold)
    reachable = data[boundary].copy()
    if reachable.empty: return {"hub": [], "level_of_service": [], "population_unit": [], "accessibility": []}
    origin_degree = reachable.groupby("UID")["hub"].transform("size").astype(float)
    hub_degree = reachable.groupby("hub")["UID"].transform("size").astype(float)
    if mode == "distance_decay":
        impedance = np.exp(-reachable["travel_time"].to_numpy(dtype=float))
        origin_weight = impedance / pd.Series(impedance, index=reachable.index).groupby(reachable["UID"]).transform("sum")
        hub_weight = impedance / pd.Series(impedance, index=reachable.index).groupby(reachable["hub"]).transform("sum")
    elif mode == "conventional_2sfca": origin_weight = hub_weight = np.ones(len(reachable))
    elif mode == "origin_only": origin_weight, hub_weight = 1.0 / origin_degree, np.ones(len(reachable))
    elif mode == "hub_only": origin_weight, hub_weight = np.ones(len(reachable)), 1.0 / hub_degree
    elif mode == "swapped_denominators": origin_weight, hub_weight = 1.0 / hub_degree, 1.0 / origin_degree
    elif mode == "global_normalization": origin_weight = hub_weight = np.full(len(reachable), 1.0 / len(reachable))
    else: origin_weight, hub_weight = 1.0 / origin_degree, 1.0 / hub_degree
    population = np.ones(len(reachable)) if mode == "uniform_population" else reachable["population"].to_numpy(dtype=float)
    demand = pd.Series(population * np.asarray(origin_weight), index=reachable.index).groupby(reachable["hub"]).sum()
    racks = reachable.groupby("hub")["racks"].first().astype(float)
    if mode == "uniform_rack_capacity": racks[:] = 1.0
    los = (racks / demand).sort_index()
    accessibility = pd.Series(reachable["hub"].map(los).to_numpy() * np.asarray(hub_weight), index=reachable.index).groupby(reachable["UID"]).sum().sort_index()
    if mode == "retain_zero_denominators":
        los = los.reindex(sorted(data["hub"].unique()), fill_value=0.0)
        accessibility = accessibility.reindex(sorted(data["UID"].unique()), fill_value=0.0)
    return validate_output({"hub": [int(x) for x in los.index], "level_of_service": [float(x) for x in los], "population_unit": [int(x) for x in accessibility.index], "accessibility": [float(x) for x in accessibility]})


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate
    from run_submission import execute
    task = ROOT / TASK_ID; legacy = ROOT / LEGACY_ID
    tolerance = read(task / "hidden/tolerances.json"); provenance = read(task / "hidden/provenance.json")
    oracle = read(ROOT / "curation_reports/0017_core_oracle.json"); g6 = read(ROOT / "core_algorithm_audits/0017_core_blind.json"); g7 = read(ROOT / "curation_reports/0017_core_g7.json")
    gates: dict[str, bool] = {"G1_core_centrality": True, "G2_unique_core": True, "G3_scientific_specificity": True, "G4_executable_closure": True,
        "G6_blind_identification": g6.get("G6") == "PASS" and g6.get("pass_count") >= 2 and g6.get("independent_contexts") == 3,
        "G7_blind_implementation": g7.get("G7") == "PASS" and g7.get("full_success") is True and g7.get("hidden_score") == 1.0,
        "G8_oracle_validity": oracle.get("G8") == "PASS" and oracle.get("two_clean_checkouts_match") is True}
    gates["legacy_0017_hashes_unchanged"] = file_map(legacy) == oracle["legacy_hashes_before"]
    gates["task_md_solution_only"] = (task / "public/task.md").read_text() == "solution.py\n"
    inputs = [read(case / "input.json") for split in ("public", "hidden") for case in sorted((task / split / "cases").iterdir())]
    gates["input_contract_bfca_only"] = all(set(value) == {"threshold", "hub_filter"} and not any(key in value for key in ("method", "b2sfca", "c2sfca")) for value in inputs)
    public_text = (task / "public/task.md").read_text() + (task / "public/interface.schema.json").read_text()
    gates["public_instruction_leakage_scan"] = not any(term in public_text.lower() for term in ("bfca", "b2sfca", "c2sfca", "formula", "baseline", "normalization", "algorithm"))
    gates["csv_hash_and_size"] = sha(task / "public/data/travel_time_matrix.csv") == "b5ae188e25523f62d8bd2b064c7cdeeb207d023fb8b9b378143e980de96ec452" and sum(1 for _ in (task / "public/data/travel_time_matrix.csv").open()) == 211606
    gates["public_cases_exact"] = inputs[:3] == [{"hub_filter": "conventional_active", "threshold": 5}, {"hub_filter": "all_active", "threshold": 5}, {"hub_filter": "conventional_active", "threshold": 10}]
    all_cases = [(split, case.name, read(case / "input.json"), read(case / "output.json")) for split in ("public", "hidden") for case in sorted((task / split / "cases").iterdir())]
    gates["independent_all_cases"] = all(compare_output(independent_solve(value), expected, tolerance)["passed"] for _, _, value, expected in all_cases)
    hidden = [(name, value, expected) for split, name, value, expected in all_cases if split == "hidden"]
    metrics = {f"case_{i:02d}": scientific_metrics(value) for i, (_, value, _) in enumerate(hidden, 1)}
    expected_counts = [(188, 187, 103), (5889, 4497, 129), (18586, 6740, 119), (80969, 9162, 131), (190179, 10733, 119)]
    gates["scientific_invariants"] = all((m["reachable_rows"], m["reachable_origins"], m["reachable_hubs"]) == expected_counts[i] and max(m[k] for k in ("origin_weight_max_error", "hub_weight_max_error", "population_conservation_error", "service_conservation_error")) <= 1e-10 for i, m in enumerate(metrics.values()))
    case_shortcut: dict[str, dict[str, bool]] = {}
    for name, value, expected in hidden:
        case_shortcut[name] = {mode: compare_output(shortcut_solve(value, mode), expected, tolerance)["passed"] for mode in SHORTCUTS}
    shortcut_scores = {mode: sum(case_shortcut[name][mode] for name, _, _ in hidden) / len(hidden) for mode in SHORTCUTS}
    gates["all_scientific_shortcuts_fail_suite"] = all(score < 1.0 for score in shortcut_scores.values())
    with tempfile.TemporaryDirectory(prefix="scibench_0017_core_verify_", dir="/tmp") as temporary:
        stage = Path(temporary); staged_task = stage / TASK_ID; shutil.copytree(task, staged_task)
        staged_provenance_path = staged_task / "hidden/provenance.json"; staged_provenance = read(staged_provenance_path); staged_provenance["lifecycle"] = "validated"; staged_provenance_path.write_text(json.dumps(staged_provenance, indent=2, sort_keys=True) + "\n")
        (stage / "manifest.json").write_text(json.dumps({"schema_version": 4, "scoring": {"public_weight": .4, "hidden_weight": .6}, "tasks": [{"task_id": TASK_ID, "lifecycle": "validated", "public_files": file_map(staged_task / "public"), "hidden_files": file_map(staged_task / "hidden")}]}))
        memorizer = stage / "memorizer"; memorizer.mkdir(); public_map = {sha(case / "input.json"): read(case / "output.json") for case in sorted((staged_task / "public/cases").iterdir())}
        source = "import argparse,hashlib,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();m=" + repr(public_map) + "\nk=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(m.get(k,{})))\n"
        (memorizer / "solution.py").write_text(source); (memorizer / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}))
        execution_path = stage / "memorizer_execution.json"; execution = execute(memorizer, staged_task, execution_path, 30); execution_path.write_text(json.dumps(execution)); memorizer_score = evaluate(staged_task, execution_path)
    gates["public_memorizer_hidden_zero"] = memorizer_score["hidden_score"] == 0 and memorizer_score["public_score"] == 1.0
    combined_matrix = {case: {**values, "public_memorizer": False} for case, values in case_shortcut.items()}
    hazard_matrix = {}
    for hazard in provenance["scientific_hazard_catalog"]:
        cells = {}
        for case, failures in combined_matrix.items():
            cells[case] = {"hazard_case": case in hazard["hidden_cases"], "shortcut_failed": {name: not passed for name, passed in failures.items()}}
        relevant_faults = [fault for fault in hazard["faults"] if fault in {*SHORTCUTS, "public_memorizer"}]
        covered = bool(hazard["hidden_cases"]) and len(relevant_faults) == len(hazard["faults"]) and all(any(not combined_matrix[case][fault] for case in hazard["hidden_cases"]) for fault in relevant_faults)
        hazard_matrix[hazard["hazard_id"]] = {"hidden_cases": hazard["hidden_cases"], "faults": hazard["faults"], "cells": cells, "covered": covered}
    gates["G5_hazard_hidden_shortcut_matrix_complete"] = len(hazard_matrix) == len(provenance["scientific_hazard_catalog"]) and all(row["covered"] for row in hazard_matrix.values()) and all(set(row["cells"]) == {name for name, _, _ in hidden} for row in hazard_matrix.values())
    invalid = [{"threshold": 0, "hub_filter": "all_active"}, {"threshold": 31, "hub_filter": "all_active"}, {"threshold": float("nan"), "hub_filter": "all_active"}, {"threshold": 5, "hub_filter": "bad"}, {"threshold": 5, "hub_filter": "all_active", "method": "b2sfca"}]
    gates["invalid_inputs_rejected"] = all(expect_error(validate_case, value) for value in invalid)
    gates["invalid_outputs_rejected"] = expect_error(validate_output, {"accessibility": []}) and expect_error(validate_output, {"hub": [1], "level_of_service": [math.inf], "population_unit": [], "accessibility": []})
    if not all(gates.values()):
        failure = {key: value for key, value in gates.items() if not value}
        report = {"schema_version": 1, "task_id": TASK_ID, "status": "REVISE", "gates": gates, "failures": failure, "case_shortcut_pass_matrix": combined_matrix, "shortcut_hidden_scores": {**shortcut_scores, "public_memorizer": 0.0}, "hazard_hidden_shortcut_matrix": hazard_matrix}
        (ROOT / "curation_reports/0017_core_validation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        raise AssertionError(failure)
    result = {"schema_version": 1, "task_id": TASK_ID, "status": "ACCEPT", "gates": gates, "reference_score": 1.0, "public_memorizer_score": memorizer_score["score"], "case_shortcut_pass_matrix": combined_matrix, "shortcut_hidden_scores": {**shortcut_scores, "public_memorizer": 0.0}, "maximum_shortcut_hidden_score": max(shortcut_scores.values()), "hazard_hidden_shortcut_matrix": hazard_matrix, "scientific_metrics": metrics, "gate_evidence": {"G1": "The target paper's accessibility/equity claims depend on BFCA.", "G2": "Threshold/filter inputs and four-field output uniquely select BFCA, not conventional or extended FCA methods.", "G3": "Dual balancing and conservation are paper-specific scientific behavior.", "G4": "The archived matrix and two scalar inputs close the deterministic contract.", "G5": "Complete literature hazard × hidden case × shortcut matrix in this report.", "G6": "core_algorithm_audits/0017_core_blind.json: 3/3.", "G7": "curation_reports/0017_core_g7.json: independently generated submission scored 1.0.", "G8": "curation_reports/0017_core_oracle.json: two official checkouts plus independent implementation."}}
    (ROOT / "curation_reports/0017_core_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (ROOT / "core_algorithm_audits/0017_core.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__": main()
