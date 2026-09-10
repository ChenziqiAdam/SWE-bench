#!/usr/bin/env python3
"""Curator reference submission for scibench_replication_0023_core.

Self-contained: shares no code with the oracle adapter or the independent audit
implementation.  Computes the random-time-shift distribution of a supercritical
multi-type branching process (paper: Morris, Maclean & Black, J. Math. Biol. 2024)
and emits the CDF of W on the requested grid, its first five raw moments, the
ultimate extinction probability, and the Malthusian parameter.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp


def _parse(value: dict):
    omega = np.asarray(value["mean_matrix"], dtype=float)
    m = omega.shape[0]
    a = np.asarray(value["lifetimes"], dtype=float)
    z0 = np.asarray(value["initial_condition"], dtype=int)
    lin: dict[int, list[tuple[int, float]]] = {i: [] for i in range(1, m + 1)}
    quad: dict[int, list[tuple[int, int, float]]] = {i: [] for i in range(1, m + 1)}
    for i, j, c in value["linear_terms"]:
        lin[i].append((j, float(c)))
    for i, k, l, c in value["quadratic_terms"]:
        quad[i].append((k, l, float(c)))
    return omega, a, z0, lin, quad, m


def _f(u, a, lin, quad, m):
    out = np.empty(m, dtype=u.dtype)
    for i in range(1, m + 1):
        const = a[i - 1] - sum(c for _, c in lin[i]) - sum(c for _, _, c in quad[i])
        acc = const / a[i - 1]
        for j, c in lin[i]:
            acc = acc + c / a[i - 1] * u[j - 1]
        for k, l, c in quad[i]:
            acc = acc + c / a[i - 1] * u[k - 1] * u[l - 1]
        out[i - 1] = acc
    return out


def _dominant(omega):
    vals, vecs = np.linalg.eig(omega)
    idx = int(np.argmax(vals.real))
    lam = float(vals.real[idx])
    u = vecs.real[:, idx]
    return lam, u / u.sum()


def _type_moments(a, lin, quad, m, lam, u1, count):
    mom = np.zeros((count, m))
    mom[0] = u1
    for n in range(2, count + 1):
        mat = np.eye(m)
        rhs = np.zeros(m)
        for i in range(1, m + 1):
            den = a[i - 1] + n * lam
            for j, c in lin[i]:
                mat[i - 1, j - 1] -= c / den
            for k, l, c in quad[i]:
                mat[i - 1, k - 1] -= c / den
                mat[i - 1, l - 1] -= c / den
                rhs[i - 1] += c / den * sum(
                    math.comb(n, r) * mom[r - 1, k - 1] * mom[n - r - 1, l - 1]
                    for r in range(1, n)
                )
        mom[n - 1] = np.linalg.solve(mat, rhs)
    return mom


def solve(value: dict) -> dict:
    omega, a, z0, lin, quad, m = _parse(value)
    n = int(value["n_moments"])
    h = float(value["embedding_step"])
    eps = float(value["taylor_epsilon"])
    grid = np.asarray(value["cdf_grid"], dtype=float)

    lam, u1 = _dominant(omega)
    mom = _type_moments(a, lin, quad, m, lam, u1, n + 1)
    err = mom[-1]
    mom = mom[:-1]
    radius = float(np.min(math.factorial(n + 1) * eps / err) ** (1.0 / (n + 1)))  # paper Eq. 19

    fact = np.array([math.factorial(k) for k in range(1, n + 1)], dtype=float)
    coeffs = np.vstack([np.ones(m), mom / fact[:, None]])
    mu = math.exp(lam * h)

    def rhs(_t, y):
        w = y[:m] + 1j * y[m:]
        d = -a * w + a * _f(w, a, lin, quad, m)
        return np.concatenate([d.real, d.imag])

    def phi_types(s):
        powers = np.array([(-s) ** k for k in range(n + 1)])
        return coeffs.T @ powers

    def phi_w(s):
        if abs(s) <= radius:
            pt = phi_types(s)
        else:
            kappa = max(1, math.ceil(-math.log(radius / abs(s)) / (lam * h)))
            y0 = phi_types(s * mu ** (-kappa))
            sol = solve_ivp(
                rhs,
                (0.0, kappa * h),
                np.concatenate([y0.real, y0.imag]),
                method="RK45",
                rtol=1e-11,
                atol=1e-12,
            )
            yf = sol.y[:, -1]
            pt = yf[:m] + 1j * yf[m:]
        out = 1.0 + 0.0j
        for idx, z in enumerate(z0):
            out *= pt[idx] ** int(z)
        return out

    # Extinction probabilities via relaxation of the Riccati ODE from 0.
    sol = solve_ivp(
        lambda _t, q: -a * q + a * _f(q, a, lin, quad, m),
        (0.0, 4000.0),
        np.zeros(m),
        method="RK45",
        rtol=1e-10,
        atol=1e-12,
    )
    q_types = np.clip(sol.y[:, -1], 0.0, 1.0)
    q_star = float(np.prod(q_types ** z0))

    cme = value["cme_coefficients"]
    eta = np.array(cme["eta_real"]) + 1j * np.array(cme["eta_imag"])
    beta = np.array(cme["beta_real"]) + 1j * np.array(cme["beta_imag"])

    def cdf(x):
        if x == 0.0:
            return q_star
        acc = sum(e * (phi_w(b / x) / (b / x)) for e, b in zip(eta, beta))
        return min(1.0, float(acc.real / x))

    w_cdf = [cdf(float(x)) for x in grid]

    # W moments: multinomial aggregation over the founding individuals.
    founders = [t for t, c in enumerate(z0) for _ in range(int(c))]
    mm = len(founders)
    tm = _type_moments(a, lin, quad, m, lam, u1, 6)[:5]
    w_moments = np.zeros(5)
    for k in range(1, 6):
        for comp in _compositions(k, mm):
            coef = math.factorial(k)
            for c in comp:
                coef //= math.factorial(c)
            term = 1.0
            for slot, c in enumerate(comp):
                if c:
                    term *= tm[c - 1, founders[slot]]
            w_moments[k - 1] += coef * term
    w_moments /= 1.0 - q_star

    return {
        "w_cdf": [float(x) for x in w_cdf],
        "w_moments": [float(x) for x in w_moments],
        "q_star": q_star,
        "lambda": float(lam),
    }


def _compositions(k, m):
    if m == 1:
        yield [k]
        return
    for first in range(k + 1):
        for rest in _compositions(k - first, m - 1):
            yield [first] + rest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    value = json.loads(Path(args.input).read_text())
    result = solve(value)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "output.json").write_text(json.dumps(result, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
