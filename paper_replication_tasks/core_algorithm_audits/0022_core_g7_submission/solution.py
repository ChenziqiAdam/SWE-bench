#!/usr/bin/env python3
"""Sketch-and-select Arnoldi process (the paper's ``select pinv`` variant)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def sketch_and_select_arnoldi(data: dict) -> dict[str, list]:
    """Construct the Krylov basis and the auxiliary matrices from the input."""
    matrix = np.asarray(data["matrix"], dtype=np.float64)
    start = np.asarray(data["start_vector"], dtype=np.float64)
    sketch = np.asarray(data["sketch_matrix"], dtype=np.float64)
    iterations = int(data["iterations"])
    budget = int(data["selection_budget"])

    n = start.size
    sketch_size = sketch.shape[0]

    basis = np.zeros((n, iterations + 1), dtype=np.float64)
    sketched_basis = np.zeros(
        (sketch_size, iterations + 1), dtype=np.float64
    )
    sketched_products = np.zeros(
        (sketch_size, iterations), dtype=np.float64
    )
    hessenberg = np.zeros((iterations + 1, iterations), dtype=np.float64)

    sketched_vector = sketch @ start
    scale = np.linalg.norm(sketched_vector)
    basis[:, 0] = start / scale
    sketched_basis[:, 0] = sketched_vector / scale

    for j in range(iterations):
        vector = matrix @ basis[:, j]
        sketched_vector = sketch @ vector
        sketched_products[:, j] = sketched_vector

        coefficients = np.linalg.lstsq(
            sketched_basis[:, : j + 1], sketched_vector, rcond=None
        )[0]

        # MATLAB's maxk returns values from largest to smallest.  A stable sort
        # also gives deterministic behavior when coefficient magnitudes tie.
        selected_count = min(max(budget, 0), j + 1)
        selected = np.argsort(
            -np.abs(coefficients), kind="stable"
        )[:selected_count]

        if selected_count:
            selected_coefficients = coefficients[selected]
            vector = vector - basis[:, selected] @ selected_coefficients
            sketched_vector = (
                sketched_vector
                - sketched_basis[:, selected] @ selected_coefficients
            )
            hessenberg[selected, j] = selected_coefficients

        scale = np.linalg.norm(sketched_vector)
        basis[:, j + 1] = vector / scale
        sketched_basis[:, j + 1] = sketched_vector / scale
        hessenberg[j + 1, j] = scale

    return {
        "basis": basis.tolist(),
        "hessenberg": hessenberg.tolist(),
        "sketched_basis": sketched_basis.tolist(),
        "sketched_products": sketched_products.tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)

    result = sketch_and_select_arnoldi(data)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "output.json").open("w", encoding="utf-8") as output_file:
        json.dump(result, output_file, allow_nan=False)


if __name__ == "__main__":
    main()
