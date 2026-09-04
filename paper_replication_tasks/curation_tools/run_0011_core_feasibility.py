#!/usr/bin/env python3
"""Run 0011_core deterministic replay and independent posterior feasibility gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from kinisi_core_adapter import ANALYSIS_COMMIT, COMMIT, DIFFUSION_SHA256, solve as official_solve
from kinisi_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "curation_reports/official_runs/0011_core_feasibility"
REPORT = ROOT / "curation_reports/0011_core_feasibility.json"
PILOT_SEEDS = (11011, 11029, 11047, 11071, 11101)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def gamma_rows(seed: int, times: list[float], means: list[float], sizes: list[int], shapes: list[float]) -> list[list[float]]:
    rng = np.random.RandomState(seed)
    return [rng.gamma(shape, mean / shape, size=size).tolist() for mean, size, shape in zip(means, sizes, shapes)]


def provisional_cases() -> list[dict]:
    t1 = [0.5, 1, 2, 3, 5, 8, 12, 17]
    m1 = [0.35 + 6 * 0.72 * t for t in t1]
    c1 = {
        "lag_times": t1,
        "squared_displacement_samples": gamma_rows(1111, t1, m1, [96] * 8, [18] * 8),
        "independent_sample_counts": [96, 72, 48, 36, 24, 16, 11, 8],
        "dimension": 3,
        "fit_start": 1,
        "condition_limit": 1e8,
        "mcmc_seed": PILOT_SEEDS[0],
    }

    t2 = [1, 2, 4, 7, 11, 16, 23]
    m2 = [1.2 + 2 * 0.006 * t for t in t2]
    c2 = {
        "lag_times": t2,
        "squared_displacement_samples": gamma_rows(1122, t2, m2, [48] * 7, [5, 5, 4, 4, 3, 3, 3]),
        "independent_sample_counts": [30, 22, 15, 10, 7, 5, 3],
        "dimension": 1,
        "fit_start": 1,
        "condition_limit": 1e5,
        "mcmc_seed": PILOT_SEEDS[0],
    }

    t3 = [0.2, 0.6, 1.3, 2.1, 3.4, 5.5, 8.9, 14.4, 22.0]
    means3 = [0.8 + 4 * 1.8 * t + (9 * np.exp(-t / 1.2)) for t in t3]
    c3 = {
        "lag_times": t3,
        "squared_displacement_samples": gamma_rows(1133, t3, means3, [72] * 9, [12] * 9),
        "independent_sample_counts": [72, 60, 45, 35, 25, 17, 11, 7, 4],
        "dimension": 2,
        "fit_start": 3.4,
        "condition_limit": 1e3,
        "mcmc_seed": PILOT_SEEDS[0],
    }
    return [c1, c2, c3]


def flatten(value: dict) -> np.ndarray:
    return np.asarray([value["mean"], value["variance"], *value["quantiles"]], dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    args = parser.parse_args()
    if EVIDENCE.exists() or REPORT.exists():
        raise RuntimeError("refusing to overwrite existing 0011_core feasibility evidence")
    for checkout in (args.checkout_1, args.checkout_2):
        head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        if head != COMMIT or subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], check=True, capture_output=True, text=True).stdout:
            raise RuntimeError("both kinisi inputs must be clean pinned checkouts")

    cases = provisional_cases()
    with tempfile.TemporaryDirectory(prefix="scibench_0011_core_feasibility_", dir=ROOT) as temporary:
        stage = Path(temporary)
        evidence = stage / "evidence"
        bundle = evidence / "public_bundle"
        bundle.mkdir(parents=True)
        shutil.copyfile(ROOT / "scibench_replication_0011/public/paper.pdf", bundle / "paper.pdf")
        (bundle / "task.md").write_text("solution.py\n", encoding="utf-8")
        write_json(bundle / "interface.schema.json", {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "task_id", "entrypoint"],
            "properties": {
                "schema_version": {"const": 4},
                "task_id": {"const": "scibench_replication_0011_core"},
                "entrypoint": {"oneOf": [
                    {"type": "string", "minLength": 1},
                    {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                ]},
            },
        })

        replay_equal = True
        pilot_relative_errors: list[np.ndarray] = []
        case_rows = []
        for index, base in enumerate(cases, 1):
            case_root = bundle / "cases" / f"case_{index:02d}"
            write_json(case_root / "input.json", base)
            first = official_solve(base, args.checkout_1)
            second = official_solve(base, args.checkout_2)
            replay_equal &= canonical(first) == canonical(second)
            write_json(evidence / f"run_1/public_case_{index:02d}.json", first)
            write_json(evidence / f"run_2/public_case_{index:02d}.json", second)
            write_json(case_root / "output.json", first)
            independent = independent_solve(base)
            write_json(evidence / f"independent/public_case_{index:02d}.json", independent)
            draws = []
            for seed in PILOT_SEEDS:
                seeded = dict(base, mcmc_seed=seed)
                value = official_solve(seeded, args.checkout_1)
                draws.append(flatten(value))
                write_json(evidence / f"pilot_seeds/public_case_{index:02d}_seed_{seed}.json", value)
            draws_array = np.asarray(draws)
            exact = flatten(independent)
            scale = np.maximum(np.abs(exact), np.asarray([1e-8, 1e-12, 1e-8, 1e-8, 1e-8]))
            relative = np.abs(draws_array - exact) / scale
            pilot_relative_errors.extend(relative)
            case_rows.append({
                "case_id": f"case_{index:02d}",
                "input_sha256": sha(case_root / "input.json"),
                "output_sha256": sha(case_root / "output.json"),
                "independent_output_sha256": sha(evidence / f"independent/public_case_{index:02d}.json"),
                "maximum_pilot_relative_error": float(relative.max()),
            })

        errors = np.asarray(pilot_relative_errors)
        centers = errors.mean(axis=0)
        deviations = errors.std(axis=0, ddof=1)
        # Frozen before any hidden case exists: a conservative four-sigma
        # prediction bound plus observed absolute pilot bias.
        bounds = np.maximum(centers + 4 * deviations, errors.max(axis=0) * 1.10)
        tolerance = {
            "frozen_from": "five official seeds on three provisional public cases before hidden construction",
            "rule": "max(mean absolute relative error + 4 sample SD, 1.10 * observed maximum)",
            "field_order": ["mean", "variance", "q2.5", "q50", "q97.5"],
            "relative_bounds": [float(x) for x in bounds],
            "absolute_scale_floors": [1e-8, 1e-12, 1e-8, 1e-8, 1e-8],
        }
        write_json(evidence / "frozen_tolerance.json", tolerance)
        all_within = bool(np.all(errors <= bounds + 1e-15))
        source_hashes = {
            "kinisi_diffusion_py": DIFFUSION_SHA256,
            "analysis_environment_yml": "8d9c31364697298812f929068224f64662d5965b19b204d7420dccb82211b3df",
            "analysis_kinisi_rw_py": "8de80ea8a8677daee0cff2de791c617bf8166ce7efe1d59a9f785a828e871978",
            "adapter": sha(ROOT / "curation_tools/kinisi_core_adapter.py"),
            "independent": sha(ROOT / "curation_tools/kinisi_core_scientific.py"),
            "environment": sha(ROOT / "curation_tools/environments/0011-core-environment.yml"),
        }
        report = {
            "schema_version": 1,
            "task_id": "scibench_replication_0011_core",
            "status": "FEASIBILITY_NUMERICAL_PASS" if replay_equal and all_within else "REVISE",
            "pins": {"kinisi_version": "1.1.0", "kinisi_commit": COMMIT, "analysis_commit": ANALYSIS_COMMIT},
            "official_call_chain": "JSON squared samples -> exact vector representation -> pinned MSDBootstrap -> diffusion -> gradient/(2*dimension)",
            "official_adapter_scope": "JSON validation/representation, seed assignment, pinned call, Einstein-unit conversion, posterior summary only",
            "two_clean_checkouts_exact": replay_equal,
            "independent_audit": "Eq. 6 covariance, symmetric minimum-eigenvalue floor, GLS Gaussian parameter law, exact lower-truncated slope marginal",
            "pilot_seed_count_per_case": len(PILOT_SEEDS),
            "official_independent_within_frozen_bound": all_within,
            "frozen_tolerance": tolerance,
            "source_hashes": source_hashes,
            "public_bundle_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in sorted(bundle.rglob("*")) if path.is_file())).hexdigest(),
            "cases": case_rows,
            "environment": {"python": platform.python_version(), "numpy": np.__version__},
            "next_gate": "G6 blind identification",
        }
        write_json(stage / "report.json", report)
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        os.replace(evidence, EVIDENCE)
        os.replace(stage / "report.json", REPORT)
    if report["status"] != "FEASIBILITY_NUMERICAL_PASS":
        raise RuntimeError("0011_core numerical feasibility failed")


if __name__ == "__main__":
    main()
