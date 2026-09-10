#!/usr/bin/env python3
"""Python port of RandomTimeShifts.jl used as the 0023 core-task oracle.

PROVENANCE / G8 WAIVER
----------------------
The official implementation accompanying

    Morris, Maclean & Black, "Computation of random time-shift distributions for
    stochastic population models", J. Math. Biol. 89:33 (2024),
    doi:10.1007/s00285-024-02132-6

is the Julia package ``github.com/djmorris7/RandomTimeShifts.jl``.  This file is a
line-faithful Python transcription of that package pinned at commit

    baf6da64fce7489503d709a9d1bc99080c5a5aa7

with the source-file SHA-256 digests recorded in ``rts_core_port_provenance.json``.
The SciBench repository has no Julia toolchain, so PAPER.md's requirement that the
oracle be the pinned official implementation executed as-is is **not** met; task
0023 is therefore promoted under a recorded ``G8_oracle_validity`` waiver.  This
port is cross-checked against (a) a separately written independent Python
implementation (``rts_core_scientific.py``) that shares no code with this file and
(b) the SIR closed form (paper Eq. 41-42).

Mapping to the Julia source (module ``RandomTimeShifts``):
  calculate_BP_contributions   <- src/LST_approximation.jl
  calculate_moments_generic    <- src/diff_phi_functional_equations.jl
  error_bounds / moment_coeffs / lst_s0 / calculate_kappa / lst_s_rest / lst
                               <- src/LST_approximation.jl
  F_offspring_ode / kappa-fold f~ composition
                               <- src/LST_approximation.jl; the kappa-fold [0,h]
                                  composition is collapsed to one [0,kappa*h]
                                  integration (Tsit5 -> scipy DOP853)
  load_cme_hyper_params / invert_lst / construct_W_cdf_ilst
                               <- src/inverse_LST.jl
  eval_cdf                     <- src/numerically_approx_pdf_cdf.jl
  compute_W_moments            <- src/moment_matching.jl
Extinction probabilities q_i are obtained by integrating the Riccati ODE
``du_i = -a_i u_i + a_i f_i(u)`` to steady state (equivalent to f_i(q) = q), as in
the example driver ``SEIR_W.jl::calculate_extinction_probs``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.special import gammaln

from rts_core_common import BranchingProcess, validate_case

_PORT_COMMIT = "baf6da64fce7489503d709a9d1bc99080c5a5aa7"
_CME_TABLE = Path(__file__).with_name("rts_iltcme_ext.json")
_CME_TERMS = 21
_ODE_RTOL = 1e-12
_ODE_ATOL = 1e-13
_EXTINCT_T = 4000.0


# --------------------------------------------------------------------------- #
# Branching-process spectral quantities (src/LST_approximation.jl)
# --------------------------------------------------------------------------- #
def progeny_constants(bp: BranchingProcess) -> np.ndarray:
    """c_i such that f_i(1,...,1) = 1, i.e. c_i = a_i - sum(alpha_ij) - sum(beta_ikl).

    Mirrors the per-model Riccati ODEs in the Julia example drivers, where the
    constant term of ``f_i`` is written explicitly (e.g. the ``gamma`` term in
    ``SEIR_W.jl::F_fixed_s_ode!`` for the infective type).
    """
    c = np.array(bp.lifetimes, dtype=float)
    for i in range(1, bp.m + 1):
        for coeff in bp.alphas.get(i, {}).values():
            c[i - 1] -= coeff
        for coeff in bp.betas.get(i, {}).values():
            c[i - 1] -= coeff
    return c


def _f_i_factory(bp: BranchingProcess, dtype):
    """Return f(u) -> array of progeny generating function values f_i(u)."""
    m = bp.m
    lifetimes = bp.lifetimes
    consts = progeny_constants(bp)

    def f_i(u: np.ndarray) -> np.ndarray:
        out = np.zeros(m, dtype=dtype)
        for i in range(1, m + 1):
            val = consts[i - 1] / lifetimes[i - 1]
            for (_i, j), alpha_ij in bp.alphas.get(i, {}).items():
                val += (alpha_ij / lifetimes[i - 1]) * u[j - 1]
            for (_i, k, l), beta_ikl in bp.betas.get(i, {}).items():
                val += (beta_ikl / lifetimes[i - 1]) * u[k - 1] * u[l - 1]
            out[i - 1] = val
        return out

    return f_i


def calculate_bp_contributions(omega: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    rvals, rvecs = np.linalg.eig(omega)
    lvals, lvecs = np.linalg.eig(omega.T)
    rvals = np.real(rvals)
    lvals = np.real(lvals)
    rvecs = np.real(rvecs)
    lvecs = np.real(lvecs)
    lam = float(np.max(rvals))
    r_index = int(np.argmin(np.abs(rvals - lam)))
    l_index = int(np.argmin(np.abs(lvals - lam)))
    u = rvecs[:, r_index]
    v = lvecs[:, l_index]
    u_norm = u / np.sum(u)
    v_norm = v / np.sum(u_norm * v)
    return lam, u_norm, v_norm


# --------------------------------------------------------------------------- #
# Moment engine (src/diff_phi_functional_equations.jl::calculate_moments_generic)
# --------------------------------------------------------------------------- #
def _tilde(c: float, lifetime: float, n: int, lam: float) -> float:
    return c / (lifetime + n * lam)


def _compute_d_n(betas_i: dict, lifetime: float, prev_moments: np.ndarray, n: int, lam: float) -> float:
    d_n = 0.0
    for (_i, k, l), val in betas_i.items():
        beta_tilde = _tilde(val, lifetime, n, lam)
        # prev_moments is 0-indexed by moment number minus 1; the Julia code uses
        # prev_moments[r, k] and prev_moments[n - r, l] for r in 1:(n-1).
        acc = 0.0
        for r in range(1, n):
            acc += math.comb(n, r) * prev_moments[r - 1, k - 1] * prev_moments[n - r - 1, l - 1]
        d_n += beta_tilde * acc
    return d_n


def calculate_moments_generic(bp: BranchingProcess, num_moments: int) -> tuple[float, np.ndarray, np.ndarray]:
    omega = bp.omega
    lifetimes = bp.lifetimes
    m = bp.m
    lam, u_norm, v_norm = calculate_bp_contributions(omega)

    identity = np.eye(m)
    moments = np.zeros((num_moments, m))
    moments[0, :] = u_norm

    for n in range(2, num_moments + 1):
        C = np.zeros((m, m))
        d = np.zeros(m)
        for i in range(1, m + 1):
            C[i - 1, :] = identity[i - 1, :]
            if i in bp.alphas:
                for (_i, j), alpha_ij in bp.alphas[i].items():
                    C[i - 1, :] -= _tilde(alpha_ij, lifetimes[i - 1], n, lam) * identity[j - 1, :]
            if i in bp.betas:
                for (_i, k, l), beta_ikl in bp.betas[i].items():
                    C[i - 1, :] -= _tilde(beta_ikl, lifetimes[i - 1], n, lam) * (
                        identity[k - 1, :] + identity[l - 1, :]
                    )
                d[i - 1] = _compute_d_n(bp.betas[i], lifetimes[i - 1], moments, n, lam)
        moments[n - 1, :] = np.linalg.solve(C, d)

    return lam, u_norm, moments


# --------------------------------------------------------------------------- #
# LST approximation (src/LST_approximation.jl)
# --------------------------------------------------------------------------- #
def error_bounds(epsilon: float, error_moments: np.ndarray, n: int) -> float:
    """Taylor-region radius L(n, eps) = ( (n+1)! * eps / gamma )^{1/(n+1)}  (paper Eq. 19).

    ``error_moments`` are the (n+1)-th moments E[W_i^{n+1}] (the ``gamma`` bound).
    The published Julia (`RandomTimeShifts.jl::error_bounds`) uses ``n!`` here; we
    follow the paper's Eq. 19 ``(n+1)!`` so the oracle, the independent
    implementation, and a paper-only blind implementation agree.  See
    ``0023_core_cases_design.md``.
    """
    return float(np.min(math.exp(gammaln(n + 2)) * epsilon / error_moments) ** (1.0 / (n + 1)))


def moment_coeffs(moments: np.ndarray) -> np.ndarray:
    coeffs = np.zeros_like(moments)
    n_moments = moments.shape[0]
    for i in range(1, n_moments + 1):
        coeffs[i - 1, :] = moments[i - 1, :] / math.exp(gammaln(i + 1))
    return coeffs


def lst_s0(s: complex, coeffs_col: np.ndarray) -> complex:
    y = 1.0 + 0.0j
    for k, c in enumerate(coeffs_col, start=1):
        y += ((-1.0) ** k) * c * s ** k
    return y


def lst_s0_all(s: complex, coeffs: np.ndarray) -> np.ndarray:
    return np.array([lst_s0(s, coeffs[:, j]) for j in range(coeffs.shape[1])], dtype=complex)


def calculate_kappa(s: complex, L: float, lam: float, h: float) -> int:
    return max(1, math.ceil(-math.log(L / abs(s)) / (lam * h)))


def make_riccati_flow(bp: BranchingProcess):
    """Return flow(u0, T): integrate du_i/dt = -a_i u_i + a_i f_i(u) over [0, T].

    Composing the embedded progeny GF f~ (the [0, h] flow) kappa times is exactly
    the [0, kappa*h] flow of this autonomous system, so a single integration
    replaces the kappa-fold composition of the Julia reference (which re-solves
    [0, h] kappa times).  Adaptive Dormand-Prince 8(5,3) at tight tolerance; the
    step size grows automatically once the flow settles onto its fixed point, so
    the near-critical regime (kappa*h ~ hundreds) stays tractable.
    """
    m = bp.m
    lifetimes = bp.lifetimes
    f_i = _f_i_factory(bp, complex)

    def rhs(_t, y):
        u = y[:m] + 1j * y[m:]
        du = -lifetimes * u + lifetimes * f_i(u)
        return np.concatenate([du.real, du.imag])

    def flow(u0: np.ndarray, T: float) -> np.ndarray:
        y0 = np.concatenate([np.real(u0), np.imag(u0)])
        sol = solve_ivp(rhs, (0.0, T), y0, method="DOP853", rtol=_ODE_RTOL, atol=_ODE_ATOL)
        yf = sol.y[:, -1]
        return yf[:m] + 1j * yf[m:]

    return flow


def construct_lst(coeffs: np.ndarray, mu_embed: float, flow, L: float, z0: np.ndarray, lam: float, h: float):
    def lst_s0_x(s):
        return lst_s0_all(s, coeffs)

    def lst_types(s):
        if abs(s) <= L:
            return lst_s0_x(s)
        kappa = calculate_kappa(s, L, lam, h)
        y0 = lst_s0_x(s * mu_embed ** (-kappa))
        return flow(y0, kappa * h)

    def lst_w(s):
        y = lst_types(s)
        out = 1.0 + 0.0j
        for idx, z in enumerate(z0):
            out *= y[idx] ** z
        return out

    return lst_w


# --------------------------------------------------------------------------- #
# CME inversion (src/inverse_LST.jl)
# --------------------------------------------------------------------------- #
def load_cme_hyper_params(n_f_evals: int) -> tuple[np.ndarray, np.ndarray]:
    """Select the min-cv2 CME parameter set with n + 1 <= n_f_evals terms.

    Retained for provenance/testing; at runtime the selected coefficients are
    supplied in ``input.json`` as ``cme_coefficients`` (they are a fixed numerical
    table from http://inverselaplace.org that the paper does not derive).
    """
    table = json.loads(_CME_TABLE.read_text())
    params = table[0]
    for p in table:
        if p["cv2"] < params["cv2"] and p["n"] + 1 <= n_f_evals:
            params = p
    eta = np.array(params["eta_re"], dtype=float) + 1j * np.array(params["eta_im"], dtype=float)
    beta = np.array(params["beta_re"], dtype=float) + 1j * np.array(params["beta_im"], dtype=float)
    return eta, beta


def invert_lst(f, x: float, eta: np.ndarray, beta: np.ndarray) -> float:
    res = sum(e * f(b / x) for e, b in zip(eta, beta))
    return float(np.real(res) / x)


def construct_w_cdf_ilst(lst_w, q_star: float, eta: np.ndarray, beta: np.ndarray):
    def w_cdf(x: float) -> float:
        if x == 0.0:
            return q_star
        return invert_lst(lambda s: lst_w(s) / s, x, eta, beta)

    return w_cdf


def eval_cdf(cdf, xs: np.ndarray) -> np.ndarray:
    return np.array([min(1.0, cdf(float(xi))) for xi in xs])


# --------------------------------------------------------------------------- #
# Extinction probabilities (SEIR_W.jl::calculate_extinction_probs, generalised)
# --------------------------------------------------------------------------- #
def calculate_extinction_probs(bp: BranchingProcess) -> np.ndarray:
    """q_i solving f_i(q) = q, via relaxation of du_i = -a_i u_i + a_i f_i(u) from 0.

    Equivalent to the ODE relaxation in ``SEIR_W.jl::calculate_extinction_probs``;
    integrated here with a fixed-step explicit Euler scheme to steady state.
    """
    lifetimes = bp.lifetimes
    f_i = _f_i_factory(bp, float)

    def rhs(_t, u):
        return -lifetimes * u + lifetimes * f_i(u)

    sol = solve_ivp(
        rhs, (0.0, _EXTINCT_T), np.zeros(bp.m), method="DOP853", rtol=1e-12, atol=1e-13
    )
    return np.clip(sol.y[:, -1], 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Moment aggregation (src/moment_matching.jl::compute_W_moments)
# --------------------------------------------------------------------------- #
def _generate_partitions(k: int, m: int) -> list[list[int]]:
    out: list[list[int]] = []

    def rec(current: list[int], remaining_sum: int, remaining_ints: int) -> None:
        if remaining_ints == 0:
            if remaining_sum == 0:
                out.append(list(current))
            return
        for x in range(remaining_sum + 1):
            rec(current + [x], remaining_sum - x, remaining_ints - 1)

    rec([], k, m)
    return out


def compute_w_moments(type_moments: np.ndarray, z0_bp: np.ndarray, q_star: float, num_moments: int = 5) -> np.ndarray:
    w_moments = np.zeros(num_moments)
    z0_cumsum = np.cumsum(z0_bp)
    m = int(np.sum(z0_bp))
    for k in range(1, num_moments + 1):
        for lvec in _generate_partitions(k, m):
            coeff = math.factorial(k)
            for x in lvec:
                coeff //= math.factorial(x)
            internal = 1.0
            j = 1
            for i in range(1, m + 1):
                if lvec[i - 1] > 0:
                    internal *= type_moments[lvec[i - 1] - 1, j - 1]
                if i >= z0_cumsum[j - 1]:
                    j += 1
            w_moments[k - 1] += coeff * internal
    return w_moments / (1.0 - q_star)


# --------------------------------------------------------------------------- #
# Full solve
# --------------------------------------------------------------------------- #
def solve(value: dict) -> dict:
    bp = validate_case(value)

    n = bp.n_moments
    # calculate n + 1 moments so error_bounds has the (n+1)th moment available.
    lam, u_norm, moments_full = calculate_moments_generic(bp, n + 1)
    error_moment = moments_full[-1, :]
    moments = moments_full[:-1, :]

    L = error_bounds(bp.epsilon, error_moment, n)
    mu_embed = math.exp(lam * bp.h)
    flow = make_riccati_flow(bp)
    coeffs = moment_coeffs(moments)
    lst_w = construct_lst(coeffs, mu_embed, flow, L, bp.z0, lam, bp.h)

    q1 = calculate_extinction_probs(bp)
    q_star = float(np.prod(q1 ** bp.z0))

    w_cdf_fn = construct_w_cdf_ilst(lst_w, q_star, bp.cme_eta, bp.cme_beta)
    w_cdf = eval_cdf(w_cdf_fn, bp.grid)

    # W moments: aggregate the type moments over the initial condition.
    # (Uses the first five type moments; recompute at num_moments = 6 for headroom.)
    _, _, type_moments_6 = calculate_moments_generic(bp, 6)
    w_moments = compute_w_moments(type_moments_6[:5, :], bp.z0, q_star, num_moments=5)

    return {
        "w_cdf": [float(x) for x in w_cdf],
        "w_moments": [float(x) for x in w_moments],
        "q_star": q_star,
        "lambda": float(lam),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _check_port_provenance(provenance_path: Path) -> None:
    record = json.loads(provenance_path.read_text())
    if record.get("commit") != _PORT_COMMIT:
        raise RuntimeError("port provenance commit mismatch")
    for name, digest in record["source_sha256"].items():
        local = provenance_path.with_name(name)
        if not local.exists():
            continue
        if hashlib.sha256(local.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"port provenance hash mismatch for {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--port-provenance", type=Path)
    args = parser.parse_args()
    if args.port_provenance:
        _check_port_provenance(args.port_provenance)
    value = json.loads(
        args.input.read_text(),
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
    )
    result = solve(value)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "output.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
