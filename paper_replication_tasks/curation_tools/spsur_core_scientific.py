"""Independent NumPy SUR-SLM 3SLS implementation for task 0020_core.

This implementation uses only the public numerical contract and does not
import or call any spsur/repository helper.
"""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    from .spsur_core_common import instrument_design, restricted_design, validate_case
except ImportError:  # direct curator-script execution
    from spsur_core_common import instrument_design, restricted_design, validate_case


def _correlation_squared(left: np.ndarray, right: np.ndarray) -> float:
    a = left - np.mean(left)
    b = right - np.mean(right)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        raise ValueError("R-squared is undefined for a constant vector")
    return float((np.dot(a, b) / denominator) ** 2)


def solve(case: dict[str, Any]) -> dict[str, Any]:
    y_panel, x, w, shared = validate_case(case)
    g_count, n_count, p_count = x.shape
    y = y_panel.reshape(-1)
    beta_design, beta_map = restricted_design(x, shared)
    lag_operator = np.kron(np.eye(g_count), w)
    wy = (lag_operator @ y).reshape(g_count, n_count)
    endogenous = np.zeros((g_count * n_count, g_count), dtype=np.float64)
    for g in range(g_count):
        endogenous[g * n_count:(g + 1) * n_count, g] = wy[g]
    z = np.column_stack((endogenous, beta_design))
    h = instrument_design(x, w, shared)

    # Orthogonal projection avoids explicitly forming the GN x GN projector.
    first_stage, _, rank_h, _ = np.linalg.lstsq(h, z, rcond=None)
    if rank_h != h.shape[1]:
        raise ValueError("instrument design is singular")
    z_hat = h @ first_stage
    if np.linalg.matrix_rank(z_hat) != z_hat.shape[1]:
        raise ValueError("instrumented structural design is singular")
    stage_two, _, rank_z, _ = np.linalg.lstsq(z_hat, y, rcond=None)
    if rank_z != z_hat.shape[1]:
        raise ValueError("second-stage design is singular")
    residual_matrix = (y - z_hat @ stage_two).reshape(g_count, n_count).T
    centered_residuals = residual_matrix - np.mean(residual_matrix, axis=0)
    sigma = centered_residuals.T @ centered_residuals / (n_count - 1)
    if np.linalg.matrix_rank(sigma) != g_count:
        raise ValueError("estimated cross-equation covariance is singular")
    sigma_inverse = np.linalg.inv(sigma)

    # Apply Sigma^-1 kron I_N without materializing the full covariance matrix.
    weighted_z = (sigma_inverse @ z_hat.reshape(g_count, n_count, -1).transpose(1, 0, 2)).transpose(1, 0, 2).reshape(g_count * n_count, -1)
    weighted_y = (sigma_inverse @ y_panel).reshape(-1)
    normal = z_hat.T @ weighted_z
    covariance = np.linalg.inv(normal)
    estimates = covariance @ (z_hat.T @ weighted_y)
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))

    rho = estimates[:g_count]
    rho_se = standard_errors[:g_count]
    compact_beta = estimates[g_count:]
    compact_beta_se = standard_errors[g_count:]
    beta = np.empty((g_count, p_count), dtype=np.float64)
    beta_se = np.empty_like(beta)
    for g in range(g_count):
        for p in range(p_count):
            beta[g, p] = compact_beta[beta_map[g, p]]
            beta_se[g, p] = compact_beta_se[beta_map[g, p]]

    fitted_panel = (z @ estimates).reshape(g_count, n_count)
    r2 = [_correlation_squared(y_panel[g], fitted_panel[g]) for g in range(g_count)]
    pooled_r2 = _correlation_squared(y, fitted_panel.reshape(-1))
    direct = np.empty((g_count, p_count - 1), dtype=np.float64)
    total = np.empty_like(direct)
    identity = np.eye(n_count)
    for g in range(g_count):
        multiplier = np.linalg.inv(identity - rho[g] * w)
        direct[g] = beta[g, 1:] * np.trace(multiplier) / n_count
        total[g] = beta[g, 1:] * np.sum(multiplier) / n_count
    result = {
        "beta": beta.tolist(),
        "beta_standard_errors": beta_se.tolist(),
        "rho": rho.tolist(),
        "rho_standard_errors": rho_se.tolist(),
        "r2_by_equation": r2,
        "pooled_r2": pooled_r2,
        "direct_effects": direct.tolist(),
        "indirect_effects": (total - direct).tolist(),
        "total_effects": total.tolist(),
    }
    if not all(np.isfinite(np.asarray(v, dtype=float)).all() for v in result.values()):
        raise ValueError("estimation produced a non-finite output")
    return result
