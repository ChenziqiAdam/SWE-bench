#!/usr/bin/env python3
"""Independent NumPy implementation of the periodic 1D/2D FSL equations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

MAX_JSON_BYTES = 16 * 1024 * 1024


def _input(path: Path) -> tuple[int, int, int, np.ndarray]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("input JSON exceeds 16 MiB")
    data = json.loads(path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if not isinstance(data, dict) or set(data) != {"dimension", "n", "m", "samples"}:
        raise ValueError("input keys differ")
    d, n, m = data["dimension"], data["n"], data["m"]
    if isinstance(d, bool) or d not in (1, 2):
        raise ValueError("dimension must be 1 or 2")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (n, m)):
        raise ValueError("n and m must be integers")
    valid = (d == 1 and 3 <= n <= 9 and 0 <= m < n and m <= 5) or (d == 2 and 2 <= n <= 5 and 0 <= m < n and m <= 2)
    if not valid:
        raise ValueError("n/m out of bounds")
    rows = data["samples"]
    if not isinstance(rows, list) or len(rows) != 2 ** (d * n):
        raise ValueError("sample length differs")
    if any(not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in p) for p in rows):
        raise ValueError("invalid complex pairs")
    values = np.array([complex(float(p[0]), float(p[1])) for p in rows])
    if np.linalg.norm(values) == 0:
        raise ValueError("zero samples")
    return d, n, m, values.reshape((2**n, 2**n)) if d == 2 else values


def _coefficient_state(samples: np.ndarray, dimension: int, m: int) -> np.ndarray:
    width = 2**m
    if dimension == 1:
        spectrum = np.fft.ifft(samples)
        selected = np.concatenate((spectrum[:width], np.zeros(1, complex), spectrum[-(width - 1):] if width > 1 else np.zeros(0, complex)))
    else:
        spectrum = np.fft.ifft2(samples)
        side = spectrum.shape[0]
        selected = np.zeros((2 * width, 2 * width), complex)
        source = [*range(width), *range(side - width + 1, side)]
        target = [*range(width), *range(width + 1, 2 * width)]
        selected[np.ix_(target, target)] = spectrum[np.ix_(source, source)]
        selected = selected.reshape(-1)
    norm = np.linalg.norm(selected)
    if norm == 0 or not np.isfinite(norm):
        raise ValueError("retained Fourier block must be nonzero")
    return selected / norm


def _alphas_y(target: np.ndarray) -> list[list[float]]:
    qubits = int(round(math.log2(target.size)))
    weights = np.abs(target) ** 2
    layers: list[list[float]] = []
    for level in range(qubits):
        half = 2**level
        layer = []
        for block in range(2 ** (qubits - level - 1)):
            start = block * 2 * half
            numerator = math.sqrt(float(np.sum(weights[start + half:start + 2 * half])))
            denominator = math.sqrt(float(np.sum(weights[start:start + 2 * half])))
            ratio = 1.0 if denominator == numerator else numerator / denominator
            layer.append(2.0 * math.asin(min(1.0, max(0.0, ratio))))
        layers.append(layer)
    return layers


def _alphas_z(target: np.ndarray) -> tuple[list[list[float]], float]:
    qubits = int(round(math.log2(target.size)))
    phases = np.angle(target)
    layers: list[list[float]] = []
    for level in range(qubits):
        half = 2**level
        layer = []
        for block in range(2 ** (qubits - level - 1)):
            start = block * 2 * half
            layer.append(float(np.sum(phases[start + half:start + 2 * half] - phases[start:start + half]) / half))
        layers.append(layer)
    return layers, float(2.0 * np.mean(phases))


def _theta_layers(alphas: list[list[float]]) -> list[list[float]]:
    result = []
    for alpha in alphas:
        count = len(alpha)
        layer = []
        for gray_index in range(count):
            gray = gray_index ^ (gray_index >> 1)
            total = 0.0
            for binary_index, value in enumerate(alpha):
                parity = (gray & binary_index).bit_count() & 1
                total += (-1.0 if parity else 1.0) * value
            layer.append(total / count)
        result.append(layer)
    return result


def _final_state(coefficient: np.ndarray, dimension: int, n: int, m: int) -> np.ndarray:
    size, width = 2**n, 2**m
    if dimension == 1:
        padded = np.zeros(size, complex)
        padded[:width] = coefficient[:width]
        if width > 1:
            padded[-(width - 1):] = coefficient[width + 1:]
        state = np.fft.fft(padded) / math.sqrt(size)
    else:
        compact = coefficient.reshape((2 * width, 2 * width))
        padded = np.zeros((size, size), complex)
        source = [*range(width), *range(width + 1, 2 * width)]
        target = [*range(width), *range(size - width + 1, size)]
        padded[np.ix_(target, target)] = compact[np.ix_(source, source)]
        state = (np.fft.fft2(padded) / size).reshape(-1)
    pivot = int(np.argmax(np.abs(state)))
    state *= np.exp(-1j * np.angle(state[pivot]))
    state[pivot] = complex(abs(state[pivot]), 0.0)
    return state


def _wrap(value: float) -> float:
    x = (float(value) + np.pi) % (2 * np.pi) - np.pi
    return 0.0 if x == 0.0 else x


def _pairs(values: np.ndarray) -> list[list[float]]:
    return [[0.0 if float(z.real) == 0.0 else float(z.real), 0.0 if float(z.imag) == 0.0 else float(z.imag)] for z in np.asarray(values).reshape(-1)]


def solve(path: Path) -> dict:
    dimension, n, m, samples = _input(path)
    coefficient = _coefficient_state(samples, dimension, m)
    alpha_z, phase = _alphas_z(coefficient)
    return {
        "coefficient_state": _pairs(coefficient),
        "rotation_y": [[_wrap(v) for v in row] for row in _theta_layers(_alphas_y(coefficient))],
        "rotation_z": [[_wrap(v) for v in row] for row in _theta_layers(alpha_z)],
        "phase": _wrap(phase),
        "statevector": _pairs(_final_state(coefficient, dimension, n, m)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = solve(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "output.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
