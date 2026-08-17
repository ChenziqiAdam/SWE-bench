"""Deterministic clean-room implementations for v4 gold auditing.

The benchmark runner never imports this module.  It is curator/reference code only.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import gammaln, logsumexp


def _finite(values: np.ndarray) -> list[float]:
    if not np.isfinite(values).all():
        raise ValueError("scientific calculation produced non-finite values")
    return values.astype(float).tolist()


def kinetics(case: dict[str, Any]) -> dict[str, Any]:
    rate = float(case["rate_constant"])
    initial = float(case["initial_concentration"])
    times = np.asarray(case["time_grid"], dtype=float)
    sigma = float(case["noise_std"])
    count = int(case["replicates"])
    if case.get("rng") != "numpy.random.Generator.PCG64":
        raise ValueError("unsupported RNG")
    rng = np.random.default_rng(int(case["seed"]))
    mean = initial * np.exp(-rate * times[:, None])
    observations = rng.normal(mean, sigma, size=(times.size, count))
    # Independently reproduce the official script's complete-column rejection
    # rule, including duplicate column indices returned by np.where.
    bad_columns = np.where(observations < 0)[1]
    while bad_columns.size:
        observations[:, bad_columns] = rng.normal(mean, sigma, size=(times.size, bad_columns.size))
        bad_columns = np.where(observations <= 0)[1]
    design = np.column_stack((times, np.ones(times.size)))
    ols = -np.linalg.lstsq(design, np.log(observations), rcond=None)[0][0]
    wls = np.empty(count)
    nonlinear = np.empty(count)
    model = lambda t, k, a0: a0 * np.exp(-k * t)
    for column in range(count):
        y = observations[:, column]
        weights = np.diag(y / sigma)
        wls[column] = -(np.linalg.pinv(design.T @ weights @ design) @ design.T @ weights @ np.log(y))[0]
        nonlinear[column] = curve_fit(model, times, y, p0=(rate, initial), maxfev=3000)[0][0]
    def summary(values: np.ndarray) -> dict[str, Any]:
        normalized = values / rate
        return {"mean": float(normalized.mean()), "ci95": _finite(np.percentile(normalized, [2.5, 97.5]))}
    return {"linear_ols": summary(ols), "linear_wls": summary(wls), "nonlinear": summary(nonlinear)}


def spin_curves(case: dict[str, Any]) -> dict[str, Any]:
    spin = float(case["spin"])
    temperature = np.asarray(case["temperature_grid"], dtype=float)
    field_scale = float(case.get("field_scale_kelvin", 1.343427))
    m = np.arange(-spin, spin + 0.5, 1.0)
    exponent = field_scale * m[:, None] / temperature[None, :]
    weights = np.exp(exponent - exponent.max(axis=0))
    quantum = (m[:, None] * weights).sum(axis=0) / weights.sum(axis=0) / spin
    x = field_scale * spin / temperature
    classical = 1.0 / np.tanh(x) - 1.0 / x
    available = {"quantum": quantum, "classical": classical}
    names = case["approximations"]
    if not names or any(name not in available for name in names):
        raise ValueError("unsupported approximation")
    return {"temperature": _finite(temperature), "curves": {name: _finite(available[name]) for name in names}}


def floquet_dmd(case: dict[str, Any]) -> dict[str, Any]:
    if set(case) != {"snapshot_blocks", "dmd_rank", "prediction_steps"}:
        raise ValueError("invalid exact-DMD fields")
    blocks = np.asarray(case["snapshot_blocks"], dtype=float)
    rank = case["dmd_rank"]
    steps = case["prediction_steps"]
    if blocks.ndim != 3 or blocks.shape[0] < 1 or blocks.shape[1] < 1 or blocks.shape[2] < 2 or not np.isfinite(blocks).all():
        raise ValueError("snapshot_blocks must be finite with shape (blocks>=1, state>=1, time>=2)")
    if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= min(blocks.shape[1], blocks.shape[0] * (blocks.shape[2] - 1)):
        raise ValueError("invalid dmd_rank")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("invalid prediction_steps")
    x1 = np.concatenate([block[:, :-1] for block in blocks], axis=1)
    x2 = np.concatenate([block[:, 1:] for block in blocks], axis=1)
    u, singular, vh = np.linalg.svd(x1, full_matrices=False)
    u, singular, vh = u[:, :rank], singular[:rank], vh[:rank]
    if np.any(singular == 0):
        raise ValueError("requested DMD rank contains a zero singular value")
    reduced = u.conj().T @ x2 @ vh.conj().T @ np.diag(1.0 / singular)
    eigenvalues, eigenvectors = np.linalg.eig(reduced)
    modes = x2 @ vh.conj().T @ np.diag(1.0 / singular) @ eigenvectors
    order = np.lexsort((eigenvalues.imag, eigenvalues.real))
    coefficients = np.linalg.pinv(modes) @ blocks[-1, :, -1]
    times = np.arange(1, steps + 1, dtype=float)
    prediction = np.asarray([modes @ (eigenvalues ** time * coefficients) for time in times]).T
    prediction = np.real_if_close(prediction)
    if np.iscomplexobj(prediction) or not np.isfinite(prediction).all():
        raise ValueError("exact-DMD prediction is not finite and real")
    return {
        "eigenvalues": [[float(z.real), float(z.imag)] for z in eigenvalues[order]],
        "prediction": np.asarray(prediction, dtype=float).tolist(),
    }


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


def anisotropy(case: dict[str, Any]) -> dict[str, Any]:
    if set(case) != {"spin", "anisotropy_ratio", "temperature_grid", "orientation_grid"}:
        raise ValueError("invalid anisotropy fields")
    spin = float(case["spin"])
    two_s = int(round(2 * spin))
    ratio = float(case["anisotropy_ratio"])
    temperatures = np.asarray(case["temperature_grid"], dtype=float)
    orientation = np.asarray(case["orientation_grid"], dtype=float)
    if not math.isfinite(spin) or spin <= 0 or not math.isclose(2 * spin, two_s, abs_tol=1e-12):
        raise ValueError("spin must be a positive integer or half-integer")
    if not math.isfinite(ratio):
        raise ValueError("anisotropy_ratio must be finite")
    if temperatures.ndim != 1 or temperatures.size < 1 or not np.isfinite(temperatures).all() or np.any(temperatures <= 0):
        raise ValueError("temperature_grid must be finite and positive")
    if orientation.ndim != 1 or orientation.size < 1 or not np.isfinite(orientation).all() or np.any(np.abs(orientation) >= 1):
        raise ValueError("orientation_grid must be finite and strictly inside (-1, 1)")
    a1, a2 = 1.0, ratio
    p = np.arange(two_s + 1, dtype=float)
    log_binomial = gammaln(two_s + 1) - gammaln(p + 1) - gammaln(two_s - p + 1)
    hamiltonian = np.empty((temperatures.size, orientation.size))
    field = np.empty_like(hamiltonian)
    for ti, temp in enumerate(temperatures):
        beta = 1.0 / temp
        for oi, n in enumerate(orientation):
            u2 = (1.0 - n) / (1.0 + n)
            terms = log_binomial + p * math.log(u2) + beta * a2 * p * p - beta * (two_s * a2 + a1) * p
            log_l = logsumexp(terms)
            expected_p = float(np.sum(p * np.exp(terms - log_l)))
            hamiltonian[ti, oi] = (-log_l + two_s * math.log1p(u2)) / beta
            derivative = (2.0 * expected_p / (1.0 - n * n) - two_s / (1.0 + n)) / beta
            field[ti, oi] = -derivative / spin
    return {"temperature": _finite(temperatures), "orientation": _finite(orientation), "hamiltonian": hamiltonian.tolist(), "effective_field": field.tolist()}


def conditional_moments(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.conditional_moment_scientific import solve as solve_conditional_moments
    return solve_conditional_moments(case)


def smw_stability(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.smw_scientific import solve as solve_smw
    return solve_smw(case)


SOLVERS = {
    "scibench_replication_0007": kinetics,
    "scibench_replication_0008": spin_curves,
    "scibench_replication_0009": floquet_dmd,
    "scibench_replication_0011": random_walk,
    "scibench_replication_0012": anisotropy,
    "scibench_replication_0013": conditional_moments,
    "scibench_replication_0014": smw_stability,
}


def solve(task_id: str, value: dict[str, Any]) -> dict[str, Any]:
    return SOLVERS[task_id](value)
