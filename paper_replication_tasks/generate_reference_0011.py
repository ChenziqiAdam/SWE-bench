#!/usr/bin/env python3
"""Regenerate the fixed-seed Figure 1 reference for replication task 0011."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
TASK_ID = "scibench_replication_0011"
OUTPUT = ROOT / TASK_ID / "hidden" / "gold_artifacts"
SEEDS = 4096
PARTICLES = 128
STEPS = 128
DIMENSIONS = 3
DIFFUSION = 1.0
JUMP_SIZE = 2.4494897428
SOURCE_COMMIT = "9141e4edcddc386cdf10a9201d70aba1abaeb66c"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def positions_for_seed(seed: int) -> np.ndarray:
    rng = np.random.RandomState(seed)
    choices = rng.choice(6, size=(PARTICLES, STEPS))
    moves = np.zeros((6, DIMENSIONS), dtype=np.int64)
    moves[0, 0], moves[1, 0] = 1, -1
    moves[2, 1], moves[3, 1] = 1, -1
    moves[4, 2], moves[5, 2] = 1, -1
    positions = np.zeros((PARTICLES, STEPS + 1, DIMENSIONS), dtype=np.int64)
    positions[:, 1:] = np.cumsum(moves[choices], axis=1)
    return positions


def msd_from_autocorrelation(positions: np.ndarray) -> np.ndarray:
    """Compute all time-origin MSD values; integer sums are recovered exactly."""
    count = positions.shape[1]
    fft = np.fft.rfft(positions, n=2 * count, axis=1)
    correlations = np.fft.irfft(fft.conj() * fft, n=2 * count, axis=1)
    correlations = np.rint(correlations[:, :count]).astype(np.int64)
    square = np.sum(positions * positions, axis=2, dtype=np.int64)
    prefix = np.cumsum(square, axis=1, dtype=np.int64)
    total = prefix[:, -1]
    values = np.empty(STEPS, dtype=np.float64)
    for lag in range(1, STEPS + 1):
        left = prefix[:, count - lag - 1] if count - lag - 1 >= 0 else 0
        right = total - prefix[:, lag - 1]
        cross = np.sum(correlations[:, lag, :], axis=1, dtype=np.int64)
        squared_displacement_sum = left + right - 2 * cross
        values[lag - 1] = squared_displacement_sum.sum() / (
            PARTICLES * (count - lag)
        )
    return values * JUMP_SIZE**2


def msd_direct(positions: np.ndarray) -> np.ndarray:
    positions = positions.astype(np.float64) * JUMP_SIZE
    values = np.empty(STEPS, dtype=np.float64)
    for lag in range(1, STEPS + 1):
        delta = positions[:, lag:] - positions[:, :-lag]
        values[lag - 1] = np.mean(np.sum(delta * delta, axis=2))
    return values


def regression_outputs(msd: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    # The official Figure 1 code excludes the final lag already absent from
    # ``true_msd[:, 1:]`` because its stored array includes lags 1..128.
    selected = msd[:, 1:]
    covariance = np.cov(selected.T)
    times = np.arange(1, STEPS, dtype=np.float64)
    design = np.column_stack((times, np.ones(times.size)))
    identity = np.eye(times.size)
    diagonal = np.diag(np.diag(covariance))

    estimates = []
    uncertainties = []
    for weight in (
        identity,
        np.linalg.pinv(diagonal, rcond=1e-15),
        np.linalg.pinv(covariance, rcond=1e-15),
    ):
        normal_inverse = np.linalg.inv(design.T @ weight @ design)
        beta = normal_inverse @ design.T @ weight @ selected.T
        estimates.append(beta[0] / (2 * DIMENSIONS))
        uncertainties.append(
            float(np.sqrt(normal_inverse[0, 0]) / (2 * DIMENSIONS))
        )

    # Match scipy.stats.linregress's per-replicate OLS slope standard error.
    fitted = design @ np.linalg.inv(design.T @ design) @ design.T @ selected.T
    residual = selected.T - fitted
    sxx = np.sum((times - times.mean()) ** 2)
    ols_stderr = np.sqrt(np.sum(residual * residual, axis=0) / (times.size - 2) / sxx)
    uncertainties[0] = float(np.mean(ols_stderr) / (2 * DIMENSIONS))

    diffusion_estimates = np.asarray(estimates)
    names = ("OLS", "WLS", "GLS")
    summary = {
        name: {
            "population_mean": float(diffusion_estimates[index].mean()),
            "population_standard_deviation": float(
                diffusion_estimates[index].std(ddof=0)
            ),
            "analytical_uncertainty": uncertainties[index],
        }
        for index, name in enumerate(names)
    }
    return covariance, diffusion_estimates, summary


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    previous = {}
    for name in ("msd", "covariance", "diffusion_estimates"):
        path = OUTPUT / f"{name}.npy"
        if path.is_file():
            previous[name] = np.load(path, allow_pickle=False)
    previous_summary = (
        json.loads((OUTPUT / "summary.json").read_text(encoding="utf-8"))
        if (OUTPUT / "summary.json").is_file()
        else None
    )
    msd = np.empty((SEEDS, STEPS - 1), dtype=np.float64)
    direct_errors = []
    for seed in range(SEEDS):
        positions = positions_for_seed(seed)
        all_lags = msd_from_autocorrelation(positions)
        direct_errors.append(
            float(np.max(np.abs(all_lags - msd_direct(positions))))
        )
        msd[seed] = all_lags[1:]

    covariance, estimates, summary = regression_outputs(
        np.column_stack((np.zeros(SEEDS), msd))
    )
    repeat_errors = {
        "msd": (
            float(np.max(np.abs(previous["msd"] - msd)))
            if "msd" in previous and previous["msd"].shape == msd.shape
            else 0.0
        ),
        "covariance": (
            float(np.max(np.abs(previous["covariance"] - covariance)))
            if "covariance" in previous
            and previous["covariance"].shape == covariance.shape
            else 0.0
        ),
        "diffusion_estimates": (
            float(np.max(np.abs(previous["diffusion_estimates"] - estimates)))
            if "diffusion_estimates" in previous
            and previous["diffusion_estimates"].shape == estimates.shape
            else 0.0
        ),
        "summary": 0.0,
    }
    if previous_summary:
        repeat_errors["summary"] = max(
            abs(previous_summary[method][field] - value)
            for method, fields in summary.items()
            for field, value in fields.items()
        )
    np.save(OUTPUT / "msd.npy", msd, allow_pickle=False)
    np.save(OUTPUT / "covariance.npy", covariance, allow_pickle=False)
    np.save(OUTPUT / "diffusion_estimates.npy", estimates, allow_pickle=False)
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    tolerances = {
        "msd_max_abs": max(
            1e-12,
            10 * max(max(direct_errors, default=0.0), repeat_errors["msd"]),
        ),
        "covariance_max_abs": max(1e-10, 10 * repeat_errors["covariance"]),
        "diffusion_estimates_max_abs": max(
            1e-11, 10 * repeat_errors["diffusion_estimates"]
        ),
        "summary_absolute": max(1e-11, 10 * repeat_errors["summary"]),
        "psd_eigenvalue_floor": -1e-10,
    }
    record = {
        "schema_version": 1,
        "experiment": "figure_1_fixed_seed_random_walk",
        "source_release": "1.0.0",
        "source_commit": SOURCE_COMMIT,
        "official_source_files": {
            "Snakefile": "eabccb9e5279abd831664535a7b5113ddd6fe7e52012f45bc24f7dcc59d68a6a",
            "src/code/random_walks/random_walk.py": (
                "d76634ffdf789479f2c72535f1c813a39d93a1e5216ff85fc1995ebf9fc3dafc"
            ),
            "src/code/random_walks/numerical_rw.py": (
                "cb0952fb98ec7b7582db5456d8ebcb6dce70eb5d6e92069a32d3c2bdb83e609e"
            ),
            "src/code/random_walks/glswlsols.py": (
                "6abe46289cbd1c6f741db35a3c363d7911c17ca7d70d21c5d2497543a2f05e32"
            ),
            "src/tex/ms.tex": (
                "8f28c63e9cd1e32fbe938daee122baec19cc40cc34e817f49ad4bd827165735c"
            ),
        },
        "parameters": {
            "seeds": SEEDS,
            "seed_sequence": [0, SEEDS - 1],
            "particles": PARTICLES,
            "steps": STEPS,
            "dimensions": DIMENSIONS,
            "diffusion_coefficient": DIFFUSION,
            "jump_size": JUMP_SIZE,
        },
        "implementation_cross_check": {
            "method": "batched FFT autocorrelation versus direct time-origin displacements",
            "checked_seeds": SEEDS,
            "maximum_msd_absolute_error": max(direct_errors, default=0.0),
        },
        "repeat_clean_run_cross_check": {
            "maximum_absolute_errors": repeat_errors,
            "previous_artifacts_present": bool(previous),
        },
        "tolerance_policy": (
            "maximum observed implementation discrepancy times ten, or the stated "
            "floating-point numerical floor, whichever is larger"
        ),
        "tolerances": tolerances,
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "command": "python paper_replication_tasks/generate_reference_0011.py",
        "generator_sha256": sha256(Path(__file__)),
        "artifacts": {},
    }
    for name in ("msd.npy", "covariance.npy", "diffusion_estimates.npy", "summary.json"):
        path = OUTPUT / name
        record["artifacts"][name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    record_path = OUTPUT / "reference_generation.json"
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
