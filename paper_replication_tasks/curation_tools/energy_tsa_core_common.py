"""Shared numeric contract and deterministic aggregation for task 0018_core."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import cut_tree, linkage

TASK_ID = "scibench_replication_0018_core"


def validate_case(case: dict[str, Any]) -> tuple[np.ndarray, int, float, int]:
    if not isinstance(case, dict) or set(case) != {"x", "n", "p", "q"}:
        raise ValueError("input must contain exactly x, n, p, q")
    x = np.asarray(case["x"], dtype=float)
    if x.ndim != 3 or x.shape[1:] != (24, 6):
        raise ValueError("x must have shape [days,24,6]")
    if x.shape[0] < 4 or x.shape[0] > 366 or x.size > 366 * 24 * 6:
        raise ValueError("unsupported number of days")
    if not np.isfinite(x).all() or (x < 0).any():
        raise ValueError("x must be finite and nonnegative")
    n, p, q = case["n"], case["p"], case["q"]
    if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n < x.shape[0]:
        raise ValueError("n must be an integer in [2, days)")
    if isinstance(q, bool) or not isinstance(q, int) or q not in (0, 1, 2):
        raise ValueError("q must be 0, 1, or 2")
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not np.isfinite(p) or not 0 <= p < 0.5:
        raise ValueError("p must be finite and in [0,0.5)")
    return x, n, float(p), q


def normalize_hourly(values: np.ndarray) -> np.ndarray:
    """Paper z-transform, including its constant-column zero convention."""
    # pandas 1.2 reduces its column-major float block row-wise. Keeping that
    # memory/reduction order avoids ulp-level medoid changes on newer NumPy.
    block = np.array(values.reshape(-1, values.shape[-1]).T, dtype=float, order="C", copy=True)
    mean = block.sum(axis=1, dtype=np.float64) / block.shape[1]
    squared = np.square(block - mean[:, None])
    std = np.sqrt(squared.sum(axis=1, dtype=np.float64) / (block.shape[1] - 1))
    variable = std >= 1e-5
    block[~variable] = 0.0
    block[variable] = (block[variable] - mean[variable, None]) / std[variable, None]
    return block.T.reshape(values.shape)


def daily_vectors(values: np.ndarray) -> pd.DataFrame:
    """Build daily vectors with the pinned oracle's pandas operation order."""
    normalized = normalize_hourly(values).reshape(-1, values.shape[-1])
    columns = [f"{column}_{hour:02d}" for column in range(values.shape[-1]) for hour in range(24)]
    daily = pd.DataFrame(index=np.arange(values.shape[0]), columns=columns, dtype=float)
    for column in range(values.shape[-1]):
        daily.iloc[:, 24 * column:24 * (column + 1)] = normalized[:, column].reshape(values.shape[0], 24)
    return daily


def _ward_labels(vectors: np.ndarray | pd.DataFrame, count: int) -> np.ndarray:
    if count == 1:
        return np.zeros(vectors.shape[0], dtype=int)
    # scipy's Ward implementation is deterministic and independent of sklearn label numbering.
    labels = cut_tree(linkage(vectors, method="ward", metric="euclidean"),
                      n_clusters=[count]).reshape(-1).astype(int)
    if np.unique(labels).size != count:
        raise ValueError("Ward clustering did not produce the requested representative budget")
    return labels


def _canonical(labels: np.ndarray) -> np.ndarray:
    mapping: dict[int, int] = {}
    return np.asarray([mapping.setdefault(int(label), len(mapping)) for label in labels], dtype=int)


def medoids(vectors: np.ndarray | pd.DataFrame, labels: np.ndarray) -> np.ndarray:
    out = []
    for label in range(int(labels.max()) + 1):
        idx = np.flatnonzero(labels == label)
        frame = vectors.iloc[idx] if isinstance(vectors, pd.DataFrame) else pd.DataFrame(vectors[idx], index=idx)
        distance = frame.subtract(frame.mean()).pow(2).sum(axis=1)
        out.append(int(distance.idxmin()))
    return np.asarray(out, dtype=int)


def aggregate(
    x: np.ndarray,
    n: int,
    importance: np.ndarray | None = None,
    p: float = 0.0,
    operation: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return reconstructed series, canonical labels, source-day medoids and weights."""
    features = x if operation is None else np.concatenate((x, operation), axis=2)
    vectors = daily_vectors(features)
    days = x.shape[0]
    extreme = np.zeros(days, dtype=bool)
    extreme_clusters = 0
    if importance is not None and p > 0:
        count = min(days, int(round(p * days)))
        if count:
            order = np.lexsort((np.arange(days), -np.asarray(importance, dtype=float)))
            chosen = order[:count]
            # Unserved-energy importance only considers days with actual unserved energy.
            chosen = chosen[np.asarray(importance)[chosen] > 0] if operation is None else chosen
            extreme[chosen] = True
            extreme_clusters = min(int(round(0.5 * n)), int(extreme.sum()))
    regular_clusters = n - extreme_clusters
    if regular_clusters > int((~extreme).sum()):
        shift = regular_clusters - int((~extreme).sum())
        extreme_clusters += shift
        regular_clusters -= shift
    labels = np.empty(days, dtype=int)
    if extreme_clusters:
        labels[extreme] = _ward_labels(vectors[extreme], extreme_clusters)
    labels[~extreme] = _ward_labels(vectors[~extreme], regular_clusters) + extreme_clusters
    labels = _canonical(labels)
    reps = medoids(vectors, labels)
    weights = np.bincount(labels, minlength=n).astype(int)
    reconstructed = x[reps[labels]]
    return reconstructed, labels, reps, weights
