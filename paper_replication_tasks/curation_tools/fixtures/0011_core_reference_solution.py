#!/usr/bin/env python3
"""Standalone curator reference submission for 0011_core evaluator testing."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import pinvh
from scipy.stats import truncnorm


def solve(value):
    times = np.asarray(value["lag_times"], float)
    counts = np.asarray(value["independent_sample_counts"], float)
    rows = [np.asarray(row, float) for row in value["squared_displacement_samples"]]
    means = np.asarray([row.mean() for row in rows])
    variances = np.asarray([row.var(ddof=1) / count for row, count in zip(rows, counts)])
    first = int(np.flatnonzero(times >= float(value["fit_start"]))[0])
    variances = variances[first:]
    fitted_counts = counts[first:]
    covariance = np.empty((variances.size, variances.size))
    for i in range(variances.size):
        for j in range(i, variances.size):
            covariance[i, j] = covariance[j, i] = variances[i] * fitted_counts[i] / fitted_counts[j]
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    eigenvalues = np.maximum(eigenvalues, eigenvalues[-1] / float(value["condition_limit"]))
    covariance = (eigenvectors * eigenvalues) @ eigenvectors.T
    precision = pinvh(covariance)
    design = np.column_stack((times[first:], np.ones(times.size - first)))
    parameter_covariance = pinvh(design.T @ precision @ design)
    parameter_mean = parameter_covariance @ design.T @ precision @ means[first:]
    slope_mean = float(parameter_mean[0])
    slope_sd = float(np.sqrt(parameter_covariance[0, 0]))
    posterior = truncnorm(-slope_mean / slope_sd, np.inf, loc=slope_mean, scale=slope_sd)
    scale = 1.0 / (2 * int(value["dimension"]))
    return {
        "mean": float(posterior.mean() * scale),
        "variance": float(posterior.var() * scale**2),
        "quantiles": [float(item * scale) for item in posterior.ppf([0.025, 0.5, 0.975])],
    }


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
result = solve(json.loads(Path(args.input).read_text(encoding="utf-8")))
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
(output / "output.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
