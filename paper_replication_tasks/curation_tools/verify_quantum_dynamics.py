#!/usr/bin/env python3
"""Independent SciPy formulation and MATLAB comparison for the quantum candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import loadmat
from scipy.optimize import linear_sum_assignment
from scipy.sparse.linalg import expm_multiply


SHAPES = {
    "open_ising_times": (3000,),
    "open_ising_observables": (2, 3000),
    "open_ising_eigenvalues": (16, 2),
    "light_bath_times": (100000,),
    "light_bath_observables": (4, 100000),
    "light_bath_eigenvalues": (4, 2),
}


def dissipator(operator: np.ndarray) -> np.ndarray:
    dimension = operator.shape[0]
    identity = np.eye(dimension)
    product = operator.conj().T @ operator
    return (
        np.kron(operator.conj(), operator)
        - 0.5 * np.kron(identity, product)
        - 0.5 * np.kron(product.T, identity)
    )


def evolve(
    liouvillian: np.ndarray, rho0: np.ndarray, times: np.ndarray
) -> np.ndarray:
    vectors = expm_multiply(
        liouvillian,
        rho0.reshape(-1, order="F"),
        start=float(times[0]),
        stop=float(times[-1]),
        num=times.size,
        endpoint=True,
    )
    dimension = rho0.shape[0]
    return vectors.reshape((-1, dimension, dimension), order="F")


def complex_columns(values: np.ndarray) -> np.ndarray:
    flat = np.asarray(values).reshape(-1)
    return np.column_stack((flat.real, flat.imag)).astype(np.float64)


def open_ising() -> dict[str, np.ndarray]:
    identity_2 = np.eye(2)
    identity_4 = np.eye(4)
    sx = np.array([[0.0, 1.0], [1.0, 0.0]])
    sz = np.diag([1.0, -1.0])
    lowering = np.array([[0.0, 0.0], [1.0, 0.0]])
    coupling = 1.0
    field = 0.1 * coupling
    hamiltonian = (
        -coupling * np.kron(sx, sx)
        - field * (np.kron(sx, identity_2) + np.kron(identity_2, sx))
    )
    l1 = np.kron(lowering, identity_2)
    l2 = np.kron(identity_2, lowering)
    liouvillian = (
        -1j * np.kron(identity_4, hamiltonian)
        + 1j * np.kron(hamiltonian.T, identity_4)
        + 0.1 * field * dissipator(l1)
        + 0.5 * field * dissipator(l2)
    )
    period = 2.0 * np.pi / (2.0 * field)
    times = np.linspace(0.0, 4.0 * period, 3000)
    down = np.array([0.0, 1.0])
    rho0 = np.outer(np.kron(down, down), np.kron(down, down))
    densities = evolve(liouvillian, rho0, times)
    magnetization_operator = (
        np.kron(sz, identity_2) + np.kron(identity_2, sz)
    ) / 2.0
    magnetization = np.einsum(
        "tij,ji->t", densities, magnetization_operator
    ).real
    eigenvalues = np.linalg.eigvals(liouvillian)
    envelope_rate = eigenvalues.real.min()
    observables = np.vstack((magnetization, np.exp(envelope_rate * times)))
    return {
        "open_ising_times": times,
        "open_ising_observables": observables,
        "open_ising_eigenvalues": complex_columns(eigenvalues),
    }


def light_bath() -> tuple[dict[str, np.ndarray], dict[str, float]]:
    identity = np.eye(2)
    excited = identity[:, 0]
    ground = identity[:, 1]
    raising = np.outer(excited, ground)
    lowering = np.outer(ground, excited)
    omega = 1.0
    gamma = 0.2 * omega
    hamiltonian = -0.5 * omega * (raising + lowering)
    liouvillian = (
        -1j * np.kron(identity, hamiltonian)
        + 1j * np.kron(hamiltonian.T, identity)
        + gamma * dissipator(lowering)
    )
    times = np.linspace(0.0, 50.0 / omega, 100000)
    densities = evolve(liouvillian, np.outer(ground, ground), times)
    population = densities[:, 0, 0].real
    coherence = np.einsum("tij,ji->t", densities, raising).imag

    mu = 1j * np.sqrt((gamma / 4.0) ** 2 - omega**2 + 0j)
    decay = np.exp(-3.0 * gamma * times / 4.0)
    exact_population = (
        omega**2
        / (gamma**2 + 2.0 * omega**2)
        * (
            1.0
            - decay
            * (
                np.cos(mu * times)
                + 3.0 * gamma / (4.0 * mu) * np.sin(mu * times)
            )
        )
    ).real
    exact_coherence = (
        -1j
        * omega
        * gamma
        / (gamma**2 + 2.0 * omega**2)
        * (
            1.0
            - decay
            * (
                np.cos(mu * times)
                + (gamma / (4.0 * mu) - omega**2 / (gamma * mu))
                * np.sin(mu * times)
            )
        )
    ).imag

    # The pinned repository omits the sine multiplier on gamma/(4*mu).
    repository_coherence = (
        -1j
        * omega
        * gamma
        / (gamma**2 + 2.0 * omega**2)
        * (
            1.0
            - decay
            * (
                np.cos(mu * times)
                + gamma / (4.0 * mu)
                - omega**2 / (gamma * mu) * np.sin(mu * times)
            )
        )
    ).imag
    diagnostics = {
        "population_analytic_max_abs": max_abs(population, exact_population),
        "population_analytic_rmse": rmse(population, exact_population),
        "paper_coherence_max_abs": max_abs(coherence, exact_coherence),
        "paper_coherence_rmse": rmse(coherence, exact_coherence),
        "repository_coherence_max_abs": max_abs(coherence, repository_coherence),
        "repository_coherence_rmse": rmse(coherence, repository_coherence),
        "numerical_coherence_at_t0": float(coherence[0]),
        "paper_coherence_at_t0": float(exact_coherence[0]),
        "repository_coherence_at_t0": float(repository_coherence[0]),
    }
    assert np.isfinite(exact_coherence).all()
    assert np.isfinite(repository_coherence).all()
    return (
        {
            "light_bath_times": times,
            "light_bath_observables": np.vstack(
                (population, exact_population, coherence, exact_coherence)
            ),
            "light_bath_eigenvalues": complex_columns(
                np.linalg.eigvals(liouvillian)
            ),
        },
        diagnostics,
    )


def max_abs(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.max(np.abs(left - right), initial=0.0))


def rmse(left: np.ndarray, right: np.ndarray) -> float:
    delta = left - right
    return float(np.sqrt(np.mean(np.abs(delta) ** 2)))


def eigenvalue_error(left: np.ndarray, right: np.ndarray) -> float:
    left_complex = left[:, 0] + 1j * left[:, 1]
    right_complex = right[:, 0] + 1j * right[:, 1]
    costs = np.abs(left_complex[:, None] - right_complex[None, :])
    rows, columns = linear_sum_assignment(costs)
    return float(costs[rows, columns].max(initial=0.0))


def load_matlab(directory: Path) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for prefix in ("open_ising", "light_bath"):
        values = loadmat(directory / f"{prefix}.mat")
        result[f"{prefix}_times"] = np.asarray(values["times"]).reshape(-1)
        result[f"{prefix}_observables"] = np.asarray(
            values["observables"], dtype=np.float64
        )
        result[f"{prefix}_eigenvalues"] = complex_columns(values["eigenvalues"])
    return result


def compare(
    independent: dict[str, np.ndarray], matlab: dict[str, np.ndarray]
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    passed = True
    for prefix in ("open_ising", "light_bath"):
        time_error = max_abs(
            independent[f"{prefix}_times"], matlab[f"{prefix}_times"]
        )
        curve_max = max_abs(
            independent[f"{prefix}_observables"],
            matlab[f"{prefix}_observables"],
        )
        curve_rmse = rmse(
            independent[f"{prefix}_observables"],
            matlab[f"{prefix}_observables"],
        )
        eig_error = eigenvalue_error(
            independent[f"{prefix}_eigenvalues"],
            matlab[f"{prefix}_eigenvalues"],
        )
        row_passed = (
            time_error <= 1e-12
            and curve_max <= 1e-6
            and curve_rmse <= 1e-7
            and eig_error <= 1e-7
        )
        passed = passed and row_passed
        diagnostics[prefix] = {
            "time_max_abs": time_error,
            "curve_max_abs": curve_max,
            "curve_rmse": curve_rmse,
            "eigenvalue_unordered_max_abs": eig_error,
            "passed": row_passed,
        }
    return {"passed": passed, "experiments": diagnostics}


def validate_arrays(arrays: dict[str, np.ndarray]) -> None:
    if set(arrays) != set(SHAPES):
        raise ValueError("artifact set mismatch")
    for name, shape in SHAPES.items():
        value = arrays[name]
        if value.shape != shape or value.dtype.kind not in "fiu":
            raise ValueError(f"{name}: expected finite numeric shape {shape}")
        if not np.isfinite(value).all():
            raise ValueError(f"{name}: non-finite value")
    for name in ("open_ising_times", "light_bath_times"):
        if np.any(np.diff(arrays[name]) <= 0.0):
            raise ValueError(f"{name}: time grid is not strictly increasing")
    for row in (0, 1):
        population = arrays["light_bath_observables"][row]
        if population.min() < -1e-12 or population.max() > 1.0 + 1e-12:
            raise ValueError("light-bath population is outside physical bounds")


def write_arrays(output: Path, arrays: dict[str, np.ndarray]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, values in arrays.items():
        np.save(output / f"{name}.npy", values, allow_pickle=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--matlab-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    arrays = open_ising()
    light_arrays, analytic_diagnostics = light_bath()
    arrays.update(light_arrays)
    validate_arrays(arrays)
    if args.output_dir:
        write_arrays(args.output_dir, arrays)

    report: dict[str, Any] = {
        "schema_version": 1,
        "independent_implementation": "scipy.sparse.linalg.expm_multiply",
        "artifact_shapes": {key: list(value) for key, value in SHAPES.items()},
        "analytic_cross_check": analytic_diagnostics,
        "matlab_comparison": {
            "performed": False,
            "passed": False,
            "reason": "no --matlab-dir supplied",
        },
    }
    if args.matlab_dir:
        matlab = load_matlab(args.matlab_dir)
        validate_arrays(matlab)
        report["matlab_comparison"] = {
            "performed": True,
            **compare(arrays, matlab),
        }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if args.matlab_dir and not report["matlab_comparison"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
