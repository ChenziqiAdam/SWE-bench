#!/usr/bin/env python3
"""Build the a-posteriori TSA energy task from two pinned clean official checkouts and audit
the D-F aggregation step independently (solver-neutral cluster-assignment match)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from energy_tsa_adapter import COMMIT, EXPECTED_YEARS, METHODS, solve as official_solve
from energy_tsa_scientific import compare_cluster_assignments, independent_cluster_assignment

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0018"
EVIDENCE_ROOT = ROOT / "curation_reports/official_runs/energy"
TOLERANCE = {
    "comparison": "fieldwise",
    "field_rules": {
        "capacity_totals": {"atol": 0.05, "rtol": 0.0},
        "unserved_energy": {"atol": 1.0, "rtol": 0.01},
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def cases() -> tuple[list[dict], list[dict]]:
    public = [{"seed": 0, "years": EXPECTED_YEARS[0]}]
    hidden = [{"seed": seed, "years": EXPECTED_YEARS[seed]} for seed in range(1, 6)]
    return public, hidden


def fieldwise_within(actual: float, expected: float, atol: float, rtol: float) -> bool:
    return abs(actual - expected) <= atol + rtol * abs(expected)


def compare_methods_result(run_a: dict, run_b: dict) -> tuple[bool, float, float]:
    """Compare two `solve()` results (both runs of the same case) under TOLERANCE's field
    rules; returns (within_tolerance, max_capacity_abs_error, max_unserved_relative_error)."""
    max_cap_abs = 0.0
    max_unmet_rel = 0.0
    within = True
    rules = TOLERANCE["field_rules"]
    for method in METHODS:
        a, b = run_a["methods"][method], run_b["methods"][method]
        for x, y in zip(a["capacity_totals"], b["capacity_totals"]):
            max_cap_abs = max(max_cap_abs, abs(x - y))
            within &= fieldwise_within(x, y, rules["capacity_totals"]["atol"], rules["capacity_totals"]["rtol"])
        unmet_a, unmet_b = a["unserved_energy"], b["unserved_energy"]
        max_unmet_rel = max(max_unmet_rel, abs(unmet_a - unmet_b) / max(abs(unmet_b), 1e-300))
        within &= fieldwise_within(unmet_a, unmet_b, rules["unserved_energy"]["atol"], rules["unserved_energy"]["rtol"])
    return within, max_cap_abs, max_unmet_rel


def audit_cluster_assignments(
    base_csv: Path, case: dict, raw_dir: Path, operate_csv: Path
) -> dict[str, Any]:
    """Run the independent D-F (and A-C) aggregation audit for one case's raw run outputs."""
    years = case["years"]
    files = {
        method: raw_dir / "ts_outputs" / next(
            (raw_dir / "ts_outputs").glob(f"{METHODS[method]}--03y--0030d_*--{case['seed']:04d}--get_ds.csv")
        ).name
        for method in METHODS
    }
    results = {}
    for method, path in files.items():
        official_hourly = pd.read_csv(path, index_col=0)
        official_hourly.index = pd.to_datetime(official_hourly.index)
        official_daily_cluster = official_hourly["cluster"].resample("D").first()
        operate = operate_csv if method in {"D", "E", "F"} else None
        independent = independent_cluster_assignment(base_csv, years, method, operate)
        comparison = compare_cluster_assignments(independent, official_daily_cluster)
        if not comparison["exact_partition_match"]:
            raise RuntimeError(f"independent cluster audit failed for method {method}: {comparison}")
        results[method] = comparison
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True, help="clean pinned repo checkout")
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--paper-version", required=True)
    args = parser.parse_args()

    task_root = ROOT / TASK_ID
    if task_root.exists():
        raise RuntimeError("refusing to overwrite task")

    public, hidden = cases()
    flat = [("public", 1, public[0])] + [("hidden", index, case) for index, case in enumerate(hidden, 1)]

    runs: list[list[dict]] = []
    for run_num in (1, 2):
        run_values = []
        for split, index, case in flat:
            result_path = EVIDENCE_ROOT / f"run_{run_num}/{split}_case_{index:02d}.json"
            if not result_path.is_file():
                raise RuntimeError(f"missing official run: run_{run_num} {split}_case_{index:02d}")
            run_values.append(json.loads(result_path.read_text(encoding="utf-8")))
        runs.append(run_values)

    # Two-clean-run tolerance check (MILP solves are not bit-identical across machines/runs).
    max_cap_abs = max_unmet_rel = 0.0
    for (split, index, _), value_1, value_2 in zip(flat, runs[0], runs[1]):
        within, cap_abs, unmet_rel = compare_methods_result(value_1, value_2)
        max_cap_abs = max(max_cap_abs, cap_abs)
        max_unmet_rel = max(max_unmet_rel, unmet_rel)
        if not within:
            raise RuntimeError(f"two clean official runs differ beyond tolerance at {split}_case_{index:02d}")

    # Independent solver-neutral D-F (and A-C) cluster-assignment audit against run 1's raw outputs.
    base_csv = args.checkout / "data/demand_wind_solar.csv"
    audit_results: dict[str, Any] = {}
    for split, index, case in flat:
        raw_dir = EVIDENCE_ROOT / f"run_1/{split}_case_{index:02d}_raw"
        operate_csv = raw_dir / "ts_outputs" / next(
            (raw_dir / "ts_outputs").glob(f"{METHODS['B']}--03y--0030d_*--{case['seed']:04d}--get_op.csv")
        ).name
        audit_results[f"{split}_case_{index:02d}"] = audit_cluster_assignments(base_csv, case, raw_dir, operate_csv)

    task_root.joinpath("public/cases").mkdir(parents=True)
    task_root.joinpath("hidden/cases").mkdir(parents=True)
    shutil.copyfile(args.paper, task_root / "public/paper.pdf")
    (task_root / "public/task.md").write_text(TASK_TEXT, encoding="utf-8")
    write_json(task_root / "public/interface.schema.json", INTERFACE_SCHEMA)

    adapter = ROOT / "curation_tools/energy_tsa_adapter.py"
    lock = ROOT / "curation_tools/environments/0016-environment.yml"
    patch = ROOT / "curation_tools/patches/0016-calliope-pr-380.patch"
    records = []
    for output_index, (split, index, case) in enumerate(flat):
        case_id = f"case_{index:02d}"
        case_root = task_root / split / "cases" / case_id
        write_json(case_root / "input.json", case)
        write_json(case_root / "output.json", runs[0][output_index])
        records.append({
            "split": split, "case_id": case_id,
            "input_sha256": sha(case_root / "input.json"),
            "output_sha256": sha(case_root / "output.json"),
            "checkout_commit": COMMIT,
            "environment_lock_sha256": sha(lock),
            "adapter_sha256": sha(adapter),
            "patch_sha256": sha(patch),
            "cluster_audit": audit_results[f"{split}_case_{index:02d}"],
            "command": ("<pinned-environment>/bin/python curation_tools/energy_tsa_adapter.py "
                        "--task 0016 --checkout <clean-checkout> --input <input.json> --output <output.json>"),
        })
    write_json(task_root / "hidden/tolerances.json", TOLERANCE)

    provenance = {
        "schema_version": 4, "task_id": TASK_ID, "lifecycle": "validated",
        "gold_source": "pinned_official_checkout",
        "repository": "https://github.com/ahilbers/a_posteriori_tsa_storage", "commit": COMMIT,
        "paper_version": args.paper_version, "paper_sha256": sha(args.paper),
        "environment_lock_sha256": sha(lock), "adapter_sha256": sha(adapter), "patch_sha256": sha(patch),
        "official_reproduction": {
            "adapter_sha256": sha(adapter), "environment_lock_sha256": sha(lock), "patch_sha256": sha(patch),
            "command": "python curation_tools/build_energy_tsa_task.py --checkout <clean-checkout> --paper <paper.pdf> --paper-version <version>",
            "two_clean_runs_max_capacity_abs_error": max_cap_abs,
            "two_clean_runs_max_unserved_relative_error": max_unmet_rel,
            "raw_and_normalized_outputs": "curation_reports/official_runs/energy",
        },
        "independent_audit": {
            "implementation": ("curation_tools/energy_tsa_scientific.py; independent reimplementation of "
                                "aggregation.py's stratify->normalize->cluster->representative-day pipeline "
                                "for all six methods A-F, compared against Calliope's own day-to-cluster "
                                "assignment (solver-neutral -- does not re-solve the CBC MILP)"),
            "status": "passed", "results": audit_results,
        },
        "cases": records,
    }
    write_json(task_root / "hidden/provenance.json", provenance)
    write_json(ROOT / "curation_reports/a_posteriori_tsa_storage.json", {
        "candidate": "a_posteriori_tsa_storage", "task_id": TASK_ID, "status": "validated",
        "official_commit": COMMIT, "public_cases": 1, "hidden_cases": 5,
        "two_clean_runs_max_capacity_abs_error": max_cap_abs,
        "two_clean_runs_max_unserved_relative_error": max_unmet_rel,
        "cluster_audit_status": "passed", "tolerances": TOLERANCE,
    })


INTERFACE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"],
    "properties": {
        "schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
        "entrypoint": {"oneOf": [{"type": "string", "minLength": 1},
                                  {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]},
    },
}

TASK_TEXT = """# scibench_replication_0018

Implement the paper's a posteriori time series aggregation framework for the six-region
capacity expansion planning model with storage, and reproduce its six aggregation schemes
(A-F). The runner invokes `<entrypoint> --input input.json --output new-output-dir`; write
finite `output.json`.

## Planning model

Implement the six-region system exactly as specified in the paper's Appendix B (nomenclature
Table B.3, objective and constraints B.1-B.14, technology/cost parameters Table B.4): baseload,
peaking and wind generation technologies; transmission between six regions; and storage, solved
as a linear/mixed-integer program that minimizes annualized install cost plus generation cost
subject to demand balance, transmission and storage dynamics constraints. Demand and wind
generation-potential time series are hourly for 1980-2017; a run resamples `ts_reduction_num_years`
years (with replacement) to build a 3-year base time series, then rolls the last 184 days to the
front (reduces the impact of an empty initial storage level). To avoid degenerate/non-unique
solutions, perturb each region's install/generation costs by a small amount (under 0.1%) that is
distinct per region and technology; the exact perturbation is not prescribed by the paper and does
not need to match the reference implementation bit-for-bit -- only the resulting capacities and
unserved energy need to fall within the stated tolerances.

Solve two kinds of runs for each aggregation method: a `get_design_estimate` run (plan mode,
aggregated 3-year time series, free capacities) and a `get_operate_variables` run (operate mode,
full non-aggregated time series, capacities fixed at the design estimate's values, unmet demand
allowed).

## Aggregation schemes A-F

All schemes aggregate the 3-year (1096-day) base time series into 30 representative days using
Ward's-linkage hierarchical clustering on z-normalized daily vectors (each day is one vector of
24 hourly values per clustering column).

- **A**: cluster on demand/wind columns only (no stratification); representative day = cluster
  mean.
- **B**: same clustering as A; representative day = medoid (real day closest to the cluster mean
  in normalized space).
- **C**: like B, but first mark the 3 regional-max-demand days and 3 regional-min-wind days (6
  days total) as "extreme" and cluster them separately from the remaining "regular" days into 6
  and 24 representative days respectively.
- **D**: like B, but stratify using each day's total unmet demand (`gen_unmet_total`, summed over
  regions) from a prior method-B `get_operate_variables` run on the full time series: rank days by
  daily total unmet demand, mark the top 5% (capped at the number of days with any unmet demand)
  as "extreme", and split representative days 15/15 between extreme and regular.
- **E**: like D, but stratify using each day's total generation cost (`generation_cost`, daily sum)
  instead of unmet demand.
- **F**: like E, but also add each region's storage (dis)charge decisions (`gen_storage_region2`,
  `gen_storage_region5`, `gen_storage_region6`) as clustering columns (in addition to the demand/wind
  columns).

## Output

For each of the six methods (keys `"A"`-`"F"`), report:

- `capacity_totals`: `[cap_baseload_total, cap_peaking_total, cap_wind_total,
  cap_storage_energy_total, cap_transmission_total]` (GW/GW/GW/GWh/GW) from the
  `get_design_estimate` run.
- `unserved_energy`: total unmet demand (MWh) summed across the full time series from the
  `get_operate_variables` run.

```json
{"methods": {"A": {"capacity_totals": [..5 floats..], "unserved_energy": <float>}, "...": "...through F"}}
```
"""


if __name__ == "__main__":
    main()
