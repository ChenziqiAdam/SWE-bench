#!/usr/bin/env python3
"""Compute the limiting branching-process distribution described in paper.pdf."""

import argparse
import json
import math
import os

import numpy as np
from scipy.integrate import solve_ivp
from scipy.special import gammaln


def dominant_eigenpair(mean_matrix):
    """Return the Perron root and the paper's sum-normalized right eigenvector."""
    values, vectors = np.linalg.eig(mean_matrix)
    index = int(np.argmax(values.real))
    lam = float(values[index].real)
    u = np.real_if_close(vectors[:, index]).real
    # A Metzler irreducible matrix has a consistently-signed Perron vector.
    if u[np.argmax(np.abs(u))] < 0:
        u = -u
    u = u / np.sum(u)
    return lam, u


def event_tables(data, dimension):
    linear = [
        (int(i) - 1, int(j) - 1, float(rate))
        for i, j, rate in data["linear_terms"]
    ]
    quadratic = [
        (int(i) - 1, int(k) - 1, int(l) - 1, float(rate))
        for i, k, l, rate in data["quadratic_terms"]
    ]

    rates = np.asarray(data["lifetimes"], dtype=float)
    if rates.shape != (dimension,):
        raise ValueError("lifetimes must have one entry per type")

    # The residual event rate is death with no offspring (nu_i in equation 29).
    death = rates.copy()
    for i, _j, rate in linear:
        death[i] -= rate
    for i, _k, _l, rate in quadratic:
        death[i] -= rate
    return rates, death, linear, quadratic


def component_moments(lam, u, rates, linear, quadratic, highest_order):
    """Recursively solve equation (36) for each single-type process."""
    dimension = len(rates)
    moments = np.zeros((highest_order + 1, dimension), dtype=float)
    moments[0, :] = 1.0
    moments[1, :] = u

    for order in range(2, highest_order + 1):
        system = np.eye(dimension, dtype=float)
        rhs = np.zeros(dimension, dtype=float)

        for i, j, rate in linear:
            system[i, j] -= rate / (rates[i] + order * lam)

        for i, k, l, rate in quadratic:
            scaled_rate = rate / (rates[i] + order * lam)
            system[i, k] -= scaled_rate
            system[i, l] -= scaled_rate
            convolution = 0.0
            for r in range(1, order):
                convolution += (
                    math.comb(order, r)
                    * moments[r, k]
                    * moments[order - r, l]
                )
            rhs[i] += scaled_rate * convolution

        moments[order, :] = np.linalg.solve(system, rhs)

    return moments


def extinction_probabilities(rates, death, linear, quadratic):
    """Find the minimal fixed point of the progeny PGF by monotone iteration."""
    dimension = len(rates)
    q = np.zeros(dimension, dtype=float)

    # Starting at zero selects the minimal nonnegative solution, unlike a generic
    # root finder (which can converge to the ever-present solution q = 1).
    for _ in range(1_000_000):
        updated = death / rates
        for i, j, rate in linear:
            updated[i] += (rate / rates[i]) * q[j]
        for i, k, l, rate in quadratic:
            updated[i] += (rate / rates[i]) * q[k] * q[l]
        updated = np.clip(updated, 0.0, 1.0)
        if np.max(np.abs(updated - q)) <= 1e-14:
            return updated
        q = updated

    # Extremely near-critical inputs can converge only linearly and very slowly.
    # The last monotone iterate remains the correct side of the minimal solution.
    return q


def total_first_moments(component_moments, initial, count):
    """MGF-series multiplication for a sum of independent initial lineages."""
    series = np.array([1.0])
    for type_index, number in enumerate(initial):
        lineage = np.array(
            [
                component_moments[k, type_index] / math.factorial(k)
                for k in range(count + 1)
            ],
            dtype=float,
        )
        for _ in range(int(number)):
            series = np.convolve(series, lineage)[: count + 1]

    return np.array(
        [series[k] * math.factorial(k) for k in range(1, count + 1)],
        dtype=float,
    )


def make_laplace_transform(
    lam,
    rates,
    death,
    linear,
    quadratic,
    moments,
    expansion_order,
    epsilon,
    embedding_step,
    initial,
):
    """Build Algorithm 1's Taylor/embedded-process LST evaluator."""
    largest_next_moment = float(np.max(moments[expansion_order + 1, :]))
    log_radius = (
        gammaln(expansion_order + 2)
        + math.log(epsilon)
        - math.log(largest_next_moment)
    ) / (expansion_order + 1)
    radius = math.exp(log_radius)

    # Coefficients of each component LST around zero, in ascending powers.
    coefficients = np.empty((expansion_order + 1, len(rates)), dtype=float)
    factorial = 1.0
    sign = 1.0
    for k in range(expansion_order + 1):
        if k:
            factorial *= k
            sign = -sign
        coefficients[k, :] = sign * moments[k, :] / factorial

    def embedded_rhs(_time, state):
        # a_i(f_i(state)-state), with divisions in f_i cancelled.
        derivative = death.astype(np.complex128)
        for i, j, rate in linear:
            derivative[i] += rate * state[j]
        for i, k, l, rate in quadratic:
            derivative[i] += rate * state[k] * state[l]
        derivative -= rates * state
        return derivative

    def laplace(theta):
        ratio = abs(theta) / radius
        if ratio <= 1.0:
            iterations = 0
        else:
            iterations = max(
                0,
                int(math.ceil(math.log(ratio) / (lam * embedding_step))),
            )

        reduced_theta = theta * math.exp(-lam * embedding_step * iterations)

        # Horner evaluation of equation (17).
        state = coefficients[expansion_order, :].astype(np.complex128)
        for k in range(expansion_order - 1, -1, -1):
            state = state * reduced_theta + coefficients[k, :]

        # Each integration evaluates the embedded progeny PGF once. Repetition is
        # equation (22); tight tolerances keep CME cancellation numerically stable.
        for _ in range(iterations):
            state = solve_ivp(
                embedded_rhs,
                (0.0, embedding_step),
                state,
                method="DOP853",
                rtol=1e-11,
                atol=1e-13,
            ).y[:, -1]

        return np.prod(np.power(state, initial))

    return laplace


def solve(data):
    initial = np.asarray(data["initial_condition"], dtype=int)
    dimension = len(initial)
    mean_matrix = np.asarray(data["mean_matrix"], dtype=float)
    if mean_matrix.shape != (dimension, dimension):
        raise ValueError("mean_matrix shape does not match initial_condition")

    lam, u = dominant_eigenpair(mean_matrix)
    if lam <= 0.0:
        raise ValueError("the method requires a super-critical process (lambda > 0)")

    rates, death, linear, quadratic = event_tables(data, dimension)
    expansion_order = int(data["n_moments"])
    moments = component_moments(
        lam,
        u,
        rates,
        linear,
        quadratic,
        max(expansion_order + 1, 5),
    )

    q = extinction_probabilities(rates, death, linear, quadratic)
    q_star = float(np.prod(np.power(q, initial)))

    raw_total_moments = total_first_moments(moments, initial, 5)
    survival_probability = 1.0 - q_star
    if survival_probability <= 0.0:
        conditional_moments = np.full(5, float("nan"))
    else:
        conditional_moments = raw_total_moments / survival_probability

    laplace = make_laplace_transform(
        lam,
        rates,
        death,
        linear,
        quadratic,
        moments,
        expansion_order,
        float(data["taylor_epsilon"]),
        float(data["embedding_step"]),
        initial,
    )

    cme = data["cme_coefficients"]
    beta = np.asarray(cme["beta_real"], dtype=float) + 1j * np.asarray(
        cme["beta_imag"], dtype=float
    )
    eta = np.asarray(cme["eta_real"], dtype=float) + 1j * np.asarray(
        cme["eta_imag"], dtype=float
    )
    if beta.shape != eta.shape:
        raise ValueError("CME beta and eta arrays must have equal lengths")

    cdf = []
    for w in data["cdf_grid"]:
        w = float(w)
        if w == 0.0:
            value = q_star
        elif w < 0.0:
            value = 0.0
        else:
            value = float(
                np.real(
                    np.sum(
                        [
                            eta[j] * laplace(beta[j] / w) / beta[j]
                            for j in range(len(beta))
                        ]
                    )
                )
            )
            # Finite-term inverse Laplace formulae can overshoot slightly.
            value = min(1.0, max(q_star, value))
        cdf.append(value)

    return {
        "lambda": lam,
        "q_star": q_star,
        "w_cdf": cdf,
        "w_moments": conditional_moments.tolist(),
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
    output_path = os.path.join(args.output, "output.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
