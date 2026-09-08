#!/usr/bin/env python3
"""Build the unpromoted explicit-panel 0020_core candidate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
from pathlib import Path

import numpy as np

from spsur_core_adapter import solve as official_solve
from spsur_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0020_core"
LEGACY = ROOT / "scibench_replication_0020"
PAPER_SHA256 = "380ffdb8a8c1e48cf204fb1742aa7f071d8c2898734b1dbe16b9b543570a02f2"
SPSUR_VERSION = "1.0.1.3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def ring_weights(n: int, reach: int = 1) -> np.ndarray:
    adjacency = np.zeros((n, n))
    for i in range(n):
        for distance in range(1, reach + 1):
            adjacency[i, (i - distance) % n] = 1
            adjacency[i, (i + distance) % n] = 1
    return adjacency / adjacency.sum(axis=1, keepdims=True)


def irregular_weights(n: int, seed: int, extra_probability: float = 0.12) -> np.ndarray:
    rng = np.random.default_rng(seed)
    adjacency = np.zeros((n, n))
    order = rng.permutation(n)
    for a, b in zip(order[:-1], order[1:]):
        adjacency[a, b] = adjacency[b, a] = 1
    for i in range(n):
        for j in range(i + 1, n):
            if not adjacency[i, j] and rng.random() < extra_probability:
                adjacency[i, j] = adjacency[j, i] = 1
    return adjacency / adjacency.sum(axis=1, keepdims=True)


def simulated_case(n: int, g: int, p: int, seed: int, rho_values: tuple[float, ...],
                   shared: tuple[int, ...] = (), topology: str = "irregular",
                   correlation: float = 0.45, smooth: float = 0.0) -> dict:
    rng = np.random.default_rng(seed)
    w = ring_weights(n, 2 if topology == "wide_ring" else 1) if "ring" in topology else irregular_weights(n, seed + 700, 0.07 if topology == "sparse" else 0.16)
    raw = rng.normal(size=(g, n, p - 1))
    if smooth:
        raw = (1 - smooth) * raw + smooth * np.einsum("ij,gjp->gip", w, raw)
    coordinate = np.linspace(-1, 1, n)
    raw[:, :, 0] += coordinate[None, :] + np.arange(g)[:, None] * 0.08
    x = np.concatenate((np.ones((g, n, 1)), raw), axis=2)
    beta = rng.normal(0, 0.55, size=(g, p)); beta[:, 0] = rng.normal(0.4, 0.15, g)
    for j in shared:
        beta[:, j] = beta[0, j]
    covariance = (1 - correlation) * np.eye(g) + correlation * np.fromfunction(lambda i, j: 0.72 ** np.abs(i - j), (g, g))
    errors = rng.normal(size=(n, g)) @ np.linalg.cholesky(covariance).T * 0.22
    y = np.empty((g, n))
    for equation in range(g):
        systematic = x[equation] @ beta[equation] + errors[:, equation]
        y[equation] = np.linalg.solve(np.eye(n) - rho_values[equation] * w, systematic)
    return {"y": y.tolist(), "x": x.tolist(), "w": w.tolist(), "shared_beta_columns": list(shared)}


def paper_case() -> dict:
    panel_path = ROOT / "curation_tools/fixtures/covid19env_panel.csv"
    weights_path = ROOT / "curation_tools/fixtures/covid19env_wmat.csv"
    with panel_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    dates = sorted({row["Date"] for row in rows})[:4]
    province_order = [int(row["ID_INE"]) for row in rows if row["Date"] == dates[0]]
    indexed = {(int(row["ID_INE"]), row["Date"]): row for row in rows}
    y, x = [], []
    for date in dates:
        selected = [indexed[province, date] for province in province_order]
        y.append([math.log(float(row["Incidence"])) for row in selected])
        x.append([[1.0, math.log(float(row["GDPpc"])), math.log(float(row["Older"])),
                   math.log(float(row["Density"])), float(row["Transit"]),
                   math.log(float(row["Humidity_lag8"])), math.log(float(row["Mean_Temp_lag8"])),
                   math.log(float(row["Sunshine_Hours_lag8"]) + 0.1)] for row in selected])
    with weights_path.open(newline="") as handle:
        matrix_rows = list(csv.reader(handle))
    w = [[float(value) for value in row[1:]] for row in matrix_rows[1:]]
    return {"y": y, "x": x, "w": w, "shared_beta_columns": [1, 2]}


def cases() -> tuple[list[dict], list[dict]]:
    public = [
        paper_case(),
        simulated_case(18, 3, 4, 2002, (0.62, 0.48, 0.71), topology="ring", correlation=0.58),
        simulated_case(22, 4, 5, 2003, (0.31, -0.24, 0.53, 0.08), (2,), correlation=0.18),
    ]
    hidden = [
        simulated_case(16, 2, 4, 2011, (0.82, 0.76), topology="wide_ring", correlation=0.72),
        simulated_case(20, 3, 4, 2012, (-0.61, -0.34, 0.17), (1,), topology="sparse", correlation=0.05),
        simulated_case(25, 5, 5, 2013, (0.67, 0.41, -0.29, 0.74, 0.12), (1, 3), correlation=0.64),
        simulated_case(14, 3, 4, 2014, (0.03, 0.44, -0.48), topology="sparse", correlation=0.0),
        simulated_case(28, 4, 5, 2015, (0.015, -0.02, 0.04, 0.0), correlation=0.22),
        simulated_case(18, 3, 5, 2016, (0.57, 0.68, 0.38), (1, 2), topology="wide_ring", correlation=0.51),
        simulated_case(24, 4, 4, 2017, (-0.52, 0.63, -0.18, 0.79), correlation=0.81),
        simulated_case(26, 5, 5, 2018, (0.73, -0.55, 0.36, 0.59, -0.21), (2,), topology="sparse", correlation=0.37, smooth=0.88),
    ]
    return public, hidden


def discrepancy(left: dict, right: dict) -> dict[str, tuple[float, float]]:
    result = {}
    for field in left:
        a, b = np.asarray(left[field], float), np.asarray(right[field], float)
        delta = np.abs(a - b)
        result[field] = (float(delta.max(initial=0)), float((delta / np.maximum(np.abs(a), 1e-300)).max(initial=0)))
    return result


def main() -> None:
    paper = LEGACY / "public/paper.pdf"
    if sha(paper) != PAPER_SHA256:
        raise RuntimeError("target paper hash mismatch")
    task = ROOT / TASK_ID
    if task.exists() and not (task / "public/cases").is_dir():
        raise RuntimeError(f"refusing to overwrite unexpected path {task}")
    public, hidden = cases(); evidence = ROOT / "curation_reports/official_runs/0020_core"
    records = []; maxima = {field: [0.0, 0.0] for field in (
        "beta", "beta_standard_errors", "rho", "rho_standard_errors", "r2_by_equation",
        "pooled_r2", "direct_effects", "indirect_effects", "total_effects")}
    bundle_hashes = []
    run_outputs = {1: [], 2: []}
    for split, collection in (("public", public), ("hidden", hidden)):
        for number, value in enumerate(collection, 1):
            case_id = f"case_{number:02d}"
            first = official_solve(value); second = official_solve(value); audit = independent_solve(value)
            for field, (absolute, relative) in discrepancy(first, audit).items():
                maxima[field][0] = max(maxima[field][0], absolute); maxima[field][1] = max(maxima[field][1], relative)
            case_root = task / split / "cases" / case_id
            write(case_root / "input.json", value); write(case_root / "output.json", first)
            for run, output in ((1, first), (2, second)):
                write(evidence / f"run_{run}/{split}_{case_id}.raw.json", output)
                write(evidence / f"run_{run}/{split}_{case_id}.normalized.json", output)
                run_outputs[run].append(output)
            write(evidence / f"independent/{split}_{case_id}.json", audit)
            records.append({"split": split, "case_id": case_id, "input_sha256": sha(case_root / "input.json"),
                            "output_sha256": sha(case_root / "output.json"), "spsur_version": SPSUR_VERSION})
    for run in (1, 2):
        bundle_hashes.append(hashlib.sha256(json.dumps(run_outputs[run], sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    if bundle_hashes[0] != bundle_hashes[1]:
        raise RuntimeError("official clean runs differ")
    (task / "public").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paper, task / "public/paper.pdf")
    (task / "public/task.md").write_text("solution.py\n")
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
              "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID}, "entrypoint": {"oneOf": [
                  {"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}},
              "required": ["schema_version", "task_id", "entrypoint"]}
    write(task / "public/interface.schema.json", schema)
    rules = {field: {"atol": max(5e-10, values[0] * 20), "rtol": max(5e-10, values[1] * 20)} for field, values in maxima.items()}
    tolerances = {"comparison": "fieldwise", "field_rules": rules}; write(task / "hidden/tolerances.json", tolerances)
    provenance = {"schema_version": 4, "task_id": TASK_ID, "lifecycle": "revise", "gold_source": "unpromoted_pinned_official",
                  "repository": "https://github.com/paezha/covid19-environmental-correlates", "commit": "6e84cf31ef7012daa08168bcdc8315f8ca3ec7c6",
                  "paper_version": "Geographical Analysis 53(3):397-421", "paper_sha256": PAPER_SHA256, "cases": records,
                  "official_reproduction": {"implementation": "spsur 1.0.1.3 spsur3sls direct X/Y/listw/G/N/Tm/R/b interfaces",
                    "adapter": "curation_tools/spsur_core_adapter.py", "adapter_sha256": sha(ROOT/"curation_tools/spsur_core_adapter.py"),
                    "driver_sha256": sha(ROOT/"curation_tools/spsur_core_driver.R"), "environment_lock_sha256": sha(ROOT/"curation_tools/environments/0020-r-environment.yml"),
                    "clean_checkout_bundle_sha256": bundle_hashes,
                    "raw_and_normalized_outputs": "curation_reports/official_runs/0020_core"},
                  "independent_audit": {"status": "passed", "implementation": "curation_tools/spsur_core_scientific.py",
                    "maximum_discrepancy_by_field": maxima, "derived_tolerances": tolerances},
                  "literature": json.loads((ROOT/"curation_reports/0020_core_hazards.json").read_text())["references"],
                  "environment": {"python": platform.python_version(), "numpy": np.__version__, "spsur": SPSUR_VERSION}}
    write(task / "hidden/provenance.json", provenance)
    print(json.dumps({"task": TASK_ID, "public": 3, "hidden": 8, "maxima": maxima, "bundle_hash": bundle_hashes[0]}, indent=2))


if __name__ == "__main__":
    main()
