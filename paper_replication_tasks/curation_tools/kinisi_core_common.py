"""Shared JSON validation for the provisional 0011 core contract."""

from __future__ import annotations

from typing import Any

import numpy as np


REQUIRED = {
    "lag_times",
    "squared_displacement_samples",
    "independent_sample_counts",
    "dimension",
    "fit_start",
    "condition_limit",
    "mcmc_seed",
}
OUTPUT_KEYS = {"mean", "variance", "quantiles"}


def validate_case(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != REQUIRED:
        raise ValueError("input fields do not match the contract")
    times = np.asarray(value["lag_times"], dtype=float)
    counts = np.asarray(value["independent_sample_counts"], dtype=float)
    samples = value["squared_displacement_samples"]
    if times.ndim != 1 or times.size < 3 or np.any(~np.isfinite(times)) or np.any(np.diff(times) <= 0):
        raise ValueError("lag_times must be finite, increasing, and contain at least three values")
    if counts.shape != times.shape or np.any(~np.isfinite(counts)) or np.any(counts <= 1):
        raise ValueError("independent_sample_counts must be finite and greater than one")
    if not isinstance(samples, list) or len(samples) != times.size:
        raise ValueError("one sample vector is required per lag")
    checked = []
    for row in samples:
        array = np.asarray(row, dtype=float)
        if array.ndim != 1 or array.size < 2 or np.any(~np.isfinite(array)) or np.any(array < 0):
            raise ValueError("squared-displacement samples must be finite nonnegative vectors")
        checked.append(array)
    dimension = value["dimension"]
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension not in (1, 2, 3):
        raise ValueError("dimension must be 1, 2, or 3")
    fit_start = float(value["fit_start"])
    condition = float(value["condition_limit"])
    if not np.isfinite(fit_start) or not times[0] <= fit_start <= times[-3]:
        raise ValueError("fit_start must leave at least three lag points")
    if not np.isfinite(condition) or condition <= 1:
        raise ValueError("condition_limit must exceed one")
    seed = value["mcmc_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("mcmc_seed must be a uint32 integer")
    return {
        "lag_times": times,
        "samples": checked,
        "counts": counts,
        "dimension": dimension,
        "fit_start": fit_start,
        "condition_limit": condition,
        "mcmc_seed": seed,
    }


def summarize(samples: np.ndarray) -> dict:
    array = np.asarray(samples, dtype=float)
    if array.ndim != 1 or array.size < 2 or np.any(~np.isfinite(array)) or np.any(array < 0):
        raise ValueError("posterior samples are invalid")
    quantiles = np.quantile(array, [0.025, 0.5, 0.975])
    return {
        "mean": float(np.mean(array)),
        "variance": float(np.var(array, ddof=1)),
        "quantiles": [float(x) for x in quantiles],
    }


def validate_output(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != OUTPUT_KEYS:
        raise ValueError("output fields do not match the contract")
    vector = np.asarray([value["mean"], value["variance"], *value["quantiles"]], dtype=float)
    if vector.shape != (5,) or np.any(~np.isfinite(vector)) or np.any(vector < 0):
        raise ValueError("output values must be finite and nonnegative")
    if not vector[2] <= vector[3] <= vector[4]:
        raise ValueError("quantiles must be ordered")
    return value
