#!/usr/bin/env python3
"""Maximum-likelihood spatial seemingly unrelated regression (SUR-SLM)."""

import argparse
import json
import os

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.optimize._numdiff import approx_derivative


def parameter_map(n_equations, n_columns, shared_columns):
    """Map equation coefficients to the minimally restricted parameter vector."""
    shared_columns = set(shared_columns)
    shared_locations = {}
    mapping = np.empty((n_equations, n_columns), dtype=int)
    cursor = 0
    for equation in range(n_equations):
        for column in range(n_columns):
            if column in shared_columns:
                if column not in shared_locations:
                    shared_locations[column] = cursor
                    cursor += 1
                mapping[equation, column] = shared_locations[column]
            else:
                mapping[equation, column] = cursor
                cursor += 1
    return mapping, cursor


def fit_spatial_sur(w, x, y, shared_columns):
    t_count, n, p = x.shape
    mapping, beta_count = parameter_map(t_count, p, shared_columns)
    wy = np.asarray([w @ y[t] for t in range(t_count)])

    # The determinant and its derivative are cheap and particularly stable when
    # evaluated from W's eigenvalues. Complex eigenvalues occur in conjugate pairs.
    eig = np.linalg.eigvals(w)

    def log_jacobian(rho):
        values = 1.0 - rho * eig
        return float(np.real(np.log(values).sum()))

    def jacobian_trace(rho):
        return float(np.real((eig / (1.0 - rho * eig)).sum()))

    def unpack(theta):
        rho = theta[:t_count]
        beta_unique = theta[t_count:]
        return rho, beta_unique[mapping]

    def objective_and_gradient(theta):
        rho, beta = unpack(theta)
        residuals = np.empty((n, t_count))
        for t in range(t_count):
            residuals[:, t] = y[t] - rho[t] * wy[t] - x[t] @ beta[t]

        sigma = residuals.T @ residuals / n
        sign, logdet_sigma = np.linalg.slogdet(sigma)
        if sign <= 0 or not np.isfinite(logdet_sigma):
            return 1.0e100, np.zeros_like(theta)
        sigma_inv = np.linalg.inv(sigma)
        weighted_residuals = residuals @ sigma_inv

        value = 0.5 * n * logdet_sigma
        gradient = np.zeros_like(theta)
        for t in range(t_count):
            value -= log_jacobian(rho[t])
            gradient[t] = -wy[t] @ weighted_residuals[:, t] + jacobian_trace(rho[t])
            contributions = -(x[t].T @ weighted_residuals[:, t])
            np.add.at(gradient[t_count:], mapping[t], contributions)
        return value, gradient

    # Equation-wise spatial ML provides a much better starting point than either
    # zero or endogenous least squares, especially for strongly spatial samples.
    rho_initial = np.zeros(t_count)
    beta_initial_matrix = np.zeros((t_count, p))
    for t in range(t_count):
        def equation_objective(rho):
            transformed = y[t] - rho * wy[t]
            beta_t = np.linalg.lstsq(x[t], transformed, rcond=None)[0]
            error = transformed - x[t] @ beta_t
            variance = max(float(error @ error / n), np.finfo(float).tiny)
            return 0.5 * n * np.log(variance) - log_jacobian(rho)

        scalar_fit = minimize_scalar(
            equation_objective,
            bounds=(-0.995, 0.995),
            method="bounded",
            options={"xatol": 1e-12, "maxiter": 500},
        )
        rho_initial[t] = scalar_fit.x
        beta_initial_matrix[t] = np.linalg.lstsq(
            x[t], y[t] - rho_initial[t] * wy[t], rcond=None
        )[0]

    beta_initial = np.zeros(beta_count)
    beta_hits = np.zeros(beta_count)
    for t in range(t_count):
        np.add.at(beta_initial, mapping[t], beta_initial_matrix[t])
        np.add.at(beta_hits, mapping[t], 1.0)
    beta_initial /= beta_hits

    starts = [
        np.r_[rho_initial, beta_initial],
        np.r_[np.zeros(t_count), beta_initial],
    ]
    fits = []
    bounds = [(-0.999, 0.999)] * t_count + [(None, None)] * beta_count
    for start in starts:
        fit = minimize(
            objective_and_gradient,
            start,
            method="L-BFGS-B",
            jac=True,
            bounds=bounds,
            options={"ftol": 1e-14, "gtol": 1e-9, "maxiter": 5000, "maxls": 50},
        )
        fits.append(fit)
    fit = min(fits, key=lambda result: result.fun)
    theta = fit.x
    rho, beta = unpack(theta)

    # The covariance of the restricted estimates is the inverse observed
    # information of the concentrated Gaussian likelihood.
    def gradient_only(point):
        return objective_and_gradient(point)[1]

    hessian = approx_derivative(
        gradient_only, theta, method="3-point", rel_step=2e-5
    )
    hessian = 0.5 * (hessian + hessian.T)
    covariance = np.linalg.pinv(hessian, rcond=1e-10)
    variances = np.maximum(np.diag(covariance), 0.0)
    standard_errors = np.sqrt(variances)
    rho_se = standard_errors[:t_count]
    beta_se = standard_errors[t_count:][mapping]

    return rho, beta, rho_se, beta_se


def squared_correlation(a, b):
    a = np.asarray(a, dtype=float).ravel()
    b = np.asarray(b, dtype=float).ravel()
    ac = a - a.mean()
    bc = b - b.mean()
    denominator = np.sqrt((ac @ ac) * (bc @ bc))
    if denominator == 0.0:
        return 0.0
    return float((ac @ bc / denominator) ** 2)


def solve(data):
    w = np.asarray(data["w"], dtype=float)
    x = np.asarray(data["x"], dtype=float)
    y = np.asarray(data["y"], dtype=float)
    shared = [int(column) for column in data.get("shared_beta_columns", [])]

    rho, beta, rho_se, beta_se = fit_spatial_sur(w, x, y, shared)
    t_count, n, p = x.shape

    direct = np.empty((t_count, p - 1))
    indirect = np.empty_like(direct)
    total = np.empty_like(direct)
    fitted = np.empty_like(y)
    identity = np.eye(n)
    for t in range(t_count):
        multiplier = np.linalg.inv(identity - rho[t] * w)
        direct_multiplier = float(np.trace(multiplier) / n)
        total_multiplier = float(multiplier.sum() / n)
        direct[t] = direct_multiplier * beta[t, 1:]
        total[t] = total_multiplier * beta[t, 1:]
        indirect[t] = total[t] - direct[t]
        fitted[t] = rho[t] * (w @ y[t]) + x[t] @ beta[t]

    r2_by_equation = [squared_correlation(y[t], fitted[t]) for t in range(t_count)]
    pooled_r2 = squared_correlation(y, fitted)

    return {
        "beta": beta.tolist(),
        "beta_standard_errors": beta_se.tolist(),
        "direct_effects": direct.tolist(),
        "indirect_effects": indirect.tolist(),
        "pooled_r2": pooled_r2,
        "r2_by_equation": r2_by_equation,
        "rho": rho.tolist(),
        "rho_standard_errors": rho_se.tolist(),
        "total_effects": total.tolist(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    result = solve(data)
    os.makedirs(args.output, exist_ok=True)
    output_path = os.path.join(args.output, "output.json")
    with open(output_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
