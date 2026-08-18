#!/usr/bin/env python3
"""Pinned-notebook adapter for task 0014; the scientific kernels are executed verbatim."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from numpy.linalg import inv, norm

OUTPUT_KEYS = (
    "epsilon_1", "epsilon_2", "forward_error_mean",
    "forward_simplified_expression", "forward_full_bound",
    "backward_error_mean", "backward_simplified_expression", "backward_full_bound",
)


def _matrix(value: Any, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric matrix") from exc
    if result.ndim != 2 or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite matrix")
    return result


def _invertible(value: np.ndarray, name: str) -> None:
    if value.shape[0] != value.shape[1] or np.linalg.matrix_rank(value) != value.shape[0]:
        raise ValueError(f"{name} must be invertible")


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict) or case.get("mode") not in {"point", "sweep"}:
        raise ValueError("mode must be point or sweep")
    if case["mode"] == "point":
        required = {"mode", "A", "U", "V", "E1", "E2"}
        if set(case) != required:
            raise ValueError("invalid point fields")
        A, U, V = (_matrix(case[key], key) for key in ("A", "U", "V"))
        E1, E2 = (_matrix(case[key], key) for key in ("E1", "E2"))
        n = A.shape[0]
        if not 2 <= n <= 128 or A.shape != (n, n) or U.shape[0] != n or V.shape != U.shape:
            raise ValueError("incompatible A/U/V dimensions")
        k = U.shape[1]
        if not 1 <= k < n or E1.shape != (n, n) or E2.shape != (k, k):
            raise ValueError("incompatible rank/noise dimensions")
        if np.linalg.matrix_rank(U) != k or np.linalg.matrix_rank(V) != k:
            raise ValueError("U and V must have full column rank")
        e1, e2 = float(norm(E1, 2)), float(norm(E2, 2))
        if e1 <= 0 or e2 <= 0:
            raise ValueError("noise spectral norms must be positive")
        return {"mode": "point", "A": A, "U": U, "V": V, "draws": [(e1, e2, E1, E2)]}
    required = {"mode", "n", "k", "update_regime", "update_factor", "epsilon_grid", "replicates", "seed"}
    if set(case) != required:
        raise ValueError("invalid sweep fields")
    n, k, replicates, seed = case["n"], case["k"], case["replicates"], case["seed"]
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (n, k, replicates, seed)):
        raise ValueError("n, k, replicates, and seed must be integers")
    if not 2 <= n <= 128 or not 1 <= k < n or not 1 <= replicates <= 100 or not 0 <= seed < 2**32:
        raise ValueError("invalid sweep dimensions, replicate count, or seed")
    if case["update_regime"] not in {"small", "large"}:
        raise ValueError("update_regime must be small or large")
    factor = float(case["update_factor"])
    epsilon = np.asarray(case["epsilon_grid"], dtype=np.float64)
    if not math.isfinite(factor) or factor <= 0 or epsilon.ndim != 1 or not 1 <= epsilon.size <= 64 or not np.isfinite(epsilon).all() or np.any(epsilon <= 0):
        raise ValueError("invalid update_factor or epsilon_grid")
    rng = np.random.RandomState(seed)
    A = rng.normal(size=(n, n)).astype(np.float64)
    U0 = rng.normal(size=(n, k)).astype(np.float64); U0 /= norm(U0, 2)
    V0 = rng.normal(size=(n, k)).astype(np.float64); V0 /= norm(V0, 2)
    singular = np.linalg.svd(A, compute_uv=False)
    lamda = factor * (singular[-1] if case["update_regime"] == "small" else singular[0])
    U, V = math.sqrt(lamda) * U0, math.sqrt(lamda) * V0
    draws = []
    for e in epsilon:
        for _ in range(replicates):
            E1 = rng.normal(size=(n, n)).astype(np.float64); E1 *= e / norm(E1, 2)
            E2 = rng.normal(size=(k, k)).astype(np.float64); E2 *= e / norm(E2, 2)
            draws.append((float(e), float(e), E1, E2))
    return {"mode": "sweep", "A": A, "U": U, "V": V, "draws": draws,
            "epsilon": epsilon, "replicates": replicates}


class _Noise:
    def __init__(self, matrices: tuple[np.ndarray, np.ndarray]):
        self.matrices = iter(matrices)

    def normal(self, size: tuple[int, int]) -> np.ndarray:
        value = np.asarray(next(self.matrices), dtype=np.float64)
        if value.shape != tuple(size):
            raise ValueError("injected noise shape mismatch")
        return value.copy()


def _kernel(checkout: Path, notebook: str):
    document = json.loads((checkout / notebook).read_text(encoding="utf-8"))
    sources = ["".join(cell.get("source", [])) for cell in document["cells"]]
    matches = [source for source in sources if source.lstrip().startswith("def compute_SMW(")]
    if len(matches) != 1:
        raise RuntimeError(f"expected one compute_SMW definition in {notebook}")
    namespace = {"np": np, "norm": norm, "inv": inv}
    exec(matches[0], namespace)
    return namespace["compute_SMW"]


def _call(function, A, U, V, E1, E2, epsilon1, epsilon2, parameter):
    original_random = np.random
    try:
        np.random = _Noise((E1, E2))  # function body remains byte-for-byte notebook source
        B = A + U @ V.T
        lamda = float(norm(U, 2) * norm(V, 2))
        return function(A.shape[0], U.shape[1], A, B, U, V, lamda, epsilon1, epsilon2, parameter)
    finally:
        np.random = original_random


def solve(case: dict[str, Any], checkout: Path) -> dict[str, list[float]]:
    clean = validate_case(case)
    A, U, V = clean["A"], clean["U"], clean["V"]
    _invertible(A, "A"); _invertible(A + U @ V.T, "B")
    A_inv = inv(A)
    alpha = float(norm(inv(np.eye(U.shape[1]) + V.T @ A_inv @ U), 2))
    beta = float(norm(np.eye(U.shape[1]) + V.T @ A_inv @ U, 2))
    forward = _kernel(checkout, "SMW_forward_same_epsilon.ipynb")
    backward = _kernel(checkout, "SMW_backward_same_epsilon.ipynb")
    grouped: list[list[tuple[float, ...]]] = []
    width = clean.get("replicates", 1)
    for offset in range(0, len(clean["draws"]), width):
        rows = []
        for e1, e2, E1, E2 in clean["draws"][offset:offset + width]:
            f = _call(forward, A, U, V, E1, E2, e1, e2, alpha)
            b = _call(backward, A, U, V, E1, E2, e1, e2, beta)
            rows.append((e1, e2, *f, *b))
        grouped.append(rows)
    result = {key: [] for key in OUTPUT_KEYS}
    for rows in grouped:
        means = np.mean(np.asarray(rows, dtype=np.float64), axis=0)
        values = (means[0], means[1], means[2], means[3], means[4], means[5], means[6], means[7])
        for key, value in zip(OUTPUT_KEYS, values):
            if not math.isfinite(float(value)):
                raise ValueError("non-finite SMW result")
            result[key].append(float(value))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.task != "0014":
        parser.error("unsupported task")
    value = json.loads(args.input.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    result = solve(value, args.checkout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
