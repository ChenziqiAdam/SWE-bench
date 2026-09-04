#!/usr/bin/env python3
"""Independent analytical audit of the paper's truncated Gaussian posterior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import pinvh
from scipy.stats import truncnorm

from kinisi_core_common import validate_case, validate_output


def covariance_from_paper(variances: np.ndarray, counts: np.ndarray) -> np.ndarray:
    size = variances.size
    result = np.empty((size, size), dtype=float)
    for i in range(size):
        for j in range(i, size):
            result[i, j] = result[j, i] = variances[i] * counts[i] / counts[j]
    return result


def minimum_eigenvalue_recondition(matrix: np.ndarray, condition_limit: float) -> np.ndarray:
    # The symmetric eigensolver orders eigenvalues. Flooring at lambda_max/kappa
    # is the minimum-eigenvalue method described in the cited reconditioning paper.
    values, vectors = np.linalg.eigh(matrix)
    floor = values[-1] / condition_limit
    values = np.maximum(values, floor)
    result = (vectors * values) @ vectors.T
    return (result + result.T) / 2


def solve(payload: dict) -> dict:
    case = validate_case(payload)
    means = np.asarray([np.mean(row) for row in case["samples"]])
    variances = np.asarray([
        np.var(row, ddof=1) / count for row, count in zip(case["samples"], case["counts"])
    ])
    first = int(np.flatnonzero(case["lag_times"] >= case["fit_start"])[0])
    covariance = covariance_from_paper(variances[first:], case["counts"][first:])
    covariance = minimum_eigenvalue_recondition(covariance, case["condition_limit"])
    precision = pinvh(covariance)
    x = np.column_stack((case["lag_times"][first:], np.ones(means.size - first)))
    parameter_covariance = pinvh(x.T @ precision @ x)
    parameter_mean = parameter_covariance @ x.T @ precision @ means[first:]
    slope_mean = float(parameter_mean[0])
    slope_sd = float(np.sqrt(parameter_covariance[0, 0]))
    lower = (0.0 - slope_mean) / slope_sd
    distribution = truncnorm(lower, np.inf, loc=slope_mean, scale=slope_sd)
    scale = 1.0 / (2 * case["dimension"])
    result = {
        "mean": float(distribution.mean() * scale),
        "variance": float(distribution.var() * scale**2),
        "quantiles": [float(x * scale) for x in distribution.ppf([0.025, 0.5, 0.975])],
    }
    return validate_output(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = solve(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
