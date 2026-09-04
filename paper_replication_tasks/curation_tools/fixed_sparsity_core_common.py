"""Validation shared by the 0015 core-algorithm oracle and audit."""

from __future__ import annotations

from typing import Any

import numpy as np


def _matrix(value: Any, name: str) -> np.ndarray:
    if not isinstance(value, list) or not value or not all(isinstance(row, list) and row for row in value):
        raise ValueError(f"{name} must be a nonempty matrix")
    width = len(value[0])
    if any(len(row) != width for row in value):
        raise ValueError(f"{name} must be rectangular")
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if result.ndim != 2 or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain finite numbers")
    return result


def validate_case(value: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(value, dict) or set(value) != {"A", "S", "G"}:
        raise ValueError("input must contain exactly A, S, and G")
    matrix = _matrix(value["A"], "A")
    mask = _matrix(value["S"], "S")
    sketch = _matrix(value["G"], "G")
    if mask.shape != matrix.shape:
        raise ValueError("S shape must equal A shape")
    if not np.all((mask == 0) | (mask == 1)):
        raise ValueError("S must be binary")
    if sketch.shape[0] != matrix.shape[1]:
        raise ValueError("G row count must equal A column count")
    if sketch.shape[1] < int(mask.sum(axis=1).max(initial=0)):
        raise ValueError("G has too few columns")
    return matrix, mask.astype(bool), sketch


def validate_output(value: Any, shape: tuple[int, int]) -> np.ndarray:
    if not isinstance(value, dict) or set(value) != {"A_tilde"}:
        raise ValueError("output must contain exactly A_tilde")
    result = _matrix(value["A_tilde"], "A_tilde")
    if result.shape != shape:
        raise ValueError("A_tilde has wrong shape")
    return result
