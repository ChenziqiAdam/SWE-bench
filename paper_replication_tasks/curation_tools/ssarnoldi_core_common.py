"""Validation and numerical contract for scibench_replication_0022_core."""

from __future__ import annotations

from typing import Any

import numpy as np

INPUT_FIELDS = {"matrix", "start_vector", "sketch_matrix", "iterations", "selection_budget"}
OUTPUT_FIELDS = {"basis", "hessenberg", "sketched_basis", "sketched_products"}


def _array(value: Any, ndim: int, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a dense real array") from exc
    if result.ndim != ndim or not np.isfinite(result).all():
        raise ValueError(f"{name} has invalid shape or nonfinite values")
    return result


def validate_case(value: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    if not isinstance(value, dict) or set(value) != INPUT_FIELDS:
        raise ValueError("input fields differ from the contract")
    matrix = _array(value["matrix"], 2, "matrix")
    start = _array(value["start_vector"], 1, "start_vector")
    sketch = _array(value["sketch_matrix"], 2, "sketch_matrix")
    iterations, budget = value["iterations"], value["selection_budget"]
    if matrix.shape[0] < 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("matrix must be square with dimension at least two")
    n = matrix.shape[0]
    if start.shape != (n,) or sketch.shape[1] != n or sketch.shape[0] < 1:
        raise ValueError("start_vector or sketch_matrix shape mismatch")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations < n:
        raise ValueError("iterations must be an integer in [1, N-1]")
    if sketch.shape[0] < iterations + 1:
        raise ValueError("sketch dimension must be at least iterations+1")
    if not isinstance(budget, int) or isinstance(budget, bool) or not 1 <= budget <= iterations:
        raise ValueError("selection_budget must be an integer in [1, iterations]")
    if np.linalg.norm(start) == 0 or np.linalg.norm(sketch @ start) == 0:
        raise ValueError("starting vector has zero Euclidean or sketched norm")
    return matrix, start, sketch, iterations, budget


def output_shapes(case: Any) -> dict[str, tuple[int, int]]:
    matrix, _, sketch, iterations, _ = validate_case(case)
    return {
        "basis": (matrix.shape[0], iterations + 1),
        "hessenberg": (iterations + 1, iterations),
        "sketched_basis": (sketch.shape[0], iterations + 1),
        "sketched_products": (sketch.shape[0], iterations),
    }


def validate_output(value: Any, case: Any) -> dict[str, list[list[float]]]:
    if not isinstance(value, dict) or set(value) != OUTPUT_FIELDS:
        raise ValueError("output fields differ from the contract")
    clean: dict[str, list[list[float]]] = {}
    for name, shape in output_shapes(case).items():
        array = _array(value[name], 2, name)
        if array.shape != shape:
            raise ValueError(f"{name} must have shape {shape}")
        clean[name] = array.tolist()
    return clean


def select_largest(coefficients: np.ndarray, count: int) -> np.ndarray:
    """Descending magnitude, with lower column index winning exact ties."""
    indices = np.arange(coefficients.size)
    return np.lexsort((indices, -np.abs(coefficients)))[:count]


def breakdown_threshold(sw: np.ndarray) -> float:
    return 64.0 * np.finfo(float).eps * max(1.0, float(np.linalg.norm(sw)))
