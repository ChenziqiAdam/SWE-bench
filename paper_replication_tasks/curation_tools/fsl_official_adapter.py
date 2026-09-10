#!/usr/bin/env python3
"""Thin JSON adapter for the pinned Fourier-Series-Loader implementation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

COMMIT = "006852b348a48a20a9a0e584cf73f08c8964ef98"
MAX_JSON_BYTES = 16 * 1024 * 1024


def _load(checkout: Path, name: str):
    path = checkout / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"fsl_official_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load official source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


def _read_input(path: Path) -> tuple[int, int, int, np.ndarray]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("input JSON exceeds 16 MiB")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if not isinstance(value, dict) or set(value) != {"dimension", "n", "m", "samples"}:
        raise ValueError("input keys differ")
    dimension, n, m = value["dimension"], value["n"], value["m"]
    if isinstance(dimension, bool) or dimension not in (1, 2):
        raise ValueError("dimension must be 1 or 2")
    if isinstance(n, bool) or not isinstance(n, int) or isinstance(m, bool) or not isinstance(m, int):
        raise ValueError("n and m must be integers")
    if dimension == 1 and not (3 <= n <= 9 and 0 <= m < n and m <= 5):
        raise ValueError("1D n/m out of bounds")
    if dimension == 2 and not (2 <= n <= 5 and 0 <= m < n and m <= 2):
        raise ValueError("2D n/m out of bounds")
    samples = value["samples"]
    expected = 2 ** (dimension * n)
    if not isinstance(samples, list) or len(samples) != expected:
        raise ValueError("sample length differs")
    parsed: list[complex] = []
    for pair in samples:
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)) for x in pair)):
            raise ValueError("samples must be finite [real, imag] pairs")
        parsed.append(complex(float(pair[0]), float(pair[1])))
    array = np.asarray(parsed, dtype=complex)
    if np.linalg.norm(array) == 0:
        raise ValueError("samples must have nonzero norm")
    if dimension == 2:
        array = array.reshape((2**n, 2**n))
    return dimension, n, m, array


def _wrap(value: float) -> float:
    result = (float(value) + np.pi) % (2 * np.pi) - np.pi
    return 0.0 if result == 0.0 else result


def _pairs(values) -> list[list[float]]:
    result = []
    for value in np.asarray(values, dtype=complex).reshape(-1):
        real = float(value.real)
        imag = float(value.imag)
        result.append([0.0 if real == 0.0 else real, 0.0 if imag == 0.0 else imag])
    return result


def _canonical_state(values) -> np.ndarray:
    state = np.asarray(values, dtype=complex).reshape(-1)
    pivot = int(np.argmax(np.abs(state)))
    state = state * np.exp(-1j * np.angle(state[pivot]))
    state[pivot] = complex(abs(state[pivot]), 0.0)
    return state


def solve(value_path: Path, checkout: Path) -> dict:
    dimension, n, m, samples = _read_input(value_path)
    supplementary = _load(checkout, "supplementary")
    ucr = _load(checkout, "uniformly_controlled_rotations")
    if dimension == 1:
        coefficient = np.asarray(supplementary.Fourier_state(samples, m), dtype=complex)
    else:
        coefficient = np.asarray(supplementary.Fourier_state_2d(samples, m), dtype=complex)
    if not np.isfinite(coefficient).all() or np.linalg.norm(coefficient) == 0:
        raise ValueError("retained Fourier block must be nonzero")

    rotation_y = ucr.find_thetas_y(coefficient)
    rotation_z, phase = ucr.find_thetas_z(coefficient)

    from qiskit import Aer, QuantumCircuit, transpile
    from qiskit.circuit.library import QFT

    simulator = Aer.get_backend("statevector_simulator")
    circuit = QuantumCircuit(dimension * n)
    loader = ucr.cascade_UCRs(coefficient)
    if dimension == 1:
        loader_qubits = list(range(n - m - 1, n))
        circuit.compose(loader, qubits=loader_qubits, inplace=True)
        for index in range(n - m - 1):
            circuit.cx(n - m - 1, index)
        inverse = transpile(QFT(num_qubits=n, inverse=True), simulator, seed_transpiler=0)
        circuit.compose(inverse, qubits=range(n - 1, -1, -1), inplace=True)
    else:
        loader_qubits = [*range(n - m - 1, n), *range(2 * n - m - 1, 2 * n)]
        circuit.compose(loader, qubits=loader_qubits, inplace=True)
        for index in range(n - m - 1):
            circuit.cx(n - m - 1, index)
            circuit.cx(2 * n - m - 1, n + index)
        inverse = QFT(num_qubits=n, inverse=True)
        circuit.compose(inverse, qubits=range(n - 1, -1, -1), inplace=True)
        circuit.compose(inverse, qubits=range(2 * n - 1, n - 1, -1), inplace=True)
    compiled = transpile(circuit, simulator, seed_transpiler=0)
    raw = simulator.run(compiled).result().get_statevector(compiled)
    state = _canonical_state(supplementary.output_reordering(raw))
    return {
        "coefficient_state": _pairs(coefficient),
        "rotation_y": [[_wrap(x) for x in layer] for layer in rotation_y],
        "rotation_z": [[_wrap(x) for x in layer] for layer in rotation_z],
        "phase": _wrap(phase),
        "statevector": _pairs(state),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = solve(args.input, args.checkout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
