#!/usr/bin/env python3
"""Curator-only JSON adapters for pinned official repositories.

The adapters only inject parameters and normalize JSON.  They deliberately fail
when a case lacks parameters needed by the official experiment.
"""

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


def kinetics(checkout: Path, case: dict[str, Any]) -> dict[str, Any]:
    """Execute patched numerical blocks from the pinned OLS and WLS scripts."""
    global LAST_RAW
    if case["rng"] != "numpy.random.Generator.PCG64":
        raise ValueError("official ols.py uses numpy.default_rng")

    replacements = {
        "rng = np.random.default_rng(1)": f"rng = np.random.default_rng({int(case['seed'])!r})",
        "k = 0.15": f"k = {float(case['rate_constant'])!r}",
        "A0 = 7.5": f"A0 = {float(case['initial_concentration'])!r}",
        "t = np.arange(2, 22, 2)": f"t = np.asarray({case['time_grid']!r}, dtype=float)",
        "scale = 0.3": f"scale = {float(case['noise_std'])!r}",
        "size = int(2 ** 15)": f"size = {int(case['replicates'])!r}",
    }

    def execute(script_name: str) -> dict[str, Any]:
        source = (checkout / f"src/scripts/{script_name}.py").read_text(encoding="utf-8")
        if "return A0 * np.exp(-1 * k  * t)" not in source or "figsize =" not in source:
            raise RuntimeError(f"pinned official numerical block changed: {script_name}.py")
        patched = "import numpy as np\nfrom scipy.optimize import curve_fit\n\n" + source[
            source.index("rng = np.random.default_rng(1)"):source.index("figsize =")
        ]
        for old, new in replacements.items():
            if old not in patched:
                raise RuntimeError(f"parameter anchor missing in {script_name}.py: {old}")
            patched = patched.replace(old, new, 1)
        namespace: dict[str, Any] = {}
        exec(compile(patched, str(checkout / f"src/scripts/{script_name}.py"), "exec"), namespace)
        return namespace

    ols_run, wls_run = execute("ols"), execute("wls")
    if not np.array_equal(ols_run["At"], wls_run["At"]):
        raise RuntimeError("pinned OLS and WLS scripts generated different observations")
    rate = float(case["rate_constant"])
    ols_values = np.asarray(ols_run["k_lin"])
    wls_values = np.asarray(wls_run["k_lin"])
    nonlinear_values = np.asarray(ols_run["k_non"])

    def summary(values):
        normalized = np.asarray(values) / rate
        return {"mean": normalized.mean(), "ci95": np.percentile(normalized, [2.5, 97.5])}

    LAST_RAW = finite({
        "observations": ols_run["At"],
        "linear_ols_estimates": ols_values,
        "linear_wls_estimates": wls_values,
        "nonlinear_estimates": nonlinear_values,
    })
    return finite({"linear_ols": summary(ols_values), "linear_wls": summary(wls_values), "nonlinear": summary(nonlinear_values)})


def spin_curves(checkout: Path, case: dict[str, Any]) -> dict[str, Any]:
    global LAST_RAW
    analytic = load_module("official_single_spin_bz_analytic", checkout / "python/analytic.py")
    temperature = np.asarray(case["temperature_grid"], dtype=float)
    analytic.asd.g_muB_by_kB = float(case["field_scale_kelvin"])
    functions = {
        "quantum": analytic.quantum_state_sz,
        "classical": analytic.classical_limit_sz,
    }
    curves = {name: functions[name](float(case["spin"]), temperature) for name in case["approximations"]}
    LAST_RAW = finite({"temperature": temperature, "curves": curves})
    return finite({"temperature": temperature, "curves": curves})


def floquet_dmd(checkout: Path, case: dict[str, Any]) -> dict[str, Any]:
    required = {"w0", "w1", "drive_amplitude", "sim_discretization", "periods", "measurements_per_period", "training_periods", "prediction_steps"}
    missing = required - set(case)
    if missing:
        raise ValueError(f"official notebook quantum-system parameters missing: {sorted(missing)}")
    import qutip as qt
    import dmdlab as dmd

    w0, w1 = float(case["w0"]), float(case["w1"])
    omega, delta = 2 * np.pi * w1, 2 * np.pi * w0
    discretization, periods = int(case["sim_discretization"]), int(case["periods"])
    period = 2 * np.pi / omega
    times = np.linspace(0, periods * period, periods * discretization, endpoint=False)
    drive = float(case["drive_amplitude"])
    hamiltonian = [delta / 2 * qt.sigmaz(), [qt.sigmax(), lambda t, args: drive * np.cos(omega * t)]]
    result = qt.mesolve(hamiltonian, qt.basis(2, 1), times, [], [qt.sigmax(), qt.sigmay(), qt.sigmaz()])
    measurements = int(case["measurements_per_period"])
    skip = discretization // measurements
    sampled = np.asarray(result.expect)[:, ::skip]
    snapshots = sampled.T.reshape(-1, measurements * 3).T
    training = int(case["training_periods"])
    train_times = times[::discretization][:training]
    model = dmd.DMD.from_full(snapshots[:, :training], train_times, threshold_type="percent", threshold=1e-3)
    steps = int(case["prediction_steps"])
    prediction_times = np.arange(steps, dtype=float) * period
    prediction = model.predict_dst(prediction_times, snapshots[:, training])
    return finite({"eigenvalues": np.linalg.eigvals(model.A), "prediction": prediction})


def random_walk(checkout: Path, case: dict[str, Any]) -> dict[str, Any]:
    global LAST_RAW
    official = load_module("official_msd_random_walk", checkout / "src/code/random_walks/random_walk.py")
    if case["rng"] != "numpy.random.RandomState":
        raise ValueError("official walk() requires RandomState")
    atoms, steps, jump = int(case["atoms"]), int(case["steps"]), float(case["jump_size"])
    start, stop = map(int, case["seed_range"])
    curves = []
    for seed in range(start, stop):
        displacements, _ = official.get_disp3d(official.walk, steps, atoms, jump, np.random.RandomState(seed))
        curves.append([np.mean(np.sum(value * value, axis=-1)) for value in displacements])
    msd = np.asarray(curves)[:, 1:]
    time = np.arange(1, steps, dtype=float)
    regression_path = checkout / "src/code/random_walks/glswlsols.py"
    source = regression_path.read_text(encoding="utf-8")
    start_marker, stop_marker = "true_cov = np.cov(true_msd.T)", "np.savez("
    if start_marker not in source or stop_marker not in source:
        raise RuntimeError("pinned official GLS/WLS/OLS numerical block changed")
    patched = source[source.index(start_marker):source.index(stop_marker)]
    # Compatibility definition: SciPy 1.12.0 pinv controls rank-deficient
    # covariance behavior. All remaining regression expressions are executed
    # verbatim from the pinned official script.
    patched = patched.replace("np.linalg.pinv", "scipy_pinv")
    namespace: dict[str, Any] = {
        "np": np,
        "true_msd": msd,
        "length": steps,
        "linregress": __import__("scipy.stats", fromlist=["linregress"]).linregress,
        "scipy_pinv": __import__("scipy.linalg", fromlist=["pinv"]).pinv,
    }
    exec(compile(patched, str(regression_path), "exec"), namespace)
    populations = {"GLS": namespace["g1"], "WLS": namespace["g2"], "OLS": namespace["g3"]}
    estimates = {
        name: {"mean": values.mean(), "std": values.std(ddof=0)}
        for name, values in populations.items()
    }
    LAST_RAW = finite({
        "msd_by_seed": msd,
        "covariance": namespace["true_cov"],
        "diffusion_populations": populations,
    })
    return finite({"time": time, "mean_msd": msd.mean(axis=0), "diffusion": estimates})


def anisotropy(checkout: Path, case: dict[str, Any]) -> dict[str, Any]:
    constants = case.get("physical_constants")
    if not isinstance(constants, dict):
        raise ValueError("physical_constants with kB, g, and mu_B is required")
    analytic = load_module("official_single_spin_anisotropy_analytic", checkout / "python/analytic.py")
    spin = float(case["spin"])
    beta = 1 / (float(constants["kB"]) * np.asarray(case["temperature_grid"], dtype=float))
    orientation = np.asarray(case["orientation_grid"], dtype=float)
    a1 = float(case["linear_energy"])
    a2 = float(case["anisotropy_ratio"]) * a1
    h_expr = analytic.eff_hamiltonian_classical_exact(int(2 * spin))
    h_fn = analytic.lambdify([analytic.B, analytic.C, analytic.D, analytic.n], h_expr, "numpy")
    f_fn = analytic.generate_field_function_exact(spin)
    hamiltonian = np.asarray([[h_fn(b, a2, a1, n) for n in orientation] for b in beta])
    field = np.asarray([[f_fn(b, a2, a1, n, constants["g"], constants["mu_B"]) for n in orientation] for b in beta])
    return finite({"temperature": case["temperature_grid"], "orientation": orientation, "hamiltonian": hamiltonian, "effective_field": field})


ADAPTERS = {"0007": kinetics, "0008": spin_curves, "0009": floquet_dmd, "0011": random_walk, "0012": anisotropy}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=sorted(ADAPTERS), required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    case = json.loads(args.input.read_text(encoding="utf-8"))
    value = ADAPTERS[args.task](args.checkout.resolve(), case)
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
