"""Validation and deterministic I/O contract for the 0021 rEIM core task."""

from __future__ import annotations

from typing import Any

import numpy as np


FIELDS = {"order", "dictionary", "targets", "query_dictionary", "initial_dictionary_index"}
OUTPUT_FIELDS = {"sample_indices", "dictionary_indices", "interpolation_matrix", "coefficients", "predictions"}


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
        raise ValueError(f"{name} must contain only finite numbers")
    return result


def validate_case(value: Any) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, int]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("input fields differ from the contract")
    dictionary = _matrix(value["dictionary"], "dictionary")
    targets = _matrix(value["targets"], "targets")
    query = _matrix(value["query_dictionary"], "query_dictionary")
    rows, columns = dictionary.shape
    if targets.shape[0] != rows or query.shape[1] != columns:
        raise ValueError("matrix dimensions are inconsistent")
    order = value["order"]
    initial = value["initial_dictionary_index"]
    if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= min(rows, columns, 40):
        raise ValueError("order is out of range")
    if isinstance(initial, bool) or not isinstance(initial, int) or not 0 <= initial < columns:
        raise ValueError("initial_dictionary_index is out of range")
    norms = np.max(np.abs(dictionary), axis=0)
    scale = max(1.0, float(norms.max()))
    if abs(float(norms[initial]) - float(norms.max())) > 8 * np.finfo(float).eps * scale:
        raise ValueError("initial_dictionary_index is not a legal maximum-norm column")
    if np.linalg.matrix_rank(dictionary, tol=np.finfo(float).eps * max(rows, columns) * np.linalg.norm(dictionary, 2)) < order:
        raise ValueError("dictionary cannot support the requested order")
    return order, dictionary, targets, query, initial


def validate_output(value: Any, case: Any) -> None:
    order, dictionary, targets, query, _ = validate_case(case)
    if not isinstance(value, dict) or set(value) != OUTPUT_FIELDS:
        raise ValueError("output fields differ from the contract")
    sample = value["sample_indices"]
    columns = value["dictionary_indices"]
    if (not isinstance(sample, list) or not isinstance(columns, list) or len(sample) != order or len(columns) != order
            or any(isinstance(x, bool) or not isinstance(x, int) for x in sample + columns)):
        raise ValueError("indices have invalid type or length")
    if len(set(sample)) != order or len(set(columns)) != order:
        raise ValueError("indices must be distinct")
    if any(x < 0 or x >= dictionary.shape[0] for x in sample) or any(x < 0 or x >= dictionary.shape[1] for x in columns):
        raise ValueError("index out of range")
    expected_shapes = {
        "interpolation_matrix": (order, order),
        "coefficients": (order, targets.shape[1]),
        "predictions": (query.shape[0], targets.shape[1]),
    }
    for name, shape in expected_shapes.items():
        if _matrix(value[name], name).shape != shape:
            raise ValueError(f"{name} has wrong shape")

