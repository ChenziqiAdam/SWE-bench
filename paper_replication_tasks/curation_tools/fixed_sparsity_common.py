"""Shared case construction for the fixed-sparsity curator implementations."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict) or set(case) != {"mode", "seed", "experiments"}:
        raise ValueError("case fields differ")
    if case["mode"] not in {"curves", "hard_coloring"}:
        raise ValueError("invalid mode")
    seed = case["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("invalid MT19937 seed")
    experiments = case["experiments"]
    if not isinstance(experiments, list) or not experiments:
        raise ValueError("experiments must be nonempty")
    clean = {"mode": case["mode"], "seed": seed, "experiments": []}
    if case["mode"] == "hard_coloring":
        for row in experiments:
            if not isinstance(row, dict) or set(row) != {"label", "k"}:
                raise ValueError("hard-coloring fields differ")
            k = row["k"]
            if isinstance(k, bool) or not isinstance(k, int) or not 2 <= k <= 40:
                raise ValueError("invalid k")
            clean["experiments"].append({"label": str(row["label"]), "k": k})
        return clean
    required = {"label", "n", "matrix", "pattern", "pattern_parameters", "matvec_counts", "trials"}
    for row in experiments:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("curve fields differ")
        n, trials = row["n"], row["trials"]
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (n, trials)) or not 3 <= n <= 1000 or not 1 <= trials <= 100:
            raise ValueError("invalid curve size")
        if row["matrix"] not in {"tridiagonal_inverse", "trefethen_inverse", "random_dense", "random_sparse"}:
            raise ValueError("invalid matrix")
        if row["pattern"] not in {"banded", "power_bands", "irregular", "nonuniform", "matrix_support"}:
            raise ValueError("invalid pattern")
        counts = row["matvec_counts"]
        if not isinstance(counts, list) or not counts or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 or x > 2000 for x in counts):
            raise ValueError("invalid matvec counts")
        parameters = row["pattern_parameters"]
        if not isinstance(parameters, list) or not parameters or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in parameters):
            raise ValueError("invalid pattern parameters")
        clean["experiments"].append({**row, "label": str(row["label"])})
    return clean


def primes(n: int) -> np.ndarray:
    values: list[int] = []
    candidate = 2
    while len(values) < n:
        if all(candidate % divisor for divisor in range(2, math.isqrt(candidate) + 1)):
            values.append(candidate)
        candidate += 1
    return np.asarray(values, dtype=float)


def matrix_for(spec: dict[str, Any], rng: np.random.RandomState) -> np.ndarray:
    n, kind = spec["n"], spec["matrix"]
    if kind == "tridiagonal_inverse":
        base = np.diag(np.full(n, 4.0)) + np.diag(np.full(n - 1, -1.0), 1) + np.diag(np.full(n - 1, -1.0), -1)
        value = np.linalg.inv(base)
    elif kind == "trefethen_inverse":
        base = np.diag(primes(n))
        for level in range(1, int(np.log2(n)) + 1):
            offset = 2**level
            if offset < n:
                base += np.diag(np.ones(n - offset), offset) + np.diag(np.ones(n - offset), -offset)
        value = np.linalg.inv(base)
    elif kind == "random_dense":
        value = rng.normal(size=(n, n))
    else:
        width = max(1, spec["pattern_parameters"][0])
        value = np.zeros((n, n))
        for i in range(n):
            columns = rng.choice(n, size=min(width, n), replace=False)
            value[i, columns] = rng.normal(size=columns.size)
    norm = np.linalg.norm(value)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("invalid generated matrix")
    return value / norm


def patterns(spec: dict[str, Any], rng: np.random.RandomState, matrix: np.ndarray) -> list[tuple[int, np.ndarray]]:
    n, kind = spec["n"], spec["pattern"]
    result = []
    for parameter in spec["pattern_parameters"]:
        mask = np.zeros((n, n), dtype=bool)
        if kind == "banded":
            for offset in range(parameter + 1):
                mask += np.diag(np.ones(n - offset, dtype=bool), offset)
                if offset:
                    mask += np.diag(np.ones(n - offset, dtype=bool), -offset)
        elif kind == "power_bands":
            for level in range(int(np.log2(n)) + 1):
                center = 2**level
                for offset in range(max(0, center - parameter), min(center + parameter, n - 1) + 1):
                    mask += np.diag(np.ones(n - offset, dtype=bool), offset)
                    if offset:
                        mask += np.diag(np.ones(n - offset, dtype=bool), -offset)
        elif kind == "irregular":
            for i in range(n):
                mask[i, rng.choice(n, size=min(parameter, n), replace=False)] = True
        elif kind == "nonuniform":
            for i in range(n):
                width = 1 + (i * max(parameter - 1, 0)) // max(n - 1, 1)
                mask[i, rng.choice(n, size=min(width, n), replace=False)] = True
        else:
            mask = matrix != 0
        result.append((parameter, mask))
    return result


def hard_coloring(k: int) -> dict[str, int]:
    dimension = k * k
    mask = np.zeros((dimension, dimension), dtype=bool)
    for p in range(k):
        for q in range(k):
            for i in range(k):
                for j in range(k):
                    if i == q or j == p:
                        mask[p * k + i, q * k + j] = True
    return {"k": k, "dimension": dimension, "row_sparsity": int(mask.sum(axis=1).max()),
            "column_sparsity": int(mask.sum(axis=0).max()), "coloring_matvecs": dimension,
            "gaussian_exact_recovery_threshold": int(mask.sum(axis=1).max())}
