"""Independent scientific implementations for retained v4 task auditing."""

from __future__ import annotations

from typing import Any

import numpy as np


def _finite(values: np.ndarray) -> list[float]:
    if not np.isfinite(values).all():
        raise ValueError("scientific calculation produced non-finite values")
    return values.astype(float).tolist()


def random_walk(case: dict[str, Any]) -> dict[str, Any]:
    atoms = int(case["atoms"])
    steps = int(case["steps"])
    jump = float(case["jump_size"])
    start, stop = map(int, case["seed_range"])
    if case.get("rng") != "numpy.random.RandomState":
        raise ValueError("unsupported RNG")
    curves = []
    for seed in range(start, stop):
        rng = np.random.RandomState(seed)
        possible = np.asarray(((jump, 0, 0), (-jump, 0, 0), (0, jump, 0), (0, -jump, 0), (0, 0, jump), (0, 0, -jump)))
        position = np.cumsum(possible[rng.choice(6, size=(atoms, steps))], axis=1)
        curve = []
        for lag_index in range(steps):
            displacement = np.concatenate((position[:, None, lag_index], position[:, lag_index + 1:] - position[:, :-(lag_index + 1)]), axis=1)
            curve.append(float(np.mean(np.sum(displacement * displacement, axis=-1))))
        curves.append(curve)
    msd = np.asarray(curves)
    time = np.arange(1, steps, dtype=float)
    fitted = msd[:, 1:]
    covariance = np.cov(fitted.T)
    design = np.column_stack((time, np.ones(time.size)))
    estimates = {}
    from scipy.linalg import pinv
    for name, weight in (("OLS", np.eye(time.size)), ("WLS", pinv(np.diag(np.diag(covariance)))), ("GLS", pinv(covariance))):
        beta = np.linalg.inv(design.T @ weight @ design) @ design.T @ weight @ fitted.T
        values = beta[0] / 6.0
        estimates[name] = {"mean": float(values.mean()), "std": float(values.std(ddof=0))}
    return {
        "time": _finite(time),
        "mean_msd": _finite(fitted.mean(axis=0)),
        "diffusion": estimates,
    }


def smw_stability(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.smw_scientific import solve as solve_smw
    return solve_smw(case)


def fixed_sparsity(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.fixed_sparsity_scientific import solve as solve_fixed_sparsity
    return solve_fixed_sparsity(case)


def sobi_equity_accessibility(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.sobiEquity_scientific import solve as solve_sobi_equity
    return solve_sobi_equity(case)


def stiefel_curvature(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.stiefelcurv_scientific import solve as solve_stiefel_curvature
    return solve_stiefel_curvature(case)


def covid19_environmental_correlates(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.covid19env_scientific import solve as solve_covid19env
    return solve_covid19env(case)


def rational_approx_eim(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.reim_scientific import solve as solve_reim
    return solve_reim(case)


SOLVERS = {
    "scibench_replication_0011": random_walk,
    "scibench_replication_0014": smw_stability,
    "scibench_replication_0015": fixed_sparsity,
    "scibench_replication_0017": sobi_equity_accessibility,
    "scibench_replication_0019": stiefel_curvature,
    "scibench_replication_0020": covid19_environmental_correlates,
    "scibench_replication_0021": rational_approx_eim,
}


def solve(task_id: str, value: dict[str, Any]) -> dict[str, Any]:
    return SOLVERS[task_id](value)
