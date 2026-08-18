"""Shared case validation for the StiefelCurvatureSIMAX curator implementations.

A case specifies one sectional-curvature evaluation. `metric` selects which of
the paper's four formulas to apply, and `p`/`np_` (n minus p) fix the block
sizes of the skew-symmetric tangent-vector coordinates A1,B1,A2,B2 (metric in
{"stiefel_canonical","stiefel_euclidean"}), B1,B2 (metric "grassmann"), or the
full skew matrices X,Y (metric "so_n"). Matrices are supplied as nested lists
of floats, row-major, matching the shapes each official function expects.
"""

from __future__ import annotations

from typing import Any


def _is_matrix(value: Any, rows: int, cols: int) -> bool:
    if not isinstance(value, list) or len(value) != rows:
        return False
    for row in value:
        if not isinstance(row, list) or len(row) != cols:
            return False
        for entry in row:
            if isinstance(entry, bool) or not isinstance(entry, (int, float)):
                return False
    return True


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict) or "metric" not in case:
        raise ValueError("case must be an object with a metric field")
    metric = case["metric"]
    if metric not in {"stiefel_canonical", "stiefel_euclidean", "grassmann", "so_n"}:
        raise ValueError("invalid metric")

    if metric in {"stiefel_canonical", "stiefel_euclidean"}:
        required = {"metric", "p", "np", "A1", "B1", "A2", "B2"}
        if set(case) != required:
            raise ValueError("stiefel case fields differ")
        p, np_ = case["p"], case["np"]
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (p, np_)) or not 1 <= p <= 40 or not 1 <= np_ <= 40:
            raise ValueError("invalid block dimensions")
        for name in ("A1", "A2"):
            if not _is_matrix(case[name], p, p):
                raise ValueError(f"{name} must be a {p}x{p} matrix")
        for name in ("B1", "B2"):
            if not _is_matrix(case[name], np_, p):
                raise ValueError(f"{name} must be a {np_}x{p} matrix")
        return {"metric": metric, "p": p, "np": np_,
                "A1": case["A1"], "B1": case["B1"], "A2": case["A2"], "B2": case["B2"]}

    if metric == "grassmann":
        required = {"metric", "np", "p", "B1", "B2"}
        if set(case) != required:
            raise ValueError("grassmann case fields differ")
        p, np_ = case["p"], case["np"]
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (p, np_)) or not 1 <= p <= 40 or not 1 <= np_ <= 40:
            raise ValueError("invalid block dimensions")
        for name in ("B1", "B2"):
            if not _is_matrix(case[name], np_, p):
                raise ValueError(f"{name} must be a {np_}x{p} matrix")
        return {"metric": metric, "p": p, "np": np_, "B1": case["B1"], "B2": case["B2"]}

    required = {"metric", "n", "X", "Y"}
    if set(case) != required:
        raise ValueError("so_n case fields differ")
    n = case["n"]
    if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= 40:
        raise ValueError("invalid dimension")
    for name in ("X", "Y"):
        if not _is_matrix(case[name], n, n):
            raise ValueError(f"{name} must be a {n}x{n} matrix")
    return {"metric": metric, "n": n, "X": case["X"], "Y": case["Y"]}
