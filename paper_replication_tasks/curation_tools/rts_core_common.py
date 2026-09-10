"""Validation and deterministic I/O contract for the 0023 random-time-shift core task.

The task computes the distribution of the limiting random variable
``W = lim_t e^{-lambda t} Z(t)`` of a supercritical multi-type continuous-time
branching process (equivalently, the random time-shift on the deterministic
macroscopic trajectory).

Input contract (``input.json``)
-------------------------------
``mean_matrix``          m x m real matrix (the branching-process mean/Jacobian matrix Omega).
``linear_terms``         list of ``[i, j, alpha_ij]`` triples (1-based type indices) giving the
                         non-zero linear coefficients of the progeny generating functions.
``quadratic_terms``      list of ``[i, k, l, beta_ikl]`` quadruples (1-based) giving the
                         non-zero quadratic coefficients of the progeny generating functions.
``lifetimes``            length-m list of positive per-type total event rates a_i.
``initial_condition``    length-m list of non-negative integers Z0.
``n_moments``            integer >= 3: number of moments used in the Taylor expansion.
``embedding_step``       positive real h: step size of the embedded (discrete-time) process.
``taylor_epsilon``       positive real: Taylor-region error tolerance.
``cdf_grid``             increasing list of non-negative reals at which the CDF of W is returned.
``cme_coefficients``     object with equal-length lists ``eta_real``, ``eta_imag``, ``beta_real``,
                         ``beta_imag`` giving the complex coefficients of the numerical
                         transform-inversion quadrature ``g(x) = Re(sum_j eta_j * G(beta_j / x)) / x``.

Output contract (``output.json``)
---------------------------------
``w_cdf``       list, same length as ``cdf_grid``: CDF of the unconditional W at each
                grid point (equals ``q_star`` at grid points that are exactly 0).
``w_moments``   length-5 list: the first five raw moments of W conditioned on
                non-extinction (W | W > 0), i.e. the moments the moment-matching
                branch fits (paper Sec 3.6).
``q_star``      scalar: ultimate extinction probability.
``lambda``      scalar: the Malthusian parameter (dominant eigenvalue of ``mean_matrix``).
"""

from __future__ import annotations

from typing import Any

import numpy as np

FIELDS = {
    "mean_matrix",
    "linear_terms",
    "quadratic_terms",
    "lifetimes",
    "initial_condition",
    "n_moments",
    "embedding_step",
    "taylor_epsilon",
    "cdf_grid",
    "cme_coefficients",
}
OUTPUT_FIELDS = {"w_cdf", "w_moments", "q_star", "lambda"}

MAX_TYPES = 8
MAX_MOMENTS = 80
MAX_GRID = 400
MAX_CME_TERMS = 200


def _square_matrix(value: Any, name: str) -> np.ndarray:
    if not isinstance(value, list) or not value or not all(isinstance(row, list) and row for row in value):
        raise ValueError(f"{name} must be a nonempty matrix")
    width = len(value[0])
    if any(len(row) != width for row in value):
        raise ValueError(f"{name} must be rectangular")
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if result.ndim != 2 or result.shape[0] != result.shape[1]:
        raise ValueError(f"{name} must be square")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite numbers")
    return result


def _real_vector(value: Any, name: str, length: int) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{name} must be a list of length {length}")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise ValueError(f"{name} must be numeric")
    result = np.asarray(value, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite numbers")
    return result


class BranchingProcess:
    """Parsed, validated branching-process specification."""

    __slots__ = (
        "omega",
        "alphas",
        "betas",
        "lifetimes",
        "z0",
        "n_moments",
        "h",
        "epsilon",
        "grid",
        "cme_eta",
        "cme_beta",
        "m",
    )

    def __init__(
        self,
        omega: np.ndarray,
        alphas: dict[int, dict[tuple[int, int], float]],
        betas: dict[int, dict[tuple[int, int, int], float]],
        lifetimes: np.ndarray,
        z0: np.ndarray,
        n_moments: int,
        h: float,
        epsilon: float,
        grid: np.ndarray,
        cme_eta: np.ndarray,
        cme_beta: np.ndarray,
    ) -> None:
        self.omega = omega
        self.alphas = alphas
        self.betas = betas
        self.lifetimes = lifetimes
        self.z0 = z0
        self.n_moments = n_moments
        self.h = h
        self.epsilon = epsilon
        self.grid = grid
        self.cme_eta = cme_eta
        self.cme_beta = cme_beta
        self.m = omega.shape[0]


def validate_case(value: Any) -> BranchingProcess:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("input fields differ from the contract")

    omega = _square_matrix(value["mean_matrix"], "mean_matrix")
    m = omega.shape[0]
    if not 1 <= m <= MAX_TYPES:
        raise ValueError("mean_matrix has an unsupported number of types")

    lifetimes = _real_vector(value["lifetimes"], "lifetimes", m)
    if np.any(lifetimes <= 0):
        raise ValueError("lifetimes must be positive")

    z0_raw = value["initial_condition"]
    if not isinstance(z0_raw, list) or len(z0_raw) != m:
        raise ValueError("initial_condition must be a list of length m")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in z0_raw):
        raise ValueError("initial_condition must be non-negative integers")
    z0 = np.asarray(z0_raw, dtype=int)
    if int(z0.sum()) == 0:
        raise ValueError("initial_condition must be non-zero")

    n_moments = value["n_moments"]
    if isinstance(n_moments, bool) or not isinstance(n_moments, int) or not 3 <= n_moments <= MAX_MOMENTS:
        raise ValueError("n_moments is out of range")

    h = value["embedding_step"]
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not (0.0 < float(h) <= 100.0):
        raise ValueError("embedding_step is out of range")
    h = float(h)

    epsilon = value["taylor_epsilon"]
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)) or not (0.0 < float(epsilon) <= 1.0):
        raise ValueError("taylor_epsilon is out of range")
    epsilon = float(epsilon)

    grid_raw = value["cdf_grid"]
    if not isinstance(grid_raw, list) or not 1 <= len(grid_raw) <= MAX_GRID:
        raise ValueError("cdf_grid has an unsupported length")
    grid = _real_vector(grid_raw, "cdf_grid", len(grid_raw))
    if np.any(grid < 0.0):
        raise ValueError("cdf_grid must be non-negative")
    if np.any(np.diff(grid) <= 0.0):
        raise ValueError("cdf_grid must be strictly increasing")

    alphas: dict[int, dict[tuple[int, int], float]] = {}
    lin = value["linear_terms"]
    if not isinstance(lin, list):
        raise ValueError("linear_terms must be a list")
    for entry in lin:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError("each linear term must be [i, j, alpha_ij]")
        i, j, coeff = entry
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (i, j)):
            raise ValueError("linear-term indices must be integers")
        if isinstance(coeff, bool) or not isinstance(coeff, (int, float)) or not np.isfinite(coeff):
            raise ValueError("linear-term coefficient must be finite")
        if not (1 <= i <= m and 1 <= j <= m):
            raise ValueError("linear-term index out of range")
        alphas.setdefault(i, {})[(i, j)] = float(coeff)

    betas: dict[int, dict[tuple[int, int, int], float]] = {}
    quad = value["quadratic_terms"]
    if not isinstance(quad, list):
        raise ValueError("quadratic_terms must be a list")
    for entry in quad:
        if not isinstance(entry, list) or len(entry) != 4:
            raise ValueError("each quadratic term must be [i, k, l, beta_ikl]")
        i, k, l, coeff = entry
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (i, k, l)):
            raise ValueError("quadratic-term indices must be integers")
        if isinstance(coeff, bool) or not isinstance(coeff, (int, float)) or not np.isfinite(coeff):
            raise ValueError("quadratic-term coefficient must be finite")
        if not (1 <= i <= m and 1 <= k <= m and 1 <= l <= m):
            raise ValueError("quadratic-term index out of range")
        betas.setdefault(i, {})[(i, k, l)] = float(coeff)

    if not alphas and not betas:
        raise ValueError("at least one progeny term is required")

    cme = value["cme_coefficients"]
    if not isinstance(cme, dict) or set(cme) != {"eta_real", "eta_imag", "beta_real", "beta_imag"}:
        raise ValueError("cme_coefficients fields differ from the contract")
    parts = {}
    for key in ("eta_real", "eta_imag", "beta_real", "beta_imag"):
        seq = cme[key]
        if not isinstance(seq, list) or not 1 <= len(seq) <= MAX_CME_TERMS:
            raise ValueError(f"cme_coefficients.{key} has an unsupported length")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not np.isfinite(x) for x in seq):
            raise ValueError(f"cme_coefficients.{key} must contain only finite numbers")
        parts[key] = np.asarray(seq, dtype=float)
    if len({len(v) for v in parts.values()}) != 1:
        raise ValueError("cme_coefficients arrays must have equal length")
    cme_eta = parts["eta_real"] + 1j * parts["eta_imag"]
    cme_beta = parts["beta_real"] + 1j * parts["beta_imag"]

    # Supercriticality: the dominant eigenvalue of Omega must be positive.
    lam = float(np.max(np.real(np.linalg.eigvals(omega))))
    if lam <= 0.0:
        raise ValueError("mean_matrix must be supercritical (dominant eigenvalue > 0)")

    return BranchingProcess(
        omega, alphas, betas, lifetimes, z0, n_moments, h, epsilon, grid, cme_eta, cme_beta
    )


def validate_output(value: Any, case: Any) -> None:
    bp = validate_case(case)
    if not isinstance(value, dict) or set(value) != OUTPUT_FIELDS:
        raise ValueError("output fields differ from the contract")

    w_cdf = value["w_cdf"]
    if not isinstance(w_cdf, list) or len(w_cdf) != len(bp.grid):
        raise ValueError("w_cdf must match cdf_grid length")
    cdf = _real_vector(w_cdf, "w_cdf", len(bp.grid))
    if np.any(cdf < -1e-9) or np.any(cdf > 1.0 + 1e-9):
        raise ValueError("w_cdf values must lie in [0, 1]")
    # The 21-term concentrated-matrix-exponential inversion produces small
    # oscillations (a few 1e-4) once the CDF has effectively reached 1; that is a
    # property of the paper's method, not an error.  Only reject decreases larger
    # than the w_cdf scoring atol.
    if np.any(np.diff(cdf) < -1e-3):
        raise ValueError("w_cdf must be non-decreasing")

    w_moments = value["w_moments"]
    if not isinstance(w_moments, list) or len(w_moments) != 5:
        raise ValueError("w_moments must be a length-5 list")
    moments = _real_vector(w_moments, "w_moments", 5)
    if np.any(moments <= 0.0):
        raise ValueError("w_moments must be positive")

    q_star = value["q_star"]
    if isinstance(q_star, bool) or not isinstance(q_star, (int, float)) or not (0.0 <= float(q_star) <= 1.0):
        raise ValueError("q_star must lie in [0, 1]")

    lam = value["lambda"]
    if isinstance(lam, bool) or not isinstance(lam, (int, float)) or not np.isfinite(lam) or float(lam) <= 0.0:
        raise ValueError("lambda must be a positive finite number")
