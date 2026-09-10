#!/usr/bin/env python3
"""Compute the limiting branching-process distribution described in paper.pdf."""

import argparse
import json
import math
import os

import numpy as np
from scipy.integrate import solve_ivp


def parse_model(data):
    rates = np.asarray(data["lifetimes"], dtype=float)
    m = rates.size
    linear = []
    for i, j, value in data.get("linear_terms", []):
        linear.append((int(i) - 1, int(j) - 1, float(value)))
    quadratic = []
    for i, k, ell, value in data.get("quadratic_terms", []):
        quadratic.append((int(i) - 1, int(k) - 1, int(ell) - 1, float(value)))
    return rates, m, linear, quadratic


def growth_rate_and_mean_vector(mean_matrix):
    matrix = np.asarray(mean_matrix, dtype=float)
    values, vectors = np.linalg.eig(matrix)
    # Perron--Frobenius makes the selected eigenvalue real for valid inputs.
    index = int(np.argmax(values.real))
    lam = float(values[index].real)
    u = np.asarray(vectors[:, index].real, dtype=float)
    if u.sum() < 0:
        u = -u
    u /= u.sum()
    return lam, u


def single_particle_coefficients(rates, m, linear, quadratic, lam, u, max_order):
    """Return E[Wi**n]/n! for every type and n=0,...,max_order."""
    coeff = np.zeros((m, max_order + 1), dtype=float)
    coeff[:, 0] = 1.0
    coeff[:, 1] = u

    linear_by_type = [[] for _ in range(m)]
    quadratic_by_type = [[] for _ in range(m)]
    for item in linear:
        linear_by_type[item[0]].append(item)
    for item in quadratic:
        quadratic_by_type[item[0]].append(item)

    for n in range(2, max_order + 1):
        matrix = np.eye(m, dtype=float)
        rhs = np.zeros(m, dtype=float)
        for i in range(m):
            denominator = rates[i] + n * lam
            for _, j, alpha in linear_by_type[i]:
                matrix[i, j] -= alpha / denominator
            for _, k, ell, beta in quadratic_by_type[i]:
                scaled = beta / denominator
                matrix[i, k] -= scaled
                matrix[i, ell] -= scaled
                rhs[i] += scaled * sum(
                    coeff[k, r] * coeff[ell, n - r] for r in range(1, n)
                )
        coeff[:, n] = np.linalg.solve(matrix, rhs)
    return coeff


def extinction_probability(rates, m, linear, quadratic):
    """Minimal nonnegative fixed point of the continuous-time progeny PGF."""
    deaths = rates.copy()
    linear_by_type = [[] for _ in range(m)]
    quadratic_by_type = [[] for _ in range(m)]
    for i, j, alpha in linear:
        deaths[i] -= alpha
        linear_by_type[i].append((j, alpha))
    for i, k, ell, beta in quadratic:
        deaths[i] -= beta
        quadratic_by_type[i].append((k, ell, beta))

    q = np.zeros(m, dtype=float)
    for _ in range(100000):
        updated = deaths / rates
        for i in range(m):
            for j, alpha in linear_by_type[i]:
                updated[i] += alpha / rates[i] * q[j]
            for k, ell, beta in quadratic_by_type[i]:
                updated[i] += beta / rates[i] * q[k] * q[ell]
        if np.max(np.abs(updated - q)) < 1e-14:
            q = updated
            break
        q = updated
    return q


def aggregate_moment_coefficients(single_coeff, initial, max_order):
    """MGF coefficients of the sum of independent initial lineages."""
    total = np.zeros(max_order + 1, dtype=float)
    total[0] = 1.0
    for i, count in enumerate(initial):
        for _ in range(int(count)):
            total = np.convolve(total, single_coeff[i])[: max_order + 1]
    return total


def solve(data):
    rates, m, linear, quadratic = parse_model(data)
    initial = np.asarray(data["initial_condition"], dtype=int)
    n = int(data["n_moments"])
    epsilon = float(data["taylor_epsilon"])
    step = float(data["embedding_step"])

    lam, u = growth_rate_and_mean_vector(data["mean_matrix"])
    # The Taylor polynomial has degree n and its remainder bound uses moment n+1.
    single = single_particle_coefficients(
        rates, m, linear, quadratic, lam, u, n + 1
    )
    q_types = extinction_probability(rates, m, linear, quadratic)
    q_star = float(np.prod(np.power(q_types, initial)))
    aggregate = aggregate_moment_coefficients(single, initial, 5)
    conditional_moments = [
        float(math.factorial(k) * aggregate[k] / (1.0 - q_star))
        for k in range(1, 6)
    ]

    # Radius on which all conditional LST Taylor polynomials meet the error bound.
    radius = float((epsilon / np.max(single[:, n + 1])) ** (1.0 / (n + 1)))

    deaths = rates.copy()
    for i, _, alpha in linear:
        deaths[i] -= alpha
    for i, _, _, beta in quadratic:
        deaths[i] -= beta

    def pgf_flow_rhs(_time, y):
        dy = deaths.astype(complex)
        for i, j, alpha in linear:
            dy[i] += alpha * y[j]
        for i, k, ell, beta in quadratic:
            dy[i] += beta * y[k] * y[ell]
        dy -= rates * y
        return dy

    def component_lst(theta):
        magnitude = abs(theta)
        if magnitude <= radius:
            iterations = 0
        else:
            iterations = int(math.ceil(math.log(magnitude / radius) / (lam * step))) + 1
        reduced = theta * math.exp(-lam * step * iterations)
        # Evaluate each Taylor polynomial by Horner's rule.
        y = single[:, n].astype(complex)
        for order in range(n - 1, -1, -1):
            y = y * (-reduced) + single[:, order]
        if iterations:
            # Composition of the embedded PGF is the autonomous PGF flow over
            # the corresponding total time.
            solution = solve_ivp(
                pgf_flow_rhs,
                (0.0, iterations * step),
                y,
                method="DOP853",
                rtol=2.3e-14,
                atol=1e-15,
            )
            y = solution.y[:, -1]
        return y

    cme = data["cme_coefficients"]
    beta = np.asarray(cme["beta_real"], dtype=float) + 1j * np.asarray(
        cme["beta_imag"], dtype=float
    )
    eta = np.asarray(cme["eta_real"], dtype=float) + 1j * np.asarray(
        cme["eta_imag"], dtype=float
    )

    cdf = []
    for w in data["cdf_grid"]:
        w = float(w)
        if w == 0.0:
            cdf.append(q_star)
            continue
        terms = []
        for b in beta:
            components = component_lst(b / w)
            phi = np.prod(np.power(components, initial))
            terms.append(phi)
        value = float(np.real(np.sum((eta / beta) * np.asarray(terms))))
        cdf.append(value)

    return {
        "lambda": lam,
        "q_star": q_star,
        "w_cdf": cdf,
        "w_moments": conditional_moments,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.input, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    result = solve(data)
    os.makedirs(args.output, exist_ok=True)
    with open(os.path.join(args.output, "output.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
