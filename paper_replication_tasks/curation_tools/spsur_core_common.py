"""Validation and matrix construction for the 0020 core task."""

from __future__ import annotations

from typing import Any

import numpy as np

INPUT_FIELDS = {"y", "x", "w", "shared_beta_columns"}
OUTPUT_FIELDS = {
    "beta", "beta_standard_errors", "rho", "rho_standard_errors",
    "r2_by_equation", "pooled_r2", "direct_effects", "indirect_effects",
    "total_effects",
}
MAX_G, MAX_N, MAX_P = 12, 200, 20


def _array(value: Any, name: str, ndim: int) -> np.ndarray:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a nonempty JSON array")
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be rectangular and numeric") from exc
    if result.ndim != ndim or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite {ndim}-dimensional array")
    return result


def parameter_columns(g_count: int, p_count: int, shared: tuple[int, ...]) -> tuple[list[tuple[int | None, int]], dict[tuple[int, int], int]]:
    """Return restricted coefficient columns and expanded (g,p)->column map."""
    shared_set = set(shared)
    columns: list[tuple[int | None, int]] = []
    mapping: dict[tuple[int, int], int] = {}
    for p in range(p_count):
        if p in shared_set:
            index = len(columns)
            columns.append((None, p))
            for g in range(g_count):
                mapping[g, p] = index
        else:
            for g in range(g_count):
                mapping[g, p] = len(columns)
                columns.append((g, p))
    return columns, mapping


def restricted_design(x: np.ndarray, shared: tuple[int, ...]) -> tuple[np.ndarray, dict[tuple[int, int], int]]:
    g_count, n_count, p_count = x.shape
    columns, mapping = parameter_columns(g_count, p_count, shared)
    design = np.zeros((g_count * n_count, len(columns)), dtype=np.float64)
    for index, (equation, regressor) in enumerate(columns):
        if equation is None:
            for g in range(g_count):
                design[g * n_count:(g + 1) * n_count, index] = x[g, :, regressor]
        else:
            design[equation * n_count:(equation + 1) * n_count, index] = x[equation, :, regressor]
    return design, mapping


def instrument_design(x: np.ndarray, w: np.ndarray, shared: tuple[int, ...]) -> np.ndarray:
    base, _ = restricted_design(x, shared)
    _, mapping = parameter_columns(x.shape[0], x.shape[2], shared)
    intercept_columns = sorted({mapping[g, 0] for g in range(x.shape[0])})
    no_intercept = np.delete(base, intercept_columns, axis=1)
    lag_operator = np.kron(np.eye(x.shape[0]), w)
    wx = lag_operator @ no_intercept
    return np.column_stack((base, wx, lag_operator @ wx))


def validate_case(value: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, ...]]:
    if not isinstance(value, dict) or set(value) != INPUT_FIELDS:
        raise ValueError("input fields differ from the contract")
    y = _array(value["y"], "y", 2)
    x = _array(value["x"], "x", 3)
    w = _array(value["w"], "w", 2)
    g_count, n_count = y.shape
    if not 2 <= g_count < n_count or g_count > MAX_G or n_count > MAX_N:
        raise ValueError("dimensions must satisfy 2 <= G < N within size limits")
    if x.shape[:2] != (g_count, n_count) or not 2 <= x.shape[2] <= MAX_P:
        raise ValueError("x must have shape G x N x P with 2 <= P <= 20")
    if w.shape != (n_count, n_count):
        raise ValueError("w must have shape N x N")
    tolerance = 64 * np.finfo(float).eps * max(1, n_count)
    if np.min(w) < -tolerance or np.max(np.abs(np.diag(w))) > tolerance:
        raise ValueError("w must be nonnegative with zero diagonal")
    if not np.allclose(w.sum(axis=1), 1.0, atol=tolerance, rtol=0.0):
        raise ValueError("every row of w must sum to one")
    if not np.allclose(x[:, :, 0], 1.0, atol=tolerance, rtol=0.0):
        raise ValueError("x column zero must be an all-ones intercept")
    raw_shared = value["shared_beta_columns"]
    if not isinstance(raw_shared, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in raw_shared):
        raise ValueError("shared_beta_columns must be a list of integers")
    shared = tuple(raw_shared)
    if tuple(sorted(set(shared))) != shared or any(v <= 0 or v >= x.shape[2] for v in shared):
        raise ValueError("shared_beta_columns must be sorted, unique, valid, and exclude the intercept")
    for g in range(g_count):
        if np.linalg.matrix_rank(x[g]) != x.shape[2]:
            raise ValueError("every equation design must have full column rank")
    base, _ = restricted_design(x, shared)
    instruments = instrument_design(x, w, shared)
    if np.linalg.matrix_rank(base) != base.shape[1] or np.linalg.matrix_rank(instruments) != instruments.shape[1]:
        raise ValueError("restricted regressor and instrument designs must have full column rank")
    return y, x, w, shared


def validate_output(value: Any, case: Any) -> None:
    y, x, _, _ = validate_case(case)
    if not isinstance(value, dict) or set(value) != OUTPUT_FIELDS:
        raise ValueError("output fields differ from the contract")
    g_count, _, p_count = x.shape
    shapes = {
        "beta": (g_count, p_count),
        "beta_standard_errors": (g_count, p_count),
        "rho": (g_count,),
        "rho_standard_errors": (g_count,),
        "r2_by_equation": (g_count,),
        "direct_effects": (g_count, p_count - 1),
        "indirect_effects": (g_count, p_count - 1),
        "total_effects": (g_count, p_count - 1),
    }
    for name, shape in shapes.items():
        if _array(value[name], name, len(shape)).shape != shape:
            raise ValueError(f"{name} has wrong shape")
    pooled = value["pooled_r2"]
    if isinstance(pooled, bool) or not isinstance(pooled, (int, float)) or not np.isfinite(float(pooled)):
        raise ValueError("pooled_r2 must be finite")

