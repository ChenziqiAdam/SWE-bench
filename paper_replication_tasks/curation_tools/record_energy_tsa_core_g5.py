#!/usr/bin/env python3
"""Record the 0018_core hazard-by-hidden-case scientific shortcut audit."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from energy_tsa_core_common import (
    TASK_ID,
    _canonical,
    _ward_labels,
    aggregate,
    medoids,
    validate_case,
)
from energy_tsa_core_scientific import _solve_lp, solve

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / TASK_ID
REPORT = ROOT / "curation_reports/official_runs/0018_core/g5_shortcuts/report.json"
SHORTCUTS = (
    "a_priori_only",
    "no_second_planning",
    "wrong_importance",
    "ignore_storage_variables",
    "break_chronology",
    "no_stratification",
    "mean_instead_medoid",
    "wrong_normalization",
    "wrong_extreme_allocation",
)
HAZARDS = (
    {"hazard_id": "H1", "source": "target", "hidden_cases": ["case_01", "case_02"],
     "faults": ["a_priori_only", "no_stratification"]},
    {"hazard_id": "H2", "source": "importance", "hidden_cases": ["case_03", "case_04"],
     "faults": ["wrong_importance"]},
    {"hazard_id": "H3", "source": "chronology", "hidden_cases": ["case_02", "case_07"],
     "faults": ["break_chronology"]},
    {"hazard_id": "H4", "source": "apriori_baseline", "hidden_cases": ["case_01", "case_04", "case_07"],
     "faults": ["mean_instead_medoid"]},
    {"hazard_id": "H5", "source": "target", "hidden_cases": ["case_05"],
     "faults": ["ignore_storage_variables"]},
    {"hazard_id": "H6", "source": "target", "hidden_cases": ["case_05"],
     "faults": ["wrong_normalization"]},
    {"hazard_id": "H7", "source": "target", "hidden_cases": ["case_06"],
     "faults": ["wrong_extreme_allocation"]},
    {"hazard_id": "H8", "source": "target", "hidden_cases": ["case_03", "case_04", "case_08"],
     "faults": ["no_second_planning"]},
)


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def totals(capacities: np.ndarray) -> list[float]:
    return [float(capacities[:3].sum()), float(capacities[3:6].sum()),
            float(capacities[6:9].sum()), float(capacities[9:12].sum()),
            float(capacities[12:19].sum())]


def passed(actual: dict[str, Any] | None, expected: dict[str, Any], tolerance: dict[str, Any]) -> bool:
    if actual is None or set(actual) != {"y", "z", "r", "w"}:
        return False
    for field, rule in tolerance["field_rules"].items():
        left = np.asarray(actual[field])
        right = np.asarray(expected[field])
        if left.shape != right.shape or not np.isfinite(left.astype(float)).all():
            return False
        if not np.allclose(left, right, atol=rule["atol"], rtol=rule["rtol"]):
            return False
    return True


def raw_daily_vectors(values: np.ndarray) -> pd.DataFrame:
    flat = values.reshape(values.shape[0], -1)
    return pd.DataFrame(flat, index=np.arange(values.shape[0]))


def altered_aggregate(
    x: np.ndarray,
    n: int,
    importance: np.ndarray | None,
    p: float,
    operation: np.ndarray | None,
    mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if mode == "no_stratification":
        return aggregate(x, n)
    features = x if operation is None else np.concatenate((x, operation), axis=2)
    vectors = raw_daily_vectors(features) if mode == "wrong_normalization" else None
    if vectors is None:
        from energy_tsa_core_common import daily_vectors
        vectors = daily_vectors(features)
    days = x.shape[0]
    extreme = np.zeros(days, dtype=bool)
    count = min(days, int(round(p * days)))
    if count:
        order = np.lexsort((np.arange(days), -np.asarray(importance, dtype=float)))
        chosen = order[:count]
        if operation is None:
            chosen = chosen[np.asarray(importance)[chosen] > 0]
        extreme[chosen] = True
    if mode == "wrong_extreme_allocation":
        # Common faulty interpretation: allocate p of the representative budget,
        # rather than half of it, to the extreme stratum.
        extreme_clusters = min(max(1, int(round(p * n))), int(extreme.sum()))
    else:
        extreme_clusters = min(int(round(.5 * n)), int(extreme.sum()))
    regular_clusters = n - extreme_clusters
    if regular_clusters > int((~extreme).sum()):
        shift = regular_clusters - int((~extreme).sum())
        extreme_clusters += shift
        regular_clusters -= shift
    labels = np.empty(days, dtype=int)
    if extreme_clusters:
        labels[extreme] = _ward_labels(vectors[extreme], extreme_clusters)
    labels[~extreme] = _ward_labels(vectors[~extreme], regular_clusters) + extreme_clusters
    labels = _canonical(labels)
    if mode == "mean_instead_medoid":
        # A centroid has no source-day index. This shortcut exposes the common
        # first-member surrogate while planning from the centroid itself.
        reps = np.asarray([np.flatnonzero(labels == label)[0] for label in range(n)], dtype=int)
        representative = np.stack([x[labels == label].mean(axis=0) for label in range(n)])
        reconstructed = representative[labels]
    else:
        reps = medoids(vectors, labels)
        reconstructed = x[reps[labels]]
    return reconstructed, labels, reps, np.bincount(labels, minlength=n).astype(int)


def cluster_output(y: list[float], labels: np.ndarray, reps: np.ndarray, weights: np.ndarray) -> dict[str, Any]:
    return {"y": y, "z": labels.tolist(), "r": reps.tolist(), "w": weights.tolist()}


def main() -> None:
    tolerance = read(TASK / "hidden/tolerances.json")
    rows: dict[str, Any] = {}
    started_all = time.monotonic()
    for case_dir in sorted((TASK / "hidden/cases").glob("case_*")):
        case_started = time.monotonic()
        case = read(case_dir / "input.json")
        expected = read(case_dir / "output.json")
        x, n, p, q = validate_case(case)
        correct = solve(case, diagnostics=True)
        diagnostics = correct.pop("diagnostics")
        preliminary = diagnostics["preliminary"]
        operation = diagnostics["operation"]
        correct_z = np.asarray(correct["z"], dtype=int)
        correct_r = np.asarray(correct["r"], dtype=int)
        correct_w = np.asarray(correct["w"], dtype=int)
        preliminary_output = {
            "y": preliminary["totals"], "z": preliminary["z"],
            "r": preliminary["r"], "w": preliminary["w"],
        }
        candidates: dict[str, dict[str, Any] | None] = {
            "a_priori_only": preliminary_output,
            "no_second_planning": cluster_output(preliminary["totals"], correct_z, correct_r, correct_w),
        }
        unmet = np.asarray(operation["unmet_daily"], dtype=float)
        generation = np.asarray(operation["generation_cost_daily"], dtype=float)
        storage = np.asarray(operation["storage_net"], dtype=float).reshape(x.shape[0], 24, 3)
        correct_importance = unmet if q == 0 else generation
        correct_operation = storage if q == 2 else None
        variants = {
            "wrong_importance": (generation if q == 0 else unmet, correct_operation, "normal"),
            "ignore_storage_variables": (correct_importance, None, "normal"),
            "no_stratification": (correct_importance, correct_operation, "no_stratification"),
            "mean_instead_medoid": (correct_importance, correct_operation, "mean_instead_medoid"),
            "wrong_normalization": (correct_importance, correct_operation, "wrong_normalization"),
            "wrong_extreme_allocation": (correct_importance, correct_operation, "wrong_extreme_allocation"),
        }
        for name, (importance, storage_features, mode) in variants.items():
            try:
                if mode == "normal":
                    reconstructed, labels, reps, weights = aggregate(x, n, importance, p, storage_features)
                else:
                    reconstructed, labels, reps, weights = altered_aggregate(
                        x, n, importance, p, storage_features, mode)
                # Exact cluster fields decide the task before capacity optimization.
                # Only solve when they accidentally equal the oracle.
                if (np.array_equal(labels, correct_z) and np.array_equal(reps, correct_r)
                        and np.array_equal(weights, correct_w)):
                    capacity = _solve_lp(reconstructed, labels=labels).capacities
                    y = totals(capacity)
                else:
                    y = correct["y"]
                candidates[name] = cluster_output(y, labels, reps, weights)
            except Exception:
                candidates[name] = None
        # A representative-only sequence discards original-period chronology and weights.
        chronology_capacity = _solve_lp(x[correct_r]).capacities
        candidates["break_chronology"] = cluster_output(
            totals(chronology_capacity), correct_z, correct_r, correct_w)
        pass_map = {name: passed(candidates[name], expected, tolerance) for name in SHORTCUTS}
        rows[case_dir.name] = {
            "shortcut_pass": pass_map,
            "shortcut_failed": {name: not value for name, value in pass_map.items()},
            "runtime_seconds": time.monotonic() - case_started,
        }
    scores = {name: sum(rows[case]["shortcut_pass"][name] for case in rows) / len(rows)
              for name in SHORTCUTS}
    scores["public_memorizer"] = 0.0
    combined = {case: {**row["shortcut_pass"], "public_memorizer": False} for case, row in rows.items()}
    hazard_matrix: dict[str, Any] = {}
    for hazard in HAZARDS:
        covered = all(any(not combined[case][fault] for case in hazard["hidden_cases"])
                      for fault in hazard["faults"])
        hazard_matrix[hazard["hazard_id"]] = {
            **hazard,
            "covered": covered,
            "cells": {case: {"hazard_case": case in hazard["hidden_cases"],
                              "shortcut_failed": {fault: not combined[case][fault]
                                                  for fault in hazard["faults"]}}
                      for case in rows},
        }
    status = "PASS" if all(score < 1.0 for score in scores.values()) and all(
        value["covered"] for value in hazard_matrix.values()) else "FAIL"
    report = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "G5": status,
        "generated_at_unix": time.time(),
        "runtime_seconds": time.monotonic() - started_all,
        "scientific_implementation_sha256": sha(Path(__file__).with_name("energy_tsa_core_scientific.py")),
        "shared_numeric_sha256": sha(Path(__file__).with_name("energy_tsa_core_common.py")),
        "recorder_sha256": sha(Path(__file__)),
        "hidden_inputs_sha256": {case.name: sha(case / "input.json") for case in sorted((TASK / "hidden/cases").glob("case_*"))},
        "hidden_outputs_sha256": {case.name: sha(case / "output.json") for case in sorted((TASK / "hidden/cases").glob("case_*"))},
        "case_shortcut_pass_matrix": combined,
        "shortcut_hidden_scores": scores,
        "maximum_shortcut_hidden_score": max(scores.values()),
        "hazard_hidden_shortcut_matrix": hazard_matrix,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    if status != "PASS":
        raise SystemExit("G5 shortcut audit failed; inspect report")


if __name__ == "__main__":
    main()
