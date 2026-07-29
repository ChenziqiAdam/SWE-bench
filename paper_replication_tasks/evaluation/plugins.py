"""Task-specific scientific checks. Metrics are always recomputed from artifacts."""

from __future__ import annotations

import itertools
import json
import math
import re
from pathlib import Path

import numpy as np
from scipy import linalg

from .framework import (
    Context,
    check_required_artifacts,
    sha256_file,
)


METRICS_0007 = (
    "lin_mean_ols",
    "non_mean_ols",
    "lin_ci_ols",
    "non_ci_ols",
    "lin_mean_wls",
    "non_mean_wls",
)


def _load_numbers(path: Path) -> list[float]:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text)
    if not matches:
        raise ValueError(f"expected numeric content in {path.name}")
    return [float(value) for value in matches]


def evaluate_0007(ctx: Context) -> None:
    expected = ctx.gold["reference"]
    tolerance = float(ctx.gold["tolerances"]["scalar_absolute"])
    required = [f"metric_{name}" for name in METRICS_0007]
    check_required_artifacts(ctx, required)
    for name in METRICS_0007:
        path = ctx.artifact_path(f"metric_{name}")
        try:
            values = _load_numbers(path) if path and path.is_file() else []
        except (OSError, UnicodeError, ValueError):
            values = []
        target_values = np.atleast_1d(np.asarray(expected[name], dtype=np.float64))
        actual_values = np.asarray(values, dtype=np.float64)
        passed = actual_values.shape == target_values.shape and bool(
            np.allclose(actual_values, target_values, rtol=0.0, atol=tolerance)
        )
        max_abs = (
            float(np.max(np.abs(actual_values - target_values), initial=0.0))
            if actual_values.shape == target_values.shape
            else math.inf
        )
        ctx.check(
            f"value_{name}",
            "scientific",
            passed,
            f"{name} must be within absolute tolerance {tolerance}",
            diagnostics={
                "actual": values,
                "expected": target_values.tolist(),
                "max_abs": max_abs,
                "absolute_tolerance": tolerance,
            },
        )


def _read_tsv(path: Path) -> np.ndarray:
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("TSV exceeds 128 MiB")
    # NumPy's ``savetxt`` defaults to whitespace even when the official files
    # use a .tsv suffix, so accept arbitrary ASCII whitespace as the delimiter.
    array = np.loadtxt(path, delimiter=None, ndmin=2)
    if array.dtype.kind not in "fiu" or not np.isfinite(array).all():
        raise ValueError("TSV contains non-finite or non-numeric data")
    return np.asarray(array, dtype=np.float64)


def evaluate_0008(ctx: Context) -> None:
    index = ctx.gold["artifact_index"]
    required = [row["id"] for row in index]
    check_required_artifacts(ctx, required)
    gold_root = ctx.gold_path.parent
    for row in index:
        artifact_id = row["id"]
        candidate_path = ctx.artifact_path(artifact_id)
        reference_path = gold_root / row["reference_path"]
        try:
            candidate = _read_tsv(candidate_path) if candidate_path else None
            reference = _read_tsv(reference_path)
            if candidate is None or candidate.shape != reference.shape:
                raise ValueError("shape mismatch")
            if not np.isfinite(reference).all():
                raise ValueError("trusted deterministic reference is non-finite")
            delta = candidate - reference
            max_abs = float(np.max(np.abs(delta), initial=0.0))
            rmse = float(np.sqrt(np.mean(delta * delta)))
            finite = math.isfinite(max_abs) and math.isfinite(rmse)
        except (OSError, ValueError):
            max_abs, rmse, finite = math.inf, math.inf, False
        max_limit = float(ctx.gold["tolerances"]["max_abs"])
        rmse_limit = float(ctx.gold["tolerances"]["rmse"])
        exact = bool(
            candidate_path
            and candidate_path.is_file()
            and reference_path.is_file()
            and sha256_file(candidate_path) == sha256_file(reference_path)
        )
        passed = finite and max_abs <= max_limit and rmse <= rmse_limit
        ctx.check(
            f"curve_{artifact_id}",
            "scientific",
            passed,
            f"{artifact_id} must satisfy numerical curve tolerances",
            diagnostics={
                "max_abs": max_abs,
                "rmse": rmse,
                "exact_hash": exact,
                "max_abs_limit": max_limit,
                "rmse_limit": rmse_limit,
            },
        )


ARRAYS_0009 = {
    "floquet_eigenvalues": (3, 2),
    "prediction_times": (32,),
    "prediction_trajectory": (3, 32),
}


def _safe_npy(path: Path, expected_shape: tuple[int, ...]) -> np.ndarray:
    if path.suffix != ".npy":
        raise ValueError("numeric artifacts must be .npy")
    array = np.load(path, mmap_mode="r", allow_pickle=False)
    if array.shape != expected_shape or array.dtype.kind not in "fiu":
        raise ValueError(f"expected numeric shape {expected_shape}, got {array.shape}")
    result = np.asarray(array, dtype=np.float64)
    if not np.isfinite(result).all():
        raise ValueError("array contains NaN or infinity")
    return result


def evaluate_0009(ctx: Context) -> None:
    check_required_artifacts(ctx, ARRAYS_0009)
    gold_root = ctx.gold_path.parent
    loaded: dict[str, np.ndarray | None] = {}
    targets: dict[str, np.ndarray] = {}
    for artifact_id, expected_shape in ARRAYS_0009.items():
        row = ctx.gold["artifact_index"][artifact_id]
        target = _safe_npy(gold_root / row["reference_path"], expected_shape)
        targets[artifact_id] = target
        path = ctx.artifact_path(artifact_id)
        try:
            actual = _safe_npy(path, expected_shape) if path else None
        except (OSError, ValueError):
            actual = None
        loaded[artifact_id] = actual

    actual_eigs = loaded["floquet_eigenvalues"]
    target_eigs = targets["floquet_eigenvalues"]
    eig_limit = float(ctx.gold["tolerances"]["eigenvalue_max_abs"])
    best_error = math.inf
    if actual_eigs is not None:
        actual_complex = actual_eigs[:, 0] + 1j * actual_eigs[:, 1]
        target_complex = target_eigs[:, 0] + 1j * target_eigs[:, 1]
        best_error = min(
            float(np.max(np.abs(actual_complex - target_complex[list(order)])))
            for order in itertools.permutations(range(3))
        )
    ctx.check(
        "floquet_eigenvalues",
        "scientific",
        best_error <= eig_limit,
        "Floquet eigenvalues must match as an unordered set",
        diagnostics={"best_max_abs": best_error, "max_abs_limit": eig_limit},
    )

    actual_times = loaded["prediction_times"]
    target_times = targets["prediction_times"]
    time_limit = float(ctx.gold["tolerances"]["time_max_abs"])
    time_error = (
        float(np.max(np.abs(actual_times - target_times), initial=0.0))
        if actual_times is not None
        else math.inf
    )
    ctx.check(
        "prediction_times",
        "scientific",
        time_error <= time_limit,
        "prediction time grid must match the benchmark protocol",
        diagnostics={"max_abs": time_error, "max_abs_limit": time_limit},
    )

    actual_trajectory = loaded["prediction_trajectory"]
    target_trajectory = targets["prediction_trajectory"]
    if actual_trajectory is None:
        trajectory_max, trajectory_rmse = math.inf, math.inf
    else:
        delta = actual_trajectory - target_trajectory
        trajectory_max = float(np.max(np.abs(delta), initial=0.0))
        trajectory_rmse = float(np.sqrt(np.mean(delta * delta)))
    max_limit = float(ctx.gold["tolerances"]["trajectory_max_abs"])
    rmse_limit = float(ctx.gold["tolerances"]["trajectory_rmse"])
    ctx.check(
        "prediction_trajectory",
        "scientific",
        trajectory_max <= max_limit and trajectory_rmse <= rmse_limit,
        "Floquet-DMD extrapolation trajectory must match the reference",
        diagnostics={
            "max_abs": trajectory_max,
            "rmse": trajectory_rmse,
            "max_abs_limit": max_limit,
            "rmse_limit": rmse_limit,
        },
    )


ARRAYS_0011 = {
    "msd": (4096, 127),
    "covariance": (127, 127),
    "diffusion_estimates": (3, 4096),
}


def _max_abs(left: np.ndarray | None, right: np.ndarray) -> float:
    if left is None or left.shape != right.shape:
        return math.inf
    return float(np.max(np.abs(left - right), initial=0.0))


def _regression_0011(
    msd: np.ndarray, covariance: np.ndarray
) -> tuple[np.ndarray, dict[str, dict[str, float]]]:
    times = np.arange(1, 128, dtype=np.float64)
    design = np.column_stack((times, np.ones(times.size)))
    weights = (
        np.eye(times.size),
        linalg.pinv(np.diag(np.diag(covariance)), atol=0.0, rtol=1e-15),
        linalg.pinv(covariance, atol=0.0, rtol=1e-15),
    )
    estimates = []
    uncertainty = []
    for weight in weights:
        inverse = np.linalg.inv(design.T @ weight @ design)
        beta = inverse @ design.T @ weight @ msd.T
        estimates.append(beta[0] / 6.0)
        uncertainty.append(float(np.sqrt(inverse[0, 0]) / 6.0))
    fitted = design @ np.linalg.inv(design.T @ design) @ design.T @ msd.T
    residual = msd.T - fitted
    sxx = np.sum((times - times.mean()) ** 2)
    uncertainty[0] = float(
        np.mean(np.sqrt(np.sum(residual * residual, axis=0) / 125.0 / sxx)) / 6.0
    )
    values = np.asarray(estimates)
    summary = {
        name: {
            "population_mean": float(values[index].mean()),
            "population_standard_deviation": float(values[index].std(ddof=0)),
            "analytical_uncertainty": uncertainty[index],
        }
        for index, name in enumerate(("OLS", "WLS", "GLS"))
    }
    return values, summary


def evaluate_0011(ctx: Context) -> None:
    required = (*ARRAYS_0011, "summary")
    check_required_artifacts(ctx, required)
    root = ctx.gold_path.parent
    loaded: dict[str, np.ndarray | None] = {}
    targets: dict[str, np.ndarray] = {}
    for artifact_id, shape in ARRAYS_0011.items():
        row = ctx.gold["artifact_index"][artifact_id]
        reference_path = root / row["reference_path"]
        if sha256_file(reference_path) != row["sha256"]:
            raise RuntimeError(f"trusted reference hash mismatch: {artifact_id}")
        reference = _safe_npy(reference_path, shape)
        targets[artifact_id] = reference
        path = ctx.artifact_path(artifact_id)
        try:
            loaded[artifact_id] = _safe_npy(path, shape) if path else None
        except (OSError, ValueError):
            loaded[artifact_id] = None

    tolerances = ctx.gold["tolerances"]
    msd_error = _max_abs(loaded["msd"], targets["msd"])
    ctx.check(
        "fixed_seed_msd",
        "scientific",
        msd_error <= float(tolerances["msd_max_abs"]),
        "all fixed-seed MSD curves must match",
        diagnostics={"max_abs": msd_error, "limit": tolerances["msd_max_abs"]},
    )
    submitted_covariance = loaded["covariance"]
    if submitted_covariance is None:
        symmetry_error, minimum_eigenvalue = math.inf, -math.inf
    else:
        symmetry_error = float(np.max(np.abs(submitted_covariance - submitted_covariance.T)))
        minimum_eigenvalue = float(np.linalg.eigvalsh(submitted_covariance).min())
    ctx.check(
        "covariance_structure",
        "scientific",
        symmetry_error <= float(tolerances["covariance_max_abs"])
        and minimum_eigenvalue >= float(tolerances["psd_eigenvalue_floor"]),
        "covariance must be symmetric and positive semidefinite",
        diagnostics={
            "symmetry_max_abs": symmetry_error,
            "minimum_eigenvalue": minimum_eigenvalue,
        },
    )

    submitted_msd = loaded["msd"]
    if submitted_msd is None:
        recomputed_covariance = targets["covariance"]
        covariance_error = math.inf
    else:
        recomputed_covariance = np.cov(submitted_msd.T)
        covariance_error = _max_abs(submitted_covariance, recomputed_covariance)
    ctx.check(
        "covariance_recomputed",
        "scientific",
        covariance_error <= float(tolerances["covariance_max_abs"]),
        "covariance must be recomputed from submitted MSD curves",
        diagnostics={
            "max_abs": covariance_error,
            "limit": tolerances["covariance_max_abs"],
        },
    )
    covariance_gold_error = _max_abs(submitted_covariance, targets["covariance"])
    ctx.check(
        "covariance_reference",
        "scientific",
        covariance_gold_error <= float(tolerances["covariance_max_abs"]),
        "covariance must match the fixed experiment",
        diagnostics={"max_abs": covariance_gold_error},
    )

    recomputed_estimates, recomputed_summary = _regression_0011(
        submitted_msd if submitted_msd is not None else targets["msd"],
        submitted_covariance if submitted_covariance is not None else recomputed_covariance,
    )
    estimate_consistency = _max_abs(loaded["diffusion_estimates"], recomputed_estimates)
    estimate_reference = _max_abs(
        loaded["diffusion_estimates"], targets["diffusion_estimates"]
    )
    estimate_limit = float(tolerances["diffusion_estimates_max_abs"])
    ctx.check(
        "diffusion_estimates_recomputed",
        "scientific",
        estimate_consistency <= estimate_limit,
        "OLS/WLS/GLS rows must be recomputed in the required order",
        diagnostics={"max_abs": estimate_consistency, "limit": estimate_limit},
    )
    ctx.check(
        "diffusion_estimates_reference",
        "scientific",
        estimate_reference <= estimate_limit,
        "diffusion estimates must match the fixed experiment",
        diagnostics={"max_abs": estimate_reference, "limit": estimate_limit},
    )

    summary_path = ctx.artifact_path("summary")
    summary_reference_row = ctx.gold["artifact_index"]["summary"]
    summary_reference_path = root / summary_reference_row["reference_path"]
    if sha256_file(summary_reference_path) != summary_reference_row["sha256"]:
        raise RuntimeError("trusted reference hash mismatch: summary")
    try:
        reference_summary = json.loads(
            summary_reference_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("trusted summary reference is invalid") from exc
    try:
        if not summary_path or summary_path.stat().st_size > 128 * 1024:
            raise ValueError("invalid summary file")
        submitted_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        submitted_summary = {}
    summary_limit = float(tolerances["summary_absolute"])
    summary_errors = {}
    summary_reference_errors = {}
    valid_summary = set(submitted_summary) == {"OLS", "WLS", "GLS"}
    for method, fields in recomputed_summary.items():
        row = submitted_summary.get(method, {})
        reference_row = reference_summary.get(method, {})
        valid_summary = valid_summary and isinstance(row, dict) and set(row) == set(fields)
        for field, expected in fields.items():
            value = row.get(field) if isinstance(row, dict) else None
            error = (
                abs(float(value) - expected)
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                else math.inf
            )
            summary_errors[f"{method}.{field}"] = error
            reference_value = (
                reference_row.get(field) if isinstance(reference_row, dict) else None
            )
            reference_error = (
                abs(float(value) - float(reference_value))
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and isinstance(reference_value, (int, float))
                and not isinstance(reference_value, bool)
                and math.isfinite(float(reference_value))
                else math.inf
            )
            summary_reference_errors[f"{method}.{field}"] = reference_error
            valid_summary = (
                valid_summary
                and error <= summary_limit
                and reference_error <= summary_limit
            )
    ctx.check(
        "summary_recomputed",
        "scientific",
        valid_summary,
        "summary must agree with the submitted numerical arrays",
        diagnostics={
            "recomputed_absolute_errors": summary_errors,
            "reference_absolute_errors": summary_reference_errors,
            "limit": summary_limit,
        },
    )


ARRAYS_0012 = {
    "temperature": (200,),
    "orientation": (201,),
    "figure2_hamiltonian": (4, 200, 201),
    "figure2_field": (4, 200, 201),
    "figure3_hamiltonian": (4, 200, 201),
    "figure3_field": (4, 200, 201),
}


def _safe_0012(path: Path, shape: tuple[int, ...]) -> np.ndarray:
    if path.suffix != ".npy" or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("invalid NPY size or suffix")
    values = np.load(path, mmap_mode="r", allow_pickle=False)
    if values.shape != shape or values.dtype != np.dtype("<f8"):
        raise ValueError("expected exact float64 shape")
    result = np.asarray(values)
    if not np.isfinite(result).all():
        raise ValueError("non-finite array")
    return result


def _core_checkpoint_0012(
    spin: float, ratio: float, temperature: float, u: float, a1_over_kb: float
) -> tuple[float, float]:
    two_s = int(round(2 * spin))
    p = np.arange(two_s + 1, dtype=np.float64)
    m = spin - p
    tau = a1_over_kb / temperature
    reference = spin + ratio * spin * spin
    log_terms = np.asarray(
        [
            math.log(math.comb(two_s, int(index)))
            + index * math.log((1.0 - u) / 2.0)
            + (two_s - index) * math.log((1.0 + u) / 2.0)
            + tau * (m[index] + ratio * m[index] ** 2 - reference)
            for index in range(two_s + 1)
        ]
    )
    maximum = float(np.max(log_terms))
    weight = np.exp(log_terms - maximum)
    log_q = maximum + math.log(float(weight.sum()))
    derivative = np.asarray(
        [
            (two_s - index) / (1.0 + u) - index / (1.0 - u)
            for index in range(two_s + 1)
        ]
    )
    return -log_q / tau, float(np.dot(weight, derivative) / weight.sum() / (spin * tau))


def evaluate_0012(ctx: Context) -> None:
    check_required_artifacts(ctx, ARRAYS_0012)
    root = ctx.gold_path.parent
    loaded: dict[str, np.ndarray | None] = {}
    targets: dict[str, np.ndarray] = {}
    for artifact_id, shape in ARRAYS_0012.items():
        row = ctx.gold["artifact_index"][artifact_id]
        reference_path = root / row["reference_path"]
        if sha256_file(reference_path) != row["sha256"]:
            raise RuntimeError(f"trusted reference hash mismatch: {artifact_id}")
        targets[artifact_id] = _safe_0012(reference_path, shape)
        path = ctx.artifact_path(artifact_id)
        try:
            loaded[artifact_id] = _safe_0012(path, shape) if path else None
        except (OSError, ValueError):
            loaded[artifact_id] = None

    tolerances = ctx.gold["tolerances"]
    for artifact_id in ("temperature", "orientation"):
        error = _max_abs(loaded[artifact_id], targets[artifact_id])
        ctx.check(
            artifact_id,
            "scientific",
            error <= float(tolerances["grid_max_abs"]),
            "complete parameter grid must match",
            diagnostics={"max_abs": error, "limit": tolerances["grid_max_abs"]},
        )

    for artifact_id in (
        "figure2_hamiltonian",
        "figure2_field",
        "figure3_hamiltonian",
        "figure3_field",
    ):
        actual = loaded[artifact_id]
        if actual is None:
            max_abs, rmse = math.inf, math.inf
        else:
            delta = actual - targets[artifact_id]
            max_abs = float(np.max(np.abs(delta), initial=0.0))
            rmse = float(np.sqrt(np.mean(delta * delta)))
        kind = "hamiltonian" if artifact_id.endswith("hamiltonian") else "field"
        ctx.check(
            artifact_id,
            "scientific",
            max_abs <= float(tolerances[f"{kind}_max_abs"])
            and rmse <= float(tolerances[f"{kind}_rmse"]),
            f"{kind} array must satisfy both numerical tolerances",
            diagnostics={
                "max_abs": max_abs,
                "rmse": rmse,
                "max_abs_limit": tolerances[f"{kind}_max_abs"],
                "rmse_limit": tolerances[f"{kind}_rmse"],
            },
        )

    temperature = loaded["temperature"]
    orientation = loaded["orientation"]
    checkpoint_errors = []
    valid_checkpoints = temperature is not None and orientation is not None
    a1_over_kb = float(ctx.gold["experiment"]["a1_over_kb_kelvin"])
    specifications = (
        (
            "figure2",
            tuple(float(x) for x in ctx.gold["curve_order"]["figure2_spins"]),
            (-2.0,) * 4,
        ),
        (
            "figure3",
            (1.0,) * 4,
            tuple(
                float(x)
                for x in ctx.gold["curve_order"]["figure3_anisotropy_ratios"]
            ),
        ),
    )
    for prefix, spins, ratios in specifications:
        h = loaded[f"{prefix}_hamiltonian"]
        b = loaded[f"{prefix}_field"]
        if h is None or b is None or temperature is None or orientation is None:
            valid_checkpoints = False
            continue
        for row, (spin, ratio) in enumerate(zip(spins, ratios)):
            for t_index, u_index in ((0, 0), (73, 99), (199, 200)):
                expected_h, expected_b = _core_checkpoint_0012(
                    spin,
                    ratio,
                    float(temperature[t_index]),
                    float(orientation[u_index]),
                    a1_over_kb,
                )
                h_error = abs(float(h[row, t_index, u_index]) - expected_h)
                b_error = abs(float(b[row, t_index, u_index]) - expected_b)
                checkpoint_errors.extend((h_error, b_error))
                valid_checkpoints = (
                    valid_checkpoints
                    and h_error <= float(tolerances["hamiltonian_max_abs"])
                    and b_error <= float(tolerances["field_max_abs"])
                )
    ctx.check(
        "independent_core_checkpoints",
        "scientific",
        valid_checkpoints,
        "selected values must pass independent coherent-state recomputation",
        diagnostics={"maximum_absolute_error": max(checkpoint_errors, default=math.inf)},
    )


PLUGINS = {
    "scibench_replication_0007": evaluate_0007,
    "scibench_replication_0008": evaluate_0008,
    "scibench_replication_0009": evaluate_0009,
    "scibench_replication_0011": evaluate_0011,
    "scibench_replication_0012": evaluate_0012,
}
