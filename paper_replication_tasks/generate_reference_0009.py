#!/usr/bin/env python3
"""Generate the deterministic hidden reference for replication task 0009.

This implements the paper's Floquet-DMD Example 2 independently of the
notebook-only stochastic examples. The physical trajectory is integrated in
the Bloch representation and the rank-three exact-DMD model is fit to the
first four Floquet columns. The fifth column supplies the extrapolation
initial condition.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import solve_ivp


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "scibench_replication_0009/hidden/gold_artifacts"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bloch_rhs(t: float, state: np.ndarray) -> np.ndarray:
    drive = np.cos(2.0 * np.pi * 1.1 * t)
    x, y, z = state
    return np.asarray(
        (-2.0 * np.pi * y, 2.0 * np.pi * x - 2.0 * drive * z, 2.0 * drive * y)
    )


def floquet_reshape(data: np.ndarray, measurements_per_period: int) -> np.ndarray:
    return data.T.reshape(-1, measurements_per_period * data.shape[0]).T


def exact_dmd(
    snapshots: np.ndarray, rank: int
) -> tuple[np.ndarray, np.ndarray]:
    x1, x2 = snapshots[:, :-1], snapshots[:, 1:]
    u, singular_values, vh = np.linalg.svd(x1, full_matrices=False)
    u = u[:, :rank]
    singular_values = singular_values[:rank]
    v = vh.conj().T[:, :rank]
    sigma_inverse = np.diag(1.0 / singular_values)
    reduced = u.conj().T @ x2 @ v @ sigma_inverse
    eigenvalues, eigenvectors = np.linalg.eig(reduced)
    modes = x2 @ v @ sigma_inverse @ eigenvectors
    return eigenvalues, modes


def main() -> None:
    drive_period = 1.0 / 1.1
    simulation_points_per_period = 32
    total_periods = 13
    simulation_times = (
        np.arange(total_periods * simulation_points_per_period, dtype=np.float64)
        * drive_period
        / simulation_points_per_period
    )
    solution = solve_ivp(
        bloch_rhs,
        (0.0, float(simulation_times[-1])),
        np.asarray((0.0, 0.0, -1.0)),
        method="DOP853",
        t_eval=simulation_times,
        rtol=1e-12,
        atol=1e-14,
    )
    if not solution.success:
        raise RuntimeError(solution.message)

    measured = solution.y[:, :: simulation_points_per_period // 4]
    floquet_columns = floquet_reshape(measured, 4)
    training = floquet_columns[:, :4]
    eigenvalues, modes = exact_dmd(training, rank=3)

    initial_column = floquet_columns[:, 4]
    coefficients = np.linalg.pinv(modes) @ initial_column
    predicted_columns = np.column_stack(
        [modes @ (eigenvalues**step * coefficients) for step in range(9)]
    ).real
    predicted_samples = predicted_columns.T.reshape(-1, 3).T
    prediction_trajectory = predicted_samples[:, 4:]
    prediction_times = (
        5.0 * drive_period
        + np.arange(32, dtype=np.float64) * drive_period / 4.0
    )
    eigenvalue_pairs = np.column_stack((eigenvalues.real, eigenvalues.imag))

    if prediction_trajectory.shape != (3, 32):
        raise RuntimeError("unexpected trajectory shape")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "floquet_eigenvalues": eigenvalue_pairs,
        "prediction_times": prediction_times,
        "prediction_trajectory": prediction_trajectory,
    }
    for artifact_id, value in artifacts.items():
        np.save(OUTPUT / f"{artifact_id}.npy", np.asarray(value, dtype=np.float64))

    script_path = Path(__file__).resolve()
    metadata = {
        "schema_version": 1,
        "experiment": "deterministic_floquet_dmd_example_2",
        "generator_sha256": sha256(script_path),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "protocol": {
            "intrinsic_period": 1.0,
            "drive_frequency": 1.1,
            "simulation_points_per_drive_period": 32,
            "measurements_per_drive_period": 4,
            "training_periods": 4,
            "initialization_periods": 1,
            "prediction_periods": 8,
            "dmd_rank": 3,
            "ode_method": "DOP853",
            "ode_rtol": 1e-12,
            "ode_atol": 1e-14,
        },
        "artifacts": {
            artifact_id: {
                "path": f"{artifact_id}.npy",
                "shape": list(value.shape),
                "sha256": sha256(OUTPUT / f"{artifact_id}.npy"),
            }
            for artifact_id, value in artifacts.items()
        },
    }
    (OUTPUT / "reference_generation.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("Generated deterministic task 0009 reference artifacts.")


if __name__ == "__main__":
    main()
