"""Independent sectional-curvature implementation for task 0019.

Clean-room reimplementation of the four formulas in Zimmermann & Stoye,
"High curvature means low rank: on the sectional curvature of Grassmann and
Stiefel manifolds and the underlying matrix trace inequalities" (SIMAX),
Section 3. Used only to audit the pinned official Octave/MATLAB gold, never
to generate it.
"""

from __future__ import annotations

import numpy as np

try:
    from .stiefelcurv_common import validate_case
except ImportError:  # direct curator-script execution
    from stiefelcurv_common import validate_case


def _stiefel_canonical(A1, B1, A2, B2) -> float:
    normX = np.sqrt(0.5 * np.trace(A1.T @ A1) + np.trace(B1.T @ B1))
    A1, B1 = A1 / normX, B1 / normX
    d = 0.5 * np.trace(A1.T @ A2) + np.trace(B1.T @ B2)
    A2, B2 = A2 - d * A1, B2 - d * B1
    normY = np.sqrt(0.5 * np.trace(A2.T @ A2) + np.trace(B2.T @ B2))
    A2, B2 = A2 / normY, B2 / normY

    lie_a1a2 = A1 @ A2 - A2 @ A1
    lie_b1tb2 = B1.T @ B2 - B2.T @ B1
    lie_b2b1t = B2 @ B1.T - B1 @ B2.T

    return float(
        (1 / 8) * np.linalg.norm(lie_a1a2 - lie_b1tb2, "fro") ** 2
        + (1 / 4) * np.linalg.norm(B1 @ A2 - B2 @ A1, "fro") ** 2
        + (1 / 2) * np.linalg.norm(lie_b2b1t, "fro") ** 2
    )


def _stiefel_euclidean(A1, B1, A2, B2) -> float:
    normX = np.sqrt(np.trace(A1.T @ A1) + np.trace(B1.T @ B1))
    A1, B1 = A1 / normX, B1 / normX
    d = np.trace(A1.T @ A2) + np.trace(B1.T @ B2)
    A2, B2 = A2 - d * A1, B2 - d * B1
    normY = np.sqrt(np.trace(A2.T @ A2) + np.trace(B2.T @ B2))
    A2, B2 = A2 / normY, B2 / normY

    lie_a1a2 = A1 @ A2 - A2 @ A1
    lie_b1tb2 = B1.T @ B2 - B2.T @ B1

    return float(
        (1 / 4) * np.linalg.norm(lie_a1a2 + lie_b1tb2, "fro") ** 2
        + np.linalg.norm(B1 @ A2 - B2 @ A1, "fro") ** 2
        + np.trace(B1 @ (B2.T @ B2) @ B1.T) - np.trace((B1.T @ B2) @ (B2.T @ B1))
    )


def _grassmann(B1, B2) -> float:
    B1 = B1 / np.linalg.norm(B1, "fro")
    B2 = B2 - np.trace(B2.T @ B1) * B1
    B2 = B2 / np.linalg.norm(B2, "fro")

    b12 = B1.T @ B2
    m1221 = b12 @ b12.T
    m1122 = (B1.T @ B1) @ (B2.T @ B2)
    m1212 = b12 @ b12

    return float(np.trace(m1221) + np.trace(m1122) - 2 * np.trace(m1212))


def _so_n(X, Y) -> float:
    X = X / np.linalg.norm(X, "fro")
    Y = Y - np.trace(X.T @ Y) * X
    Y = Y / np.linalg.norm(Y, "fro")

    lie_xy = X @ Y - Y @ X
    return float(0.5 * np.trace(lie_xy.T @ lie_xy))


def solve(case: dict) -> dict:
    clean = validate_case(case)
    metric = clean["metric"]
    if metric == "stiefel_canonical":
        seccurv = _stiefel_canonical(
            np.asarray(clean["A1"], dtype=float), np.asarray(clean["B1"], dtype=float),
            np.asarray(clean["A2"], dtype=float), np.asarray(clean["B2"], dtype=float),
        )
    elif metric == "stiefel_euclidean":
        seccurv = _stiefel_euclidean(
            np.asarray(clean["A1"], dtype=float), np.asarray(clean["B1"], dtype=float),
            np.asarray(clean["A2"], dtype=float), np.asarray(clean["B2"], dtype=float),
        )
    elif metric == "grassmann":
        seccurv = _grassmann(np.asarray(clean["B1"], dtype=float), np.asarray(clean["B2"], dtype=float))
    else:
        seccurv = _so_n(np.asarray(clean["X"], dtype=float), np.asarray(clean["Y"], dtype=float))

    if not np.isfinite(seccurv):
        raise ValueError("scientific calculation produced a non-finite value")
    return {"metric": metric, "seccurv": seccurv}
