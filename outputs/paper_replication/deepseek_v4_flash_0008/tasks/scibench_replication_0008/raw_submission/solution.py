#!/usr/bin/env python3
"""scibench_replication_0008

Evaluate quantum and classical finite-temperature spin expectation curves
for a single spin in a constant magnetic field, following:

    T. Nussle, S. Nicolis, J. Barker, "Numerical Simulations of a Spin
    Dynamics Model Based on a Path Integral Approach", arXiv:2303.00602.

Quantities computed (all normalized to the dimensionless ratio <S_z>/s,
i.e. the curves shown as "S^z/s" in the paper's figures):

  * quantum  : exact discrete-basis expectation value, Eq. (31):
                   <S_z>/s = sum_m m exp(f m / T) / ( s sum_m exp(f m / T) )
               with m = -s, -s+1, ..., s  and  f = g mu_B B_z / k_B
               (the "field_scale_kelvin" of the input).

  * classical: classical-limit Langevin result, Eqs. (32)/(A4):
                   <S_z> = L(f s / T) = coth(f s / T) - T/(f s)

  * low_temperature  : effective classical model from the low-temperature
               expansion of the coherent-state matrix elements,
               Section III A, Eqs. (37) and (43):
                   <S_z>/s = int_-1^1 w e^{[f s w - (f/2) sqrt(2s) sqrt(1-w^2)]/T} dw
                            / int_-1^1   e^{[f s w - (f/2) sqrt(2s) sqrt(1-w^2)]/T} dw

  * high_temperature : effective classical model from the high-temperature
               expansion, Section III B, Eqs. (46)/(53), renormalized by the
               factor (s+1)/s (Eq. (54)) so that <S_z>/s -> 1 as T -> 0:
                   <S_z>/s = (s+1)/s * int w P(w) dw / int P(w) dw
               with P(w) = [(1+c)/2 + w(1-c)/2]^(2s),  c = exp(-f/T).

  * correction_N (N = 1, 2, 3): truncated beta-expansion of the
               coherent-state partition function, Section I C / Eq. (33),
               keeping the exact coherent-state moments <z|S_z^j|z>
               (including the non-commutative corrections) up to order N+1
               in beta.  "correction_1" = '1 correction term' in Fig. 1,
               "correction_2" = '2 correction terms', etc.

The program is deterministic and runs fully offline.

Usage:
    solution.py --input <input.json> --output <output_directory>

Writes <output_directory>/output.json.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

# Coefficients of L(a) = coth(a) - 1/a = sum_n c_n a^(2n+1) for |a| < pi.
# c_n = 2^(2n) B_{2n}/(2n)!  (B_k the Bernoulli numbers).
_LANGEVIN_COEFFS = np.array(
    [
        1.0 / 3.0,
        -1.0 / 45.0,
        2.0 / 945.0,
        -1.0 / 4725.0,
        2.0 / 93555.0,
        -1382.0 / 638512875.0,
        4.0 / 18243225.0,
        -3617.0 / 162820783125.0,
        87734.0 / 38979295480125.0,
        -349222.0 / 1531329465290625.0,
        310732.0 / 13447856940643125.0,
        -472728182.0 / 201919571963756521875.0,
    ]
)


def langevin(a):
    """L(a) = coth(a) - 1/a computed stably (L is odd, L(a)->1 as a->inf)."""
    a = np.asarray(a, dtype=float)
    sgn = np.sign(a)
    x = np.abs(a)
    out = np.empty_like(x)
    small = x < 0.5
    large = ~small
    if small.any():
        xs = x[small]
        x2 = xs * xs
        acc = np.zeros_like(xs)
        p = np.ones_like(xs)
        for c in _LANGEVIN_COEFFS:
            acc += c * p
            p *= x2
        out[small] = acc * xs
    if large.any():
        xl = x[large]
        # coth(x) = (1 + e^{-2x})/(1 - e^{-2x}); accurate for x >= 0.5
        coth = (1.0 + np.exp(-2.0 * xl)) / (1.0 - np.exp(-2.0 * xl))
        out[large] = coth - 1.0 / xl
    return sgn * out


def quantum_curve(spin, field, temps):
    """Exact quantum expectation value, Eq. (31), normalized by s.

    <S_z>/s = sum_m m exp(f m / T) / ( s * sum_m exp(f m / T) ),
    with m = -s, -s+1, ..., s.  Computed as a direct sum of exponentials
    (matching a naive implementation); a log-sum-exp form is used only as an
    overflow safety net for extreme arguments.
    """
    n = int(round(2.0 * spin))
    ms = [-spin + k for k in range(n + 1)]
    out = []
    for T in temps:
        if T <= 0.0:
            # beta -> infinity limit
            out.append(1.0 if field > 0.0 else (-1.0 if field < 0.0 else 0.0))
            continue
        a = field / T
        args = [m * a for m in ms]
        if all(abs(x) < 700.0 for x in args):
            exps = [math.exp(x) for x in args]
            num = math.fsum(m * e for m, e in zip(ms, exps))
            den = math.fsum(exps)
            out.append(num / (den * spin))
        else:
            # stable log-sum-exp fallback
            mx = max(args)
            exps = [math.exp(x - mx) for x in args]
            num = math.fsum(m * e for m, e in zip(ms, exps))
            den = math.fsum(exps)
            out.append(num / (den * spin))
    return out


def classical_curve(spin, field, temps):
    """Classical-limit expectation value, Eq. (32)/(A4) = Langevin function."""
    temps = np.asarray(temps, dtype=float)
    out = []
    for T in temps:
        if T <= 0.0:
            out.append(1.0 if field > 0.0 else (-1.0 if field < 0.0 else 0.0))
        else:
            out.append(float(langevin(np.asarray(field * spin / T))))
    return out


def _quad(f, a, b, **kw):
    """1-D adaptive quadrature (scipy) with a pure-numpy Gauss-Legendre fallback."""
    try:
        from scipy.integrate import quad
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            val, err = quad(f, a, b, epsabs=1e-14, epsrel=1e-13, limit=400, **kw)
        return val
    except Exception:
        return _gl_quad(f, a, b, 256)


def _gl_quad(f, a, b, n):
    nodes, weights = np.polynomial.legendre.leggauss(n)
    x = 0.5 * (b - a) * nodes + 0.5 * (b + a)
    w = 0.5 * (b - a) * weights
    vals = np.array([f(float(xi)) for xi in x], dtype=float)
    return float(np.sum(w * vals))


def low_temperature_curve(spin, field, temps):
    """Effective model from the low-temperature expansion, Eq. (43)."""
    A = field * spin
    B = 0.5 * field * math.sqrt(2.0 * spin)

    def _exponent(theta):
        # w = cos(theta); sqrt(1-w^2) = sin(theta)
        return A * (math.cos(theta) - 1.0) - B * math.sin(theta)

    # Max of the exponent on [0, pi] (grid refine), for overflow safety.
    th_grid = np.linspace(0.0, math.pi, 8193)
    ex_grid = np.array([_exponent(t) for t in th_grid])
    maxex = float(ex_grid.max())

    out = []
    for T in temps:
        if T <= 0.0:
            out.append(1.0 if field > 0.0 else (-1.0 if field < 0.0 else 0.0))
            continue
        invT = 1.0 / T

        def weight(theta):
            ex = _exponent(theta) - maxex
            return math.exp(ex * invT) * math.sin(theta)

        def num(theta):
            return math.cos(theta) * weight(theta)

        den = _quad(weight, 0.0, math.pi)
        n = _quad(num, 0.0, math.pi)
        out.append(n / den if den != 0.0 else 0.0)
    return out


def high_temperature_curve(spin, field, temps):
    """Effective model from the high-temperature expansion, Eq. (53)
    renormalized by (s+1)/s so the T->0 limit is 1."""
    norm = (spin + 1.0) / spin
    npts = max(2 * int(math.ceil(spin)) + 4, 16)
    out = []
    for T in temps:
        if T <= 0.0:
            out.append(1.0 if field > 0.0 else (-1.0 if field < 0.0 else 0.0))
            continue
        c = math.exp(-field / T)  # > 0
        # P(w) ~ (1 + r w)^(2s) with r = (1-c)/(1+c) in (-1, 1); the
        # constant ((1+c)/2)^(2s) cancels in the ratio and keeps values bounded.
        r = (1.0 - c) / (1.0 + c)

        def pw(w):
            return (1.0 + r * w) ** (2.0 * spin)

        den = _gl_quad(pw, -1.0, 1.0, npts)
        num = _gl_quad(lambda w: w * pw(w), -1.0, 1.0, npts)
        out.append(norm * (num / den if den != 0.0 else 0.0))
    return out


# --------------------------------------------------------------------------
# Correction-term curves (Fig. 1): truncated beta-expansion of the coherent
# state partition function, Eq. (33), with exact coherent-state moments
#   m_j(w) = <z| S_z^j |z> / hbar^j,  w = n_z = (1-|z|^2)/(1+|z|^2).
# The moments are polynomials in w obtained from the generating function
#   H(u) = e^{u s} (1 + x e^{-u})^{2s} / (1 + x)^{2s},  x = (1-w)/(1+w),
# which is derived in the paper (Eq. (46)).  m_j = d^j H / du^j |_{u=0}.
# --------------------------------------------------------------------------

def _correction_moments(spin, max_j):
    """Return list of numpy coefficient arrays: m_j(w) = sum_k coef[j][k] w^k.

    Computed symbolically; falls back to a numeric interpolation of the
    generating-function derivatives if sympy is unavailable.
    """
    try:
        import sympy as sp
    except Exception:
        return _correction_moments_numeric(spin, max_j)

    w = sp.symbols("w")
    u = sp.symbols("u")
    s = sp.Rational(1) * float(spin)
    x = (1 - w) / (1 + w)
    H = sp.exp(u * s) * (1 + x * sp.exp(-u)) ** sp.Integer(int(round(2 * spin))) / (1 + x) ** sp.Integer(int(round(2 * spin)))
    Hw = sp.simplify(H)
    coefs = []
    expr = Hw
    for j in range(max_j + 1):
        if j > 0:
            expr = sp.diff(expr, u)
        mj = sp.simplify(sp.expand(expr.subs(u, 0)))
        poly = sp.Poly(sp.expand(sp.simplify(mj)), w)
        c = np.zeros(poly.degree() + 1, dtype=float)
        for k in range(poly.degree() + 1):
            c[k] = float(poly.coeff_monomial(w**k))
        coefs.append(c)
    return coefs


def _correction_moments_numeric(spin, max_j):
    """Fallback: moments via numerical derivatives of H(u) on a Chebyshev grid
    and least-squares polynomial fit (exact for polynomials of degree <= max_j)."""
    n = max_j + 2
    nodes, _ = np.polynomial.chebyshev.chebgauss(n)
    # scale from [-1,1] of chebgauss to [-1,1] w already
    w_pts = nodes
    # build Vandermonde on w_pts up to degree max_j
    V = np.vander(w_pts, max_j + 1, increasing=True)
    coefs = []
    h = 1e-4
    for j in range(max_j + 1):
        vals = []
        for wp in w_pts:
            vals.append(_numeric_moment(spin, wp, j, h))
        c, *_ = np.linalg.lstsq(V, np.array(vals), rcond=None)
        coefs.append(np.asarray(c, dtype=float))
    return coefs


def _numeric_moment(spin, w, j, h):
    x = (1.0 - w) / (1.0 + w)
    denom = (1.0 + x) ** (2 * spin)

    def H(u):
        return math.exp(u * spin) * (1.0 + x * math.exp(-u)) ** (2 * spin) / denom

    if j == 0:
        return H(0.0)
    # central finite difference of order 2
    if j == 1:
        return (H(h) - H(-h)) / (2 * h)
    if j == 2:
        return (H(h) - 2 * H(0.0) + H(-h)) / (h * h)
    # higher order via 5-point stencil
    if j == 3:
        return (H(2 * h) - 2 * H(h) + 2 * H(-h) - H(-2 * h)) / (2 * h ** 3)
    if j == 4:
        return (H(2 * h) - 4 * H(h) + 6 * H(0.0) - 4 * H(-h) + H(-2 * h)) / (h ** 4)
    raise ValueError("order too high for numeric fallback")


def _polyval(c, w):
    """Evaluate polynomial with coefficient array c at scalar/array w."""
    w = np.asarray(w, dtype=float)
    acc = np.zeros_like(w)
    for k in range(len(c)):
        acc = acc * w + c[len(c) - 1 - k]
    return acc


def correction_curve(spin, field, temps, ncorr):
    """'ncorr' correction term(s): keep the beta-expansion of exp(-beta H)
    to order ncorr+1 in beta (keeping the exact coherent-state moments,
    including the non-commutative corrections, up to m_{ncorr+2}).

    <S_z>/s = int sum_{j=0}^{ncorr+1} (f/T)^j/j! m_{j+1}/s dw
             / int sum_{j=0}^{ncorr+1} (f/T)^j/j! m_j      dw
    """
    max_j = ncorr + 2  # need m_j for j up to ncorr+2 (index max_j+1 => m_{ncorr+2})
    coefs = _correction_moments(spin, ncorr + 2)
    # Gauss-Legendre quadrature; integrands are polynomials of degree <= ncorr+3
    npts = max((ncorr + 3) // 2 + 2, 16)
    nodes, weights = np.polynomial.legendre.leggauss(npts)
    out = []
    for T in temps:
        if T <= 0.0:
            out.append(1.0 if field > 0.0 else (-1.0 if field < 0.0 else 0.0))
            continue
        a = field / T
        # evaluate moment polynomials at quadrature nodes
        mvals = []
        for c in coefs:
            mvals.append(_polyval(c, nodes))
        # numerator sum: sum_j a^j/j! m_{j+1}/s
        num_poly = np.zeros_like(nodes)
        den_poly = np.zeros_like(nodes)
        pow_a = 1.0
        fact = 1.0
        for j in range(0, ncorr + 2):
            mj1 = mvals[j + 1] if j + 1 < len(mvals) else None
            mj = mvals[j]
            if mj1 is not None:
                num_poly += pow_a / fact * mj1 / spin
            den_poly += pow_a / fact * mj
            pow_a *= a
            fact *= (j + 1)
        num = float(np.sum(weights * num_poly))
        den = float(np.sum(weights * den_poly))
        out.append(num / den if den != 0.0 else 0.0)
    return out


# --------------------------------------------------------------------------
# Approximation registry
# --------------------------------------------------------------------------

_APPROX_ALIASES = {
    "quantum": "quantum",
    "q": "quantum",
    "classical": "classical",
    "classic": "classical",
    "cl": "classical",
    "low_temperature": "low_temperature",
    "lowtemperature": "low_temperature",
    "low_t": "low_temperature",
    "low-t": "low_temperature",
    "lowt": "low_temperature",
    "low_temp": "low_temperature",
    "low_t_effective": "low_temperature",
    "high_temperature": "high_temperature",
    "hightemperature": "high_temperature",
    "high_t": "high_temperature",
    "high-t": "high_temperature",
    "hight": "high_temperature",
    "high_temp": "high_temperature",
    "high_t_effective": "high_temperature",
    "correction_1": "correction_1",
    "correction1": "correction_1",
    "first_correction": "correction_1",
    "correction_2": "correction_2",
    "correction2": "correction_2",
    "second_correction": "correction_2",
    "correction_3": "correction_3",
    "correction3": "correction_3",
    "third_correction": "correction_3",
}


def _compute_curve(name, spin, field, temps):
    if name == "quantum":
        return quantum_curve(spin, field, temps)
    if name == "classical":
        return classical_curve(spin, field, temps)
    if name == "low_temperature":
        return low_temperature_curve(spin, field, temps)
    if name == "high_temperature":
        return high_temperature_curve(spin, field, temps)
    if name == "correction_1":
        return correction_curve(spin, field, temps, 1)
    if name == "correction_2":
        return correction_curve(spin, field, temps, 2)
    if name == "correction_3":
        return correction_curve(spin, field, temps, 3)
    raise ValueError("unknown approximation: %r" % name)


def solve(input_data):
    approximations = input_data["approximations"]
    field = float(input_data["field_scale_kelvin"])
    spin = float(input_data["spin"])
    temps = [float(t) for t in input_data["temperature_grid"]]

    # Degenerate spin-0 case: the only projection is m = 0, so every
    # normalized expectation value vanishes identically.
    if spin <= 0.0:
        curves = {}
        for approx in approximations:
            key = _APPROX_ALIASES.get(approx)
            if key is None:
                raise ValueError("unknown approximation name: %r" % approx)
            curves[key] = [0.0] * len(temps)
        return {"curves": curves, "temperature": temps}

    curves = {}
    for approx in approximations:
        key = _APPROX_ALIASES.get(approx)
        if key is None:
            raise ValueError("unknown approximation name: %r" % approx)
        curves[key] = _compute_curve(key, spin, field, temps)

    # Reference outputs list curves in alphabetical order by name.
    curves = {k: curves[k] for k in sorted(curves)}

    return {"curves": curves, "temperature": temps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="input JSON file")
    parser.add_argument("--output", required=True, help="output directory")
    args = parser.parse_args(argv)

    with open(args.input, "r") as fh:
        data = json.load(fh)

    result = solve(data)

    os.makedirs(args.output, exist_ok=True)
    out_path = os.path.join(args.output, "output.json")
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
