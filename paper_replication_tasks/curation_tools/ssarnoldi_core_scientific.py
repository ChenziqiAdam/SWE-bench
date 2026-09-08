"""Clean-room NumPy implementation derived from the paper's basic method."""

from __future__ import annotations

import numpy as np

from ssarnoldi_core_common import breakdown_threshold, select_largest, validate_case


def solve(value: dict) -> dict:
    A, start, S, m, budget = validate_case(value)
    n, sketch_dim = A.shape[0], S.shape[0]
    V = np.zeros((n, m + 1)); SV = np.zeros((sketch_dim, m + 1))
    H = np.zeros((m + 1, m)); SAV = np.zeros((sketch_dim, m))
    sv = S @ start; beta = np.linalg.norm(sv)
    V[:, 0], SV[:, 0] = start / beta, sv / beta
    for column in range(m):
        w = A @ V[:, column]
        sw = S @ w
        SAV[:, column] = sw
        coefficients = np.linalg.pinv(SV[:, : column + 1]) @ sw
        selected = select_largest(coefficients, min(column + 1, budget))
        h = coefficients[selected]
        H[selected, column] = h
        w = w - V[:, selected] @ h
        sw = sw - SV[:, selected] @ h
        beta = float(np.linalg.norm(sw))
        if not np.isfinite(beta) or beta <= breakdown_threshold(SAV[:, column]):
            raise ValueError(f"numerical breakdown at iteration {column + 1}")
        H[column + 1, column] = beta
        V[:, column + 1], SV[:, column + 1] = w / beta, sw / beta
    return {"basis": V.tolist(), "hessenberg": H.tolist(),
            "sketched_basis": SV.tolist(), "sketched_products": SAV.tolist()}
