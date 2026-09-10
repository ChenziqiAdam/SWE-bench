"""Independent Python implementation of the random-time-shift computation.

Written only from the equations in

    Morris, Maclean & Black, "Computation of random time-shift distributions for
    stochastic population models", J. Math. Biol. 89:33 (2024).

This module shares no code with ``rts_core_adapter.py`` (the Julia port used as
the oracle).  It is used to cross-check that oracle and to derive comparison
tolerances.  Design choices deliberately differ from the port where the paper
leaves them open: the moment recursion is assembled directly from the
functional-equation derivatives, the embedded progeny generating function is
obtained with an explicit fixed-step integrator, and the extinction probabilities
are found by a damped fixed-point iteration on f_i(q) = q rather than by ODE
relaxation.

Contract: see ``rts_core_common``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.integrate import solve_ivp

from rts_core_common import validate_case


def _dominant_eig(omega: np.ndarray) -> tuple[float, np.ndarray]:
    vals, vecs = np.linalg.eig(omega)
    vals = vals.real
    vecs = vecs.real
    idx = int(np.argmax(vals))
    lam = float(vals[idx])
    u = vecs[:, idx]
    u = u / u.sum()
    return lam, u


def _progeny_generating_function(bp, u: np.ndarray) -> np.ndarray:
    """f_i(u): constant term chosen so f_i(1) = 1."""
    m = bp.m
    out = np.zeros(m, dtype=u.dtype)
    for i in range(1, m + 1):
        a_i = bp.lifetimes[i - 1]
        lin = bp.alphas.get(i, {})
        quad = bp.betas.get(i, {})
        const = a_i - sum(lin.values()) - sum(quad.values())
        val = const / a_i
        for (_i, j), c in lin.items():
            val = val + (c / a_i) * u[j - 1]
        for (_i, k, l), c in quad.items():
            val = val + (c / a_i) * u[k - 1] * u[l - 1]
        out[i - 1] = val
    return out


def _moments(bp, lam: float, u: np.ndarray, num_moments: int) -> np.ndarray:
    """E[W_i^n] via the functional-equation recursion (paper Sec 3.3-3.4).

    The n-th derivative of phi_i = f~_i(phi) at 0 gives a linear system
        (I - J~) M[n] = d[n],
    where J~ has entries alpha_ij/(a_i + n lam) and 2 beta_ikl/(a_i + n lam)
    (accumulated over k, l), and d[n] collects the binomial convolution of the
    quadratic terms over the already-computed lower moments.
    """
    m = bp.m
    M = np.zeros((num_moments, m))
    M[0, :] = u
    for n in range(2, num_moments + 1):
        A = np.eye(m)
        rhs = np.zeros(m)
        for i in range(1, m + 1):
            denom = bp.lifetimes[i - 1] + n * lam
            for (_i, j), c in bp.alphas.get(i, {}).items():
                A[i - 1, j - 1] -= c / denom
            for (_i, k, l), c in bp.betas.get(i, {}).items():
                A[i - 1, k - 1] -= c / denom
                A[i - 1, l - 1] -= c / denom
                conv = 0.0
                for r in range(1, n):
                    conv += math.comb(n, r) * M[r - 1, k - 1] * M[n - r - 1, l - 1]
                rhs[i - 1] += (c / denom) * conv
        M[n - 1, :] = np.linalg.solve(A, rhs)
    return M


def _taylor_radius(epsilon: float, err_moment: np.ndarray, n: int) -> float:
    # L(n, eps) = ( (n+1)! * eps / gamma )^{1/(n+1)}, paper Eq. 19, with
    # gamma = max_i E[W_i^{n+1}] (here err_moment holds the (n+1)-th moments).
    safe = np.where(np.abs(err_moment) > 0.0, err_moment, np.inf)
    return float(np.min(math.factorial(n + 1) * epsilon / safe) ** (1.0 / (n + 1)))


def _lst_near_zero(s: complex, coeffs: np.ndarray) -> np.ndarray:
    # coeffs[k, i] = M[k, i] / k!  ; phi_i(s) = sum_k (-1)^k coeffs[k,i] s^k  (k>=0, coeffs[0]=1)
    m = coeffs.shape[1]
    powers = np.array([(-s) ** k for k in range(coeffs.shape[0])], dtype=complex)
    return coeffs.T @ powers if False else np.array(
        [sum(((-1.0) ** k) * coeffs[k, i] * s ** k for k in range(coeffs.shape[0])) for i in range(m)],
        dtype=complex,
    )


def _riccati_flow(bp):
    """flow(u0, T): solution at t = T of du/dt = -a_i u_i + a_i f_i(u), u(0) = u0.

    Adaptive Dormand-Prince (scipy ``RK45``).  The kappa-fold composition of the
    [0, h] map in the paper is the [0, kappa*h] flow of this autonomous system, so
    a single integration suffices.
    """
    a = np.array(bp.lifetimes, dtype=float)
    m = bp.m

    def rhs(_t, y):
        u = y[:m] + 1j * y[m:]
        du = -a * u + a * _progeny_generating_function(bp, u)
        return np.concatenate([du.real, du.imag])

    def flow(u0: np.ndarray, T: float) -> np.ndarray:
        y0 = np.concatenate([np.real(u0), np.imag(u0)])
        sol = solve_ivp(rhs, (0.0, T), y0, method="RK45", rtol=1e-11, atol=1e-12)
        yf = sol.y[:, -1]
        return yf[:m] + 1j * yf[m:]

    return flow


def _extinction(bp) -> np.ndarray:
    """Solve f_i(q) = q by damped fixed-point iteration from q = 0."""
    q = np.zeros(bp.m)
    for _ in range(200000):
        nxt = _progeny_generating_function(bp, q)
        step = 0.5 * (nxt - q)
        q = np.clip(q + step, 0.0, 1.0)
        if np.max(np.abs(step)) < 1e-14:
            break
    return q


def solve(value: dict) -> dict:
    bp = validate_case(value)
    n = bp.n_moments

    lam, u = _dominant_eig(bp.omega)
    M = _moments(bp, lam, u, n + 1)
    err_moment = M[-1, :]
    M = M[:-1, :]
    radius = _taylor_radius(bp.epsilon, err_moment, n)

    coeffs = np.vstack([np.ones(bp.m), M / np.array([math.factorial(k) for k in range(1, n + 1)])[:, None]])
    mu = math.exp(lam * bp.h)
    flow = _riccati_flow(bp)
    z0 = bp.z0

    def phi_w(s: complex) -> complex:
        if abs(s) <= radius:
            phi_types = _lst_near_zero(s, coeffs)
        else:
            kappa = max(1, math.ceil(-math.log(radius / abs(s)) / (lam * bp.h)))
            phi_types = _lst_near_zero(s * mu ** (-kappa), coeffs)
            phi_types = flow(phi_types, kappa * bp.h)
        out = 1.0 + 0.0j
        for idx, z in enumerate(z0):
            out *= phi_types[idx] ** z
        return out

    q_types = _extinction(bp)
    q_star = float(np.prod(q_types ** z0))

    eta, beta = bp.cme_eta, bp.cme_beta

    def cdf(x: float) -> float:
        if x == 0.0:
            return q_star
        acc = sum(e * (phi_w(b / x) / (b / x)) for e, b in zip(eta, beta))
        return min(1.0, float(np.real(acc) / x))

    w_cdf = [cdf(float(x)) for x in bp.grid]

    # W moments from the type moments (multinomial aggregation, paper Eq. 38).
    M6 = _moments(bp, lam, u, 6)[:5, :]
    w_moments = _aggregate_w_moments(M6, z0, q_star)

    return {
        "w_cdf": [float(x) for x in w_cdf],
        "w_moments": [float(x) for x in w_moments],
        "q_star": q_star,
        "lambda": float(lam),
    }


def _aggregate_w_moments(type_moments: np.ndarray, z0: np.ndarray, q_star: float) -> np.ndarray:
    """E[W^k] = (1 - q*)^-1 * sum over compositions of k across the m founding individuals."""
    founders: list[int] = []
    for type_idx, count in enumerate(z0):
        founders.extend([type_idx] * int(count))
    m = len(founders)
    out = np.zeros(5)
    for k in range(1, 6):
        total = 0.0
        for comp in _compositions(k, m):
            coeff = math.factorial(k)
            for c in comp:
                coeff //= math.factorial(c)
            term = 1.0
            for slot, c in enumerate(comp):
                if c > 0:
                    term *= type_moments[c - 1, founders[slot]]
            total += coeff * term
        out[k - 1] = total
    return out / (1.0 - q_star)


def _compositions(k: int, m: int):
    if m == 1:
        yield [k]
        return
    for first in range(k + 1):
        for rest in _compositions(k - first, m - 1):
            yield [first] + rest
