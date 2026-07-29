#!/usr/bin/env python3
"""Generate the deterministic core-method reference for replication task 0012."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
from scipy import constants, special


ROOT = Path(__file__).resolve().parent
TASK_ID = "scibench_replication_0012"
OUTPUT = ROOT / TASK_ID / "hidden" / "gold_artifacts"
SOURCE_COMMIT = "ba6f6cbbc665ea55e48f852b2205fda07f0f760e"
TEMPERATURE = np.linspace(0.02, 10.0, 200, dtype=np.float64)
ORIENTATION = np.linspace(-0.98, 0.98, 201, dtype=np.float64)
SPINS = (0.5, 1.0, 1.5, 2.0)
RATIOS = (10.0, 0.0, -1.0, -10.0)
G_FACTOR = abs(constants.value("electron g factor"))
MU_B = constants.value("Bohr magneton")
K_B = constants.k
A1_OVER_KB = G_FACTOR * MU_B / K_B


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_form(spin: float, ratio: float) -> tuple[np.ndarray, np.ndarray]:
    """Pinned L-polynomial formulation in stereographic coordinates."""
    two_s = int(round(2 * spin))
    p = np.arange(two_s + 1, dtype=np.float64)
    log_c = (
        special.gammaln(two_s + 1)
        - special.gammaln(p + 1)
        - special.gammaln(two_s - p + 1)
    )
    u = ORIENTATION
    r2 = (1.0 - u) / (1.0 + u)
    log_r2 = np.log(r2)
    h = np.empty((TEMPERATURE.size, u.size), dtype=np.float64)
    b = np.empty_like(h)
    for index, temperature in enumerate(TEMPERATURE):
        tau = A1_OVER_KB / temperature
        log_terms = (
            log_c[:, None]
            + p[:, None] * log_r2[None, :]
            + tau
            * (ratio * p * p - (two_s * ratio + 1.0) * p)[:, None]
        )
        log_l = special.logsumexp(log_terms, axis=0)
        log_w = log_l - two_s * np.log1p(r2)
        h[index] = -log_w / tau
        posterior = np.exp(log_terms - log_l[None, :])
        d_log_l_du = np.sum(
            posterior * (-2.0 * p[:, None] / (1.0 - u * u)[None, :]),
            axis=0,
        )
        d_log_w_du = d_log_l_du + two_s / (1.0 + u)
        b[index] = d_log_w_du / (spin * tau)
    return h, b


def independent_form(spin: float, ratio: float) -> tuple[np.ndarray, np.ndarray]:
    """Independent coherent-basis matrix-element formulation."""
    two_s = int(round(2 * spin))
    p = np.arange(two_s + 1, dtype=np.float64)
    m = spin - p
    u = ORIENTATION
    log_probability = (
        np.asarray([math.log(math.comb(two_s, int(value))) for value in p])[:, None]
        + p[:, None] * np.log((1.0 - u) / 2.0)[None, :]
        + (two_s - p)[:, None] * np.log((1.0 + u) / 2.0)[None, :]
    )
    derivative = (
        (two_s - p)[:, None] / (1.0 + u)[None, :]
        - p[:, None] / (1.0 - u)[None, :]
    )
    h = np.empty((TEMPERATURE.size, u.size), dtype=np.float64)
    b = np.empty_like(h)
    reference_energy = spin + ratio * spin * spin
    for index, temperature in enumerate(TEMPERATURE):
        tau = A1_OVER_KB / temperature
        relative_energy = m + ratio * m * m - reference_energy
        log_terms = log_probability + tau * relative_energy[:, None]
        log_q = special.logsumexp(log_terms, axis=0)
        posterior = np.exp(log_terms - log_q[None, :])
        h[index] = -log_q / tau
        b[index] = np.sum(posterior * derivative, axis=0) / (spin * tau)
    return h, b


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    official: dict[str, np.ndarray] = {
        "temperature": TEMPERATURE,
        "orientation": ORIENTATION,
    }
    independent: dict[str, np.ndarray] = {
        "temperature": TEMPERATURE.copy(),
        "orientation": ORIENTATION.copy(),
    }
    for prefix, specifications in (
        ("figure2", [(spin, -2.0) for spin in SPINS]),
        ("figure3", [(1.0, ratio) for ratio in RATIOS]),
    ):
        official_h, official_b, independent_h, independent_b = [], [], [], []
        for spin, ratio in specifications:
            first_h, first_b = repository_form(spin, ratio)
            second_h, second_b = independent_form(spin, ratio)
            official_h.append(first_h)
            official_b.append(first_b)
            independent_h.append(second_h)
            independent_b.append(second_b)
        official[f"{prefix}_hamiltonian"] = np.asarray(official_h)
        official[f"{prefix}_field"] = np.asarray(official_b)
        independent[f"{prefix}_hamiltonian"] = np.asarray(independent_h)
        independent[f"{prefix}_field"] = np.asarray(independent_b)

    errors = {}
    for name, values in official.items():
        delta = values - independent[name]
        errors[name] = {
            "max_absolute": float(np.max(np.abs(delta), initial=0.0)),
            "rmse": float(np.sqrt(np.mean(delta * delta))),
        }
        if values.dtype != np.float64 or not np.isfinite(values).all():
            raise RuntimeError(f"invalid reference array: {name}")
        np.save(OUTPUT / f"{name}.npy", values, allow_pickle=False)

    h_error = max(
        errors[name]["max_absolute"] for name in errors if name.endswith("hamiltonian")
    )
    b_error = max(
        errors[name]["max_absolute"] for name in errors if name.endswith("field")
    )
    tolerances = {
        "grid_max_abs": 1e-14,
        "hamiltonian_max_abs": max(1e-11, 10 * h_error),
        "hamiltonian_rmse": max(1e-12, 10 * max(
            errors[name]["rmse"] for name in errors if name.endswith("hamiltonian")
        )),
        "field_max_abs": max(1e-10, 10 * b_error),
        "field_rmse": max(1e-11, 10 * max(
            errors[name]["rmse"] for name in errors if name.endswith("field")
        )),
        "identity_abs": 1e-9,
    }
    record = {
        "schema_version": 1,
        "experiment": "deterministic_effective_hamiltonian_core_method",
        "scope": "core_method_not_full_stochastic_asd_replication",
        "source_commit": SOURCE_COMMIT,
        "source_release": "v1.0.8",
        "paper_source": "arXiv:2404.19539v2/main1.tex",
        "paper_equations": ["partitionAlmostOk", "exactHam", "B_eff"],
        "curve_order": {
            "figure2_spins": list(SPINS),
            "figure2_anisotropy_ratio": -2.0,
            "figure3_spin": 1.0,
            "figure3_anisotropy_ratios": list(RATIOS),
        },
        "grids": {
            "temperature": "numpy.linspace(0.02,10.0,200), kelvin",
            "orientation": "numpy.linspace(-0.98,0.98,201), dimensionless u_z",
        },
        "output_conventions": {
            "hamiltonian": "(H_eff(u_z)-H_eff(1))/A1",
            "field": "B_eff_z/H_z = -(1/s) d[(H_eff-H_eff(1))/A1]/du_z",
        },
        "parameters": {
            "field_tesla": 1.0,
            "stress": 0.0,
            "g_factor": G_FACTOR,
            "mu_b_joule_per_tesla": MU_B,
            "k_b_joule_per_kelvin": K_B,
            "a1_over_kb_kelvin": A1_OVER_KB,
        },
        "routes": {
            "official": "pinned repository L-polynomial in stereographic radius",
            "independent": "coherent-basis diagonal matrix element and analytic derivative",
        },
        "implementation_cross_check": errors,
        "tolerance_policy": (
            "ten times the largest cross-route discrepancy or the documented "
            "floating-point floor, whichever is larger"
        ),
        "tolerances": tolerances,
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "scipy": __import__("scipy").__version__,
            "platform": platform.platform(),
        },
        "command": "python paper_replication_tasks/generate_reference_0012.py",
        "generator_sha256": sha256(Path(__file__)),
        "source_hashes": {
            "commit_archive": "c4ad694bb05862fb5537977c3128667d8c5c49cd8829e047ad1197acbf18ff41",
            "zenodo_v1.0.8": "4e159d40c40df7fb4186378ab45118ec1b2b30a6fbebd74e654e3b647fd7509e",
            "arxiv_v2_source": "efc4c6b34f724876478272dea9e7a93ef7a2acbacae4cd976654936be01e45f6",
            "main1.tex": "a95e00bcabc25f3f9fb2220c783d8194079d2a78fc0cdf2c67277f9263e11b2d"
        },
        "artifacts": {},
    }
    for name, values in official.items():
        path = OUTPUT / f"{name}.npy"
        record["artifacts"][path.name] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "shape": list(values.shape),
            "dtype": "float64",
        }
    (OUTPUT / "reference_generation.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"errors": errors, "tolerances": tolerances}, indent=2))


if __name__ == "__main__":
    main()
