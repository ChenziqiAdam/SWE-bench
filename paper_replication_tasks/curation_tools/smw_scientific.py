"""Independent Theorem 2/6 and Corollary 3/7 implementation for task 0014."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.linalg import inv, norm

try:
    from .smw_adapter import OUTPUT_KEYS, validate_case
except ImportError:  # direct curator-script execution
    from smw_adapter import OUTPUT_KEYS, validate_case


def solve(case: dict[str, Any]) -> dict[str, list[float]]:
    clean = validate_case(case)
    A, U, V = clean["A"], clean["U"], clean["V"]
    A_inv = inv(A)
    B = A + U @ V.T
    B_inv = inv(B)
    lamda = float(norm(U, 2) * norm(V, 2))
    alpha = float(norm(inv(np.eye(U.shape[1]) + V.T @ A_inv @ U), 2))
    beta = float(norm(np.eye(U.shape[1]) + V.T @ A_inv @ U, 2))
    rows = []
    for e1, e2, E1, E2 in clean["draws"]:
        A_tilde_inv = A_inv + E1
        Z_inv = inv(np.eye(U.shape[1]) + V.T @ A_tilde_inv @ U) + E2
        B_tilde_inv = A_tilde_inv - A_tilde_inv @ U @ Z_inv @ V.T @ A_tilde_inv
        forward_error = norm(B_inv - B_tilde_inv, 2)
        forward_simple = 2 * e2 * norm(A_inv, 2) + 12 * e1
        forward_full = e1 + e1 * lamda * (2 * norm(A_inv, 2) + e1) * alpha + lamda * (norm(A_inv, 2) + e1) ** 2 * (e2 + 2 * e1 * lamda * alpha**2)
        backward_error = norm(B - inv(B_tilde_inv), 2)
        backward_simple = 2 * e1 * norm(A, 2) ** 2 + 8 * e2
        backward_full = 2 * e1 * norm(A, 2) ** 2 + 4 * lamda * e2 * (beta + lamda * e1) ** 2
        rows.append((e1, e2, forward_error, forward_simple, forward_full, backward_error, backward_simple, backward_full))
    width = clean.get("replicates", 1)
    result = {key: [] for key in OUTPUT_KEYS}
    for offset in range(0, len(rows), width):
        means = np.mean(np.asarray(rows[offset:offset + width], dtype=np.float64), axis=0)
        for key, value in zip(OUTPUT_KEYS, means):
            if not math.isfinite(float(value)):
                raise ValueError("non-finite independent result")
            result[key].append(float(value))
    return result
