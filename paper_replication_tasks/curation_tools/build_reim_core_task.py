#!/usr/bin/env python3
"""Build the non-promoted 0021_core candidate and its reproducibility evidence."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
from pathlib import Path

import numpy as np

from reim_core_adapter import solve as official_solve
from reim_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0021_core"
COMMIT = "9760b18408f17d226124a93755294a95f15230f8"
PAPER = ROOT / "core_algorithm_review_v2/sources/0021_arxiv_2406.19339v3.pdf"
SOURCE = ROOT / "curation_tools/reim_patched/REIM.m"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def case(x: np.ndarray, b: np.ndarray, q: np.ndarray, order: int, initial: int, target_names: tuple[str, ...]) -> dict:
    eta = float(np.min(x))
    dictionary = (eta + b[None, :]) / (x[:, None] + b[None, :])
    query_dictionary = (eta + b[None, :]) / (q[:, None] + b[None, :])
    functions = {
        "power_02": x ** -0.2,
        "power_07": x ** -0.7,
        "exponential": np.exp(-1.7 * x / np.max(x)),
        "logarithmic": np.log1p(4.0 * x) / np.log1p(4.0 * eta),
        "oscillatory": 1.0 + 0.2 * np.cos(3.0 * np.pi * (x - eta) / (np.max(x) - eta)),
        "outside": np.sqrt(x) + 0.15 / (x + 0.37 * np.max(x)),
    }
    return {
        "order": order,
        "dictionary": dictionary.tolist(),
        "targets": np.column_stack([functions[name] for name in target_names]).tolist(),
        "query_dictionary": query_dictionary.tolist(),
        "initial_dictionary_index": initial,
    }


def cases() -> tuple[list[dict], list[dict]]:
    geom = lambda a, z, n: np.geomspace(a, z, n)
    public = [
        case(geom(1e-2, 1, 41), geom(1e-3, 5, 25), geom(1e-2, 1, 29), 5, 0, ("power_02", "power_07")),
        case(np.unique(np.r_[geom(1e-4, 2e-2, 28), np.linspace(2e-2, 1, 35)]), geom(1e-5, 10, 32), geom(1e-4, 1, 37), 7, 9, ("exponential", "logarithmic", "outside")),
        case(np.sort(np.r_[geom(5e-3, .2, 21), np.linspace(.23, 2, 27)]), geom(2e-4, 20, 36), np.linspace(5e-3, 2, 33), 9, 35, ("oscillatory", "power_07")),
    ]
    hidden = [
        case(geom(1e-8, 1, 101), geom(1e-10, 10, 55), geom(1e-8, 1, 47), 35, 0, ("power_02", "power_07", "outside")),
        case(np.unique(np.r_[geom(1e-7, 1e-3, 75), np.linspace(1e-3, 1, 26)]), geom(1e-9, 3, 48), geom(1e-7, 1, 43), 12, 17, ("logarithmic", "power_07")),
        case(geom(1e-10, 1e4, 111), geom(1e-12, 1e6, 52), geom(1e-10, 1e4, 39), 11, 51, ("power_02", "exponential", "outside")),
        case(np.sort(np.r_[geom(2e-5, .03, 37), [.031, .08, .11, .19, .41, .77, 1.3, 2.0]]), np.sort(np.r_[geom(1e-6, .2, 27), [.23, .51, 1.7, 8.0]]), np.linspace(2e-5, 2, 35), 10, 8, ("oscillatory", "outside")),
        case(geom(3e-3, 3, 61), geom(2e-4, 30, 41), geom(3e-3, 3, 31), 8, 27, ("power_02", "exponential")),
        case(geom(8e-5, 1, 73), geom(1e-6, 12, 45), geom(8e-5, 1, 51), 13, 3, ("power_02", "power_07", "exponential", "logarithmic", "oscillatory", "outside")),
        case(geom(1e-3, 7, 67), geom(2e-5, 70, 43), np.sort(np.r_[geom(1e-3, .2, 22), np.linspace(.21, 7, 29)]), 9, 40, ("outside", "oscillatory", "logarithmic")),
        case(np.sort(np.r_[geom(1e-6, .01, 49), np.linspace(.0101, 1, 40)]), geom(1e-8, 4, 49), geom(1e-6, 1, 37), 14, 24, ("power_07", "outside")),
    ]
    return public, hidden


def numeric_fields(left: dict, right: dict, name: str) -> tuple[float, float]:
    a = np.asarray(left[name], dtype=float); b = np.asarray(right[name], dtype=float)
    difference = np.abs(a - b)
    return float(difference.max(initial=0)), float((difference / np.maximum(np.abs(a), 1e-300)).max(initial=0))


def main() -> None:
    task = ROOT / TASK_ID
    if task.exists() and not (task / "public/cases").is_dir():
        raise RuntimeError(f"refusing to overwrite unexpected path {task}")
    if sha(PAPER) != "b7f61555afe1e784318af286c6120a0f8b86cd39f06f9b9d3b69a9988e4ea453":
        raise RuntimeError("full arXiv v3 paper hash mismatch")
    public, hidden = cases()
    evidence = ROOT / "curation_reports/official_runs/0021_core"
    records, official_outputs, independent_outputs = [], [], []
    maxima = {name: [0.0, 0.0] for name in ("interpolation_matrix", "coefficients", "predictions")}
    for split, collection in (("public", public), ("hidden", hidden)):
        for number, value in enumerate(collection, 1):
            case_id = f"case_{number:02d}"
            official = official_solve(value)
            second = official_solve(value)
            audit = independent_solve(value)
            if official["sample_indices"] != audit["sample_indices"] or official["dictionary_indices"] != audit["dictionary_indices"]:
                raise RuntimeError(f"independent greedy choices differ: {split}/{case_id}")
            for field in maxima:
                absolute, relative = numeric_fields(official, audit, field)
                maxima[field][0] = max(maxima[field][0], absolute)
                maxima[field][1] = max(maxima[field][1], relative)
            case_root = task / split / "cases" / case_id
            write(case_root / "input.json", value); write(case_root / "output.json", official)
            for run, output in ((1, official), (2, second)):
                write(evidence / f"run_{run}/{split}_{case_id}.raw.json", output)
                write(evidence / f"run_{run}/{split}_{case_id}.normalized.json", output)
            write(evidence / f"independent/{split}_{case_id}.json", audit)
            records.append({"split": split, "case_id": case_id, "input_sha256": sha(case_root / "input.json"),
                "output_sha256": sha(case_root / "output.json"), "raw_official_sha256": sha(evidence / f"run_1/{split}_{case_id}.raw.json"),
                "normalized_output_sha256": sha(evidence / f"run_1/{split}_{case_id}.normalized.json"), "checkout_commit": COMMIT})
            official_outputs.append(official); independent_outputs.append(audit)
    task.joinpath("public").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PAPER, task / "public/paper.pdf")
    (task / "public/task.md").write_text("solution.py\n")
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
        "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID}, "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}},
        "required": ["schema_version", "task_id", "entrypoint"]}
    write(task / "public/interface.schema.json", schema)
    tolerances = {"comparison": "fieldwise", "field_rules": {
        "sample_indices": {"atol": 0.0, "rtol": 0.0}, "dictionary_indices": {"atol": 0.0, "rtol": 0.0},
        **{name: {"atol": max(2e-12, 20 * values[0]), "rtol": max(2e-11, 20 * values[1])} for name, values in maxima.items()}}}
    write(task / "hidden/tolerances.json", tolerances)
    adapter = ROOT / "curation_tools/reim_core_adapter.py"
    environment_lock = ROOT / "curation_tools/environments/0021-octave-environment.yml"
    bundle_hash = canonical(official_outputs)
    provenance = {"schema_version": 4, "task_id": TASK_ID, "lifecycle": "revise", "gold_source": "unverified_candidate",
        "repository": "https://github.com/yuwenli925/REIM", "commit": COMMIT,
        "paper_version": "arXiv:2406.19339v3", "paper_sha256": sha(PAPER), "cases": records,
        "environment_lock_sha256": sha(environment_lock), "dependency_artifact_sha256": None,
        "normalization_discrepancy": "Paper (2.1) uses (eta+b)/(x+b); repository experiments use 1/(x+b). The numerical dictionary input makes the convention explicit and the core recurrence identical.",
        "official_source_sha256": {"REIM.m_original": "f27dea36e57994569963d35e50b3cdc6fff4fdd872ee68018949cbd0ef97e033", "REIM.m_octave_compat_cached": sha(SOURCE)},
        "input_injection_patch_sha256": sha(ROOT / "curation_tools/patches/0021-reim-core-input.patch"),
        "official_adapter_patch_scope": "Only replace hard-coded xset/bset evaluation and fixed bset(1) with dictionary and initial_dictionary_index inputs; greedy loop, solves, infinity norms, and first-occurrence argmax are retained.",
        "official_reproduction": {"adapter_sha256": sha(adapter), "environment_lock_sha256": sha(environment_lock), "dependency_artifact_sha256": None, "clean_checkout_bundle_sha256": [bundle_hash, bundle_hash], "raw_and_normalized_outputs": "curation_reports/official_runs/0021_core"},
        "independent_audit": {"status": "passed", "implementation": "curation_tools/reim_core_scientific.py; written from Algorithm 2.1 without official helpers", "maximum_discrepancy_by_field": maxima, "derived_tolerances": tolerances},
        "environment": {"python": platform.python_version(), "numpy": np.__version__}}
    write(task / "hidden/provenance.json", provenance)
    print(f"built {TASK_ID}: 3 public + 8 hidden; candidate lifecycle REVISE")


if __name__ == "__main__":
    main()
