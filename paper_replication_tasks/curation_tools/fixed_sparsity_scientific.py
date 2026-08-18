"""Independent Gaussian-sketching implementation for task 0015."""

from __future__ import annotations

import numpy as np

try:
    from .fixed_sparsity_common import hard_coloring, matrix_for, patterns, validate_case
except ImportError:  # direct curator-script execution
    from fixed_sparsity_common import hard_coloring, matrix_for, patterns, validate_case


def _recover(matrix: np.ndarray, mask: np.ndarray, m: int, rng: np.random.RandomState) -> np.ndarray:
    sketch = rng.normal(size=(matrix.shape[1], m))
    observations = matrix @ sketch
    recovered = np.zeros_like(matrix)
    for row in range(matrix.shape[0]):
        columns = np.flatnonzero(mask[row])
        design = sketch[columns]
        # Independent normal-equations implementation of the row least-squares problem.
        recovered[row, columns] = np.linalg.solve(design @ design.T, design @ observations[row])
    return recovered


def solve(case):
    case = validate_case(case)
    if case["mode"] == "hard_coloring":
        return {"hard_coloring": [{"label": row["label"], **hard_coloring(row["k"])} for row in case["experiments"]]}
    rng = np.random.RandomState(case["seed"])
    curves = []
    for spec in case["experiments"]:
        matrix = matrix_for(spec, rng)
        for parameter, mask in patterns(spec, rng, matrix):
            s = int(mask.sum(axis=1).max())
            counts = [m for m in spec["matvec_counts"] if m >= s + 2]
            if not counts:
                raise ValueError("no admissible matvec count")
            off = float(np.linalg.norm(matrix - matrix * mask))
            rows = []
            for m in counts:
                print(f"independent {spec['label']} parameter={parameter} m={m}", flush=True)
                rows.append([np.linalg.norm(_recover(matrix, mask, m, rng) - matrix * mask) for _ in range(spec["trials"])])
            errors = np.asarray(rows)
            rmse = np.sqrt(np.mean(errors**2, axis=1)); q10 = np.quantile(errors, .1, axis=1); q90 = np.quantile(errors, .9, axis=1)
            bound = np.sqrt(s / (np.asarray(counts, dtype=float) - s - 1)) * off
            curves.append({"label": spec["label"], "pattern_parameter": parameter, "row_sparsity": s,
                "matvec_counts": counts, "off_pattern_error": off, "recovery_rmse": rmse.tolist(),
                "recovery_q10": q10.tolist(), "recovery_q90": q90.tolist(),
                "displayed_approximation_error": (off + rmse).tolist(),
                "displayed_approximation_q10": (off + q10).tolist(), "displayed_approximation_q90": (off + q90).tolist(),
                "theorem1_recovery_bound": bound.tolist(), "theorem1_displayed_bound": (off + bound).tolist()})
    return {"curves": curves}
