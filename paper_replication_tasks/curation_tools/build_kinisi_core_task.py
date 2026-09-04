#!/usr/bin/env python3
"""Build the formal 0011_core task after the feasibility gates pass."""

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
from run_0011_core_feasibility import provisional_cases

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0011_core"
FEASIBILITY = ROOT / "curation_reports/0011_core_feasibility.json"
BLIND = ROOT / "core_algorithm_audits/0011_core_blind.json"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def gamma_rows(seed: int, means: list[float], sizes: list[int], shapes: list[float]) -> list[list[float]]:
    rng = np.random.RandomState(seed)
    rows = []
    for mean, size, shape in zip(means, sizes, shapes):
        row = rng.gamma(shape, mean / shape, size=size)
        # Preserve the designed lag mean exactly while retaining stochastic variance.
        row *= mean / row.mean()
        rows.append(row.tolist())
    return rows


def payload(seed: int, times: list[float], means: list[float], sizes: list[int], shapes: list[float],
            counts: list[float], dimension: int, fit_start: float, condition_limit: float,
            mcmc_seed: int) -> dict:
    return {
        "lag_times": times,
        "squared_displacement_samples": gamma_rows(seed, means, sizes, shapes),
        "independent_sample_counts": counts,
        "dimension": dimension,
        "fit_start": fit_start,
        "condition_limit": condition_limit,
        "mcmc_seed": mcmc_seed,
    }


def hidden_cases() -> tuple[list[dict], list[dict]]:
    cases: list[dict] = []
    designs: list[dict] = []

    t = [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8]
    cases.append(payload(2111, t, [0.2 + 6 * 0.35 * x for x in t], [80] * 8, [30] * 8,
                         [400, 200, 100, 50, 25, 12, 6, 3], 3, 0.2, 8.0, 21101))
    designs.append({"case_id": "case_01", "hazards": ["ill_conditioned_covariance", "minimum_eigenvalue_reconditioning"],
                    "invariant": "finite ordered posterior summaries after condition-number control"})

    t = [1, 2, 3.5, 5.5, 8, 12, 17, 24]
    cases.append(payload(2122, t, [2.0 + 6 * 2e-5 * x for x in t], [36] * 8, [2.5] * 8,
                         [26, 18, 12, 8, 6, 4, 3, 2], 3, 1, 1e6, 21203))
    designs.append({"case_id": "case_02", "hazards": ["nonnegative_diffusion_prior", "low_diffusion_boundary"],
                    "invariant": "posterior support and all reported quantiles remain nonnegative"})

    t = [0.25, 0.75, 1.5, 2.5, 4, 6.5, 10, 15]
    cases.append(payload(2133, t, [48.0 + 4 * 0.55 * x for x in t], [64] * 8, [45] * 8,
                         [90, 70, 52, 38, 26, 17, 10, 6], 2, 0.75, 1e9, 21307))
    designs.append({"case_id": "case_03", "hazards": ["nonzero_intercept"],
                    "invariant": "diffusion is obtained from the fitted slope, not mean/t"})

    t = [0.2, 0.5, 1, 2, 3.5, 5.5, 8.5, 13, 20]
    means = [0.4 + 3.5 * x * x for x in t[:4]] + [7.0 + 2 * 1.4 * x for x in t[4:]]
    cases.append(payload(2144, t, means, [72] * 9, [20] * 9,
                         [120, 90, 65, 45, 32, 22, 14, 8, 4], 1, 3.5, 1e5, 21401))
    designs.append({"case_id": "case_04", "hazards": ["early_nondiffusive_regime", "fit_window"],
                    "invariant": "only lags at or above fit_start enter the regression"})

    t = [0.03, 0.11, 0.37, 0.9, 1.8, 3.7, 7.4, 14.9, 30.0]
    cases.append(payload(2155, t, [0.07 + 2 * 0.032 * x for x in t], [55] * 9, [14] * 9,
                         [75, 62, 49, 36, 25, 16, 10, 6, 3], 1, 0.11, 2e4, 21503))
    designs.append({"case_id": "case_05", "hazards": ["irregular_lag_grid", "one_dimension"],
                    "invariant": "Einstein scaling uses the supplied dimension and numeric lag grid"})

    t = [1, 2, 4, 7, 11, 16, 22]
    cases.append(payload(2166, t, [0.6 + 4 * 0.18 * x for x in t], [6] * 7, [1.8] * 7,
                         [8, 6, 5, 4, 3, 2.5, 2], 2, 2, 50.0, 21611))
    designs.append({"case_id": "case_06", "hazards": ["few_independent_samples", "heteroscedastic_noise"],
                    "invariant": "sample variance is rescaled by the supplied effective counts"})

    t = [0.02, 0.06, 0.15, 0.4, 1, 2.5, 6]
    cases.append(payload(2177, t, [120.0 + 6 * 8500.0 * x for x in t], [48] * 7, [35] * 7,
                         [70, 52, 36, 23, 13, 7, 3], 3, 0.06, 1e7, 21701))
    designs.append({"case_id": "case_07", "hazards": ["high_diffusion_scale", "scale_generalization"],
                    "invariant": "posterior summaries scale with squared-distance/time units"})

    t = [10, 30, 75, 160, 320, 650, 1300, 2600]
    cases.append(payload(2188, t, [3e-6 + 6 * 3e-7 * x for x in t], [60] * 8, [25] * 8,
                         [95, 70, 50, 34, 22, 13, 7, 3], 3, 30, 1e4, 21803))
    designs.append({"case_id": "case_08", "hazards": ["low_numeric_scale", "scale_generalization"],
                    "invariant": "finite posterior summaries without scale-dependent constants"})
    return cases, designs


INTERFACE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"],
    "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
                   "entrypoint": {"oneOf": [{"type": "string", "minLength": 1},
                                              {"type": "array", "minItems": 1,
                                               "items": {"type": "string", "minLength": 1}}]}},
}


def flatten(value: dict) -> np.ndarray:
    return np.asarray([value["mean"], value["variance"], *value["quantiles"]], dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    args = parser.parse_args()
    feasibility = json.loads(FEASIBILITY.read_text(encoding="utf-8"))
    blind = json.loads(BLIND.read_text(encoding="utf-8"))
    if feasibility.get("status") != "FEASIBILITY_PASS" or blind.get("G6") != "PASS" or blind.get("pass_count", 0) < 2:
        raise RuntimeError("feasibility gates have not passed")
    for checkout in (args.checkout_1, args.checkout_2):
        head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
        if head != COMMIT or dirty:
            raise RuntimeError("both official inputs must be clean pinned checkouts")
    destination = ROOT / TASK_ID
    evidence_destination = ROOT / "curation_reports/official_runs/0011_core"
    if destination.exists() or evidence_destination.exists():
        raise RuntimeError("refusing to overwrite an existing formal task or evidence")

    public = provisional_cases()
    hidden, designs = hidden_cases()
    flat = [(split, index, case) for split, values in (("public", public), ("hidden", hidden))
            for index, case in enumerate(values, 1)]
    frozen = feasibility["frozen_tolerance"]
    bounds = np.asarray(frozen["relative_bounds"], dtype=float)
    floors = np.asarray(frozen["absolute_scale_floors"], dtype=float)
    # Convert the pre-hidden independent-denominator bounds to evaluator rules
    # using official gold as denominator. This algebraically preserves the bound.
    evaluator_rtol = bounds / np.maximum(1.0 - bounds, 1e-12)
    field_names = ("mean", "variance", "q2.5", "q50", "q97.5")
    quantile = int(np.argmax(evaluator_rtol[2:])) + 2
    tolerance = {"comparison": "fieldwise", "field_rules": {
        "mean": {"atol": float(bounds[0] * floors[0]), "rtol": float(evaluator_rtol[0])},
        "variance": {"atol": float(bounds[1] * floors[1]), "rtol": float(evaluator_rtol[1])},
        "quantiles": {"atol": float(bounds[quantile] * floors[quantile]), "rtol": float(evaluator_rtol[quantile])},
    }, "frozen_source": "curation_reports/official_runs/0011_core_feasibility/frozen_tolerance.json",
       "quantile_rule": "most conservative of the three pre-hidden frozen quantile bounds"}

    with tempfile.TemporaryDirectory(prefix="scibench_0011_core_build_", dir=ROOT) as temporary:
        stage = Path(temporary); task = stage / TASK_ID; evidence = stage / "official_runs"
        runs: list[list[dict]] = []
        for run_index, checkout in enumerate((args.checkout_1, args.checkout_2), 1):
            run = []
            for split, index, case in flat:
                result = official_solve(case, checkout)
                run.append(result)
                write_json(evidence / f"run_{run_index}/{split}_case_{index:02d}.json", result)
            runs.append(run)
        run_hashes = [canonical_hash(run) for run in runs]
        if run_hashes[0] != run_hashes[1]:
            raise RuntimeError("two clean official runs differ")

        independent = [independent_solve(case) for _, _, case in flat]
        relative_errors = []
        for official, audit in zip(runs[0], independent):
            relative_errors.append(np.abs(flatten(official) - flatten(audit)) / np.maximum(np.abs(flatten(audit)), floors))
        relative_errors_array = np.asarray(relative_errors)
        if np.any(relative_errors_array > bounds + 1e-15):
            locations = np.argwhere(relative_errors_array > bounds + 1e-15).tolist()
            raise RuntimeError(f"independent audit exceeds frozen pre-hidden bound at {locations}")

        (task / "public").mkdir(parents=True); (task / "hidden").mkdir()
        shutil.copyfile(ROOT / "scibench_replication_0011/public/paper.pdf", task / "public/paper.pdf")
        (task / "public/task.md").write_text("solution.py\n", encoding="utf-8")
        write_json(task / "public/interface.schema.json", INTERFACE_SCHEMA)
        records = []
        for offset, (split, index, case) in enumerate(flat):
            case_root = task / split / "cases" / f"case_{index:02d}"
            write_json(case_root / "input.json", case)
            write_json(case_root / "output.json", runs[0][offset])
            write_json(evidence / f"independent/{split}_case_{index:02d}.json", independent[offset])
            records.append({"split": split, "case_id": f"case_{index:02d}",
                            "input_sha256": sha(case_root / "input.json"),
                            "output_sha256": sha(case_root / "output.json"),
                            "independent_output_sha256": sha(evidence / f"independent/{split}_case_{index:02d}.json"),
                            "relative_errors": {name: float(value) for name, value in zip(field_names, relative_errors_array[offset])}})
        write_json(task / "hidden/tolerances.json", tolerance)
        provenance = {
            "schema_version": 4, "task_id": TASK_ID, "lifecycle": "candidate", "gold_source": "pinned_official_checkout",
            "legacy_predecessor": "scibench_replication_0011", "repository": "https://github.com/bjmorgan/kinisi",
            "commit": COMMIT, "analysis_repository_commit": ANALYSIS_COMMIT, "kinisi_version": "1.1.0",
            "paper_sha256": sha(task / "public/paper.pdf"), "kinisi_diffusion_sha256": DIFFUSION_SHA256,
            "official_reproduction": {"adapter_sha256": sha(ROOT / "curation_tools/kinisi_core_adapter.py"),
                "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0011-core-environment.yml"),
                "clean_checkout_bundle_sha256": run_hashes,
                "raw_outputs": "curation_reports/official_runs/0011_core"},
            "independent_audit": {"implementation": "independent Eq. 6 covariance, symmetric eigenvalue floor, and exact truncated-Gaussian marginal",
                "implementation_sha256": sha(ROOT / "curation_tools/kinisi_core_scientific.py"), "status": "passed",
                "frozen_relative_bounds": frozen, "maximum_relative_errors": {
                    name: float(value) for name, value in zip(field_names, relative_errors_array.max(axis=0))}},
            "case_design": designs, "cases": records, "tolerances": tolerance,
            "environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        }
        write_json(task / "hidden/provenance.json", provenance)
        report = {"schema_version": 1, "task_id": TASK_ID, "status": "oracle_passed", "G8": "PASS",
                  "two_clean_checkouts_match": True, "official_output_bundle_sha256": run_hashes[0],
                  "official_output_bundle_sha256_by_run": run_hashes, "independent_within_frozen_tolerance": True,
                  "maximum_relative_errors": provenance["independent_audit"]["maximum_relative_errors"],
                  "tolerances": tolerance}
        write_json(stage / "report.json", report)
        os.replace(task, destination)
        evidence_destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(evidence, evidence_destination)
        os.replace(stage / "report.json", ROOT / "curation_reports/0011_core_oracle.json")


if __name__ == "__main__":
    main()
