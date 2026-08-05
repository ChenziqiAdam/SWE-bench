#!/usr/bin/env python3
"""Official-kernel adapters for generalized core-method tasks 0009 and 0012."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

LAST_RAW: dict[str, Any] | None = None


def finite(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return finite(value.tolist())
    if isinstance(value, np.generic):
        return finite(value.item())
    if isinstance(value, complex):
        return [finite(value.real), finite(value.imag)]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("official adapter produced a non-finite value")
    if isinstance(value, list):
        return [finite(item) for item in value]
    if isinstance(value, dict):
        return {key: finite(item) for key, item in value.items()}
    return value


def complex_pairs(values: Any) -> list[list[float]]:
    array = np.asarray(values, dtype=complex).reshape(-1)
    if not np.isfinite(array).all():
        raise ValueError("official adapter produced non-finite eigenvalues")
    return [[float(value.real), float(value.imag)] for value in array]


def load_module(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load official module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def exact_dmd(_: Path, case: dict[str, Any]) -> dict[str, Any]:
    global LAST_RAW
    import dmdlab

    if set(case) != {"snapshot_blocks", "dmd_rank", "prediction_steps"}:
        raise ValueError("input must contain only snapshot_blocks, dmd_rank, and prediction_steps")
    blocks = np.asarray(case["snapshot_blocks"], dtype=float)
    if blocks.ndim != 3 or min(blocks.shape) < 1 or blocks.shape[2] < 2 or not np.isfinite(blocks).all():
        raise ValueError("snapshot_blocks must be finite with shape (blocks>=1, state>=1, snapshots>=2)")
    rank, steps = case["dmd_rank"], case["prediction_steps"]
    available = min(blocks.shape[1], blocks.shape[0] * (blocks.shape[2] - 1))
    if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= available:
        raise ValueError("dmd_rank is outside the available snapshot rank")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("prediction_steps must be a positive integer")
    x1 = np.concatenate([block[:, :-1] for block in blocks], axis=1)
    x2 = np.concatenate([block[:, 1:] for block in blocks], axis=1)
    times = np.arange(x1.shape[1] + 1, dtype=float)
    model = dmdlab.DMD(x2, x1, times, threshold_type="count", threshold=rank)
    prediction = np.real_if_close(model.predict_dst(np.arange(1, steps + 1, dtype=float), blocks[-1, :, -1]))
    if np.iscomplexobj(prediction) or prediction.shape != (blocks.shape[1], steps) or not np.isfinite(prediction).all():
        raise ValueError("dmdlab produced a non-real, non-finite, or incorrectly shaped prediction")
    LAST_RAW = finite({"X1": x1, "X2": x2, "times": times, "projected_eigenvalues": model.eigs, "prediction": prediction})
    return finite({"eigenvalues": complex_pairs(model.eigs), "prediction": prediction})


def anisotropy(checkout: Path, case: dict[str, Any]) -> dict[str, Any]:
    global LAST_RAW
    if set(case) != {"spin", "anisotropy_ratio", "temperature_grid", "orientation_grid"}:
        raise ValueError("anisotropy input contains unknown or missing fields")
    spin, ratio = float(case["spin"]), float(case["anisotropy_ratio"])
    temperature = np.asarray(case["temperature_grid"], dtype=float)
    orientation = np.asarray(case["orientation_grid"], dtype=float)
    if not math.isfinite(spin) or spin <= 0 or not math.isclose(2 * spin, round(2 * spin), abs_tol=1e-12):
        raise ValueError("spin must be a positive integer or half-integer")
    if not math.isfinite(ratio):
        raise ValueError("anisotropy_ratio must be finite")
    if temperature.ndim != 1 or not temperature.size or not np.isfinite(temperature).all() or np.any(temperature <= 0):
        raise ValueError("temperature_grid must be a non-empty finite positive array")
    if orientation.ndim != 1 or not orientation.size or not np.isfinite(orientation).all() or np.any(np.abs(orientation) >= 1):
        raise ValueError("orientation_grid must be finite and strictly inside (-1, 1)")
    analytic = load_module("official_single_spin_anisotropy_exact", checkout / "python/analytic.py")
    beta, a1, a2 = 1.0 / temperature, 1.0, ratio
    expression = analytic.eff_hamiltonian_classical_exact(int(2 * spin))
    h_fn = analytic.lambdify([analytic.B, analytic.C, analytic.D, analytic.n], expression, "numpy")
    f_fn = analytic.generate_field_function_exact(spin)
    hamiltonian = np.asarray([[h_fn(b, a2, a1, n) for n in orientation] for b in beta])
    field = np.asarray([[f_fn(b, a2, a1, n, 1.0, 1.0) for n in orientation] for b in beta])
    if hamiltonian.shape != (temperature.size, orientation.size) or field.shape != hamiltonian.shape:
        raise ValueError("official exact functions returned an invalid shape")
    LAST_RAW = finite({"beta": beta, "A_1": a1, "A_2": a2, "g_mu_B": 1.0, "hamiltonian": hamiltonian, "effective_field": field})
    return finite({"temperature": temperature, "orientation": orientation, "hamiltonian": hamiltonian, "effective_field": field})


ADAPTERS = {"0009": exact_dmd, "0012": anisotropy}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=sorted(ADAPTERS), required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    value = ADAPTERS[args.task](args.checkout.resolve(), json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if args.raw_output is not None:
        if LAST_RAW is None:
            raise RuntimeError("adapter did not expose raw official output")
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(LAST_RAW, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
