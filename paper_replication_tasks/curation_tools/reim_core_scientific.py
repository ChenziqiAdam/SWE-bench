"""Independent NumPy implementation derived only from paper Algorithm 2.1."""

from __future__ import annotations

import numpy as np

from reim_core_common import validate_case


def solve(value: dict) -> dict:
    n, atoms, targets, query_atoms, first = validate_case(value)
    selected_x = [int(np.argmax(np.abs(atoms[:, first])))]
    selected_g = [first]
    for _ in range(1, n):
        interpolation = atoms[np.ix_(selected_x, selected_g)]
        sampled_atoms = atoms[selected_x, :]
        weights = np.linalg.solve(interpolation, sampled_atoms)
        errors = atoms - atoms[:, selected_g] @ weights
        infinity_errors = np.max(np.abs(errors), axis=0)
        next_g = int(np.argmax(infinity_errors))
        next_x = int(np.argmax(np.abs(errors[:, next_g])))
        selected_g.append(next_g)
        selected_x.append(next_x)
    interpolation = atoms[np.ix_(selected_x, selected_g)]
    weights = np.linalg.solve(interpolation, targets[selected_x, :])
    predictions = query_atoms[:, selected_g] @ weights
    return {
        "sample_indices": selected_x,
        "dictionary_indices": selected_g,
        "interpolation_matrix": interpolation.tolist(),
        "coefficients": weights.tolist(),
        "predictions": predictions.tolist(),
    }
