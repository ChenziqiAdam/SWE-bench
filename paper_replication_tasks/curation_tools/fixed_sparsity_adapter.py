#!/usr/bin/env python3
"""Curator adapter executing the pinned notebook sparse_recovery kernel."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path

import numpy as np

from fixed_sparsity_common import hard_coloring, matrix_for, patterns, validate_case


COMMIT = "6da600d95dbcf8a2f6f8424432601e31a243ba5e"


def notebook_kernel(checkout: Path):
    notebook = json.loads((checkout / "sparse_recovery.ipynb").read_text(encoding="utf-8"))
    source = next("".join(cell["source"]) for cell in notebook["cells"] if cell.get("cell_type") == "code" and "def sparse_recovery" in "".join(cell["source"]))
    namespace = {"np": np}
    exec(compile(source, "sparse_recovery.ipynb", "exec"), namespace)
    return namespace["sparse_recovery"]


def _official_curve(job):
    checkout, spec, parameter, matrix, mask, state = job
    np.random.set_state(state)
    kernel = notebook_kernel(Path(checkout))
    sparsities = mask.sum(axis=1)
    s = int(sparsities.max())
    counts = [m for m in spec["matvec_counts"] if m >= s + 2]
    errors = np.empty((len(counts), spec["trials"]))
    for i, m in enumerate(counts):
        print(f"{spec['label']} parameter={parameter} m={m}", flush=True)
        for trial in range(spec["trials"]):
            recovered = kernel(matrix, mask, m)
            errors[i, trial] = np.linalg.norm(recovered - matrix * mask)
    off = float(np.linalg.norm(matrix - matrix * mask))
    rmse = np.sqrt(np.mean(errors**2, axis=1))
    q10 = np.quantile(errors, .1, axis=1)
    q90 = np.quantile(errors, .9, axis=1)
    bound = np.sqrt(s / (np.asarray(counts, dtype=float) - s - 1)) * off
    return {"label": spec["label"], "pattern_parameter": parameter, "row_sparsity": s,
        "matvec_counts": counts, "off_pattern_error": off, "recovery_rmse": rmse.tolist(),
        "recovery_q10": q10.tolist(), "recovery_q90": q90.tolist(),
        "displayed_approximation_error": (off + rmse).tolist(),
        "displayed_approximation_q10": (off + q10).tolist(), "displayed_approximation_q90": (off + q90).tolist(),
        "theorem1_recovery_bound": bound.tolist(), "theorem1_displayed_bound": (off + bound).tolist()}


def solve(case, checkout: Path):
    case = validate_case(case)
    if case["mode"] == "hard_coloring":
        return {"hard_coloring": [{"label": row["label"], **hard_coloring(row["k"])} for row in case["experiments"]]}
    np.random.seed(case["seed"])
    driver_rng = np.random.mtrand._rand
    jobs = []
    for spec in case["experiments"]:
        matrix = matrix_for(spec, driver_rng)
        for parameter, mask in patterns(spec, driver_rng, matrix):
            s = int(mask.sum(axis=1).max())
            counts = [m for m in spec["matvec_counts"] if m >= s + 2]
            if not counts:
                raise ValueError("no matvec count satisfies m >= s + 2")
            state = driver_rng.get_state()
            jobs.append((str(checkout), spec, parameter, matrix, mask, state))
            # Advance the driver exactly as the sequential notebook kernel would.
            for m in counts:
                for _ in range(spec["trials"]):
                    driver_rng.randn(matrix.shape[1], m)
    if len(jobs) == 1:
        curves = [_official_curve(jobs[0])]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            curves = list(pool.map(_official_curve, jobs))
    return {"curves": curves}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.task != "0015":
        parser.error("unsupported task")
    result = solve(json.loads(args.input.read_text()), args.checkout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
