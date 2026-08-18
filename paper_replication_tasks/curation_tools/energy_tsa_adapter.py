#!/usr/bin/env python3
"""Official dependent A--F workflow adapter for the a-posteriori TSA candidate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

COMMIT = "c162068f61bafbe640bbd40ee4a47312498ed153"
METHODS = {
    "A": "agg_inp_mean",
    "B": "agg_inp_closest",
    "C": "agg_inp_min_max",
    "D": "agg_str_unmet_inp",
    "E": "agg_str_gencost_inp",
    "F": "agg_str_gencost_op_vars",
}
CAPACITIES = ["cap_baseload_total", "cap_peaking_total", "cap_wind_total",
              "cap_storage_energy_total", "cap_transmission_total"]
EXPECTED_YEARS = {
    0: [1980, 1983, 1983], 1: [2017, 1992, 1988], 2: [1995, 1988, 2002],
    3: [2004, 1983, 1988], 4: [1985, 1981, 2003], 5: [2015, 1994, 1996],
}


def _run(work: Path, method: str, kind: str, seed: int) -> None:
    print(f"official energy seed={seed} method={method} phase={kind}", flush=True)
    subprocess.run([
        sys.executable, "main.py", "--simulation_name", METHODS[method],
        "--simulation_type", kind, "--ts_base_resample_num_years", "3",
        "--ts_reduction_num_days", "30", "--replication", str(seed),
    ], cwd=work, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def _summary(work: Path, method: str, seed: int, suffix: str) -> pd.Series:
    pattern = f"{METHODS[method]}--03y--0030d_*--{seed:04d}--{suffix}.csv"
    matches = list((work / "outputs/summary_outputs").glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one summary for {method}/{suffix}, found {matches}")
    frame = pd.read_csv(matches[0], index_col=0)
    if list(frame.columns) != ["output"]:
        raise RuntimeError("official summary schema differs")
    return frame["output"]


def _ts_outputs_present(work: Path, method: str, seed: int) -> Path:
    # get_ds (design-estimate) ts_outputs carries the official `cluster` column produced by
    # Calliope's own get_timeseries_outputs() whenever the model solved a clustered/aggregated
    # time series; this is the ground-truth day-to-representative-day mapping methods D-F use.
    pattern = f"{METHODS[method]}--03y--0030d_*--{seed:04d}--get_ds.csv"
    matches = list((work / "outputs/ts_outputs").glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one ts_outputs file for {method}, found {matches}")
    return matches[0]


def _enable_design_ts_outputs(work: Path) -> None:
    # main_run_config only saves ts_outputs for get_operate_variables runs by default; the
    # get_design_estimate ts_outputs (with the cluster assignment) is needed for the independent
    # aggregation audit, so flip the default. This does not change solve semantics -- only which
    # outputs are written to disk.
    config_path = work / "config.py"
    original = config_path.read_text(encoding="utf-8")
    target = "'save_ts_outputs': False,  # Gets changed to True for 'get_operate_variables' simulations"
    if target not in original:
        raise RuntimeError("could not locate save_ts_outputs default in official config.py")
    config_path.write_text(
        original.replace(target, "'save_ts_outputs': True,  # scibench: always save ts_outputs"),
        encoding="utf-8",
    )


def solve(case: dict, checkout: Path, raw_output_dir: Path | None = None) -> dict:
    if not isinstance(case, dict) or set(case) != {"seed", "years"}:
        raise ValueError("case fields differ")
    seed = case["seed"]
    if isinstance(seed, bool) or seed not in EXPECTED_YEARS or case["years"] != EXPECTED_YEARS[seed]:
        raise ValueError("seed/year mapping differs from official MT19937 resampling")
    with tempfile.TemporaryDirectory(prefix=f"scibench_energy_{seed}_") as temporary:
        work = Path(temporary) / "official"
        shutil.copytree(checkout, work, ignore=shutil.ignore_patterns(".git", "outputs"))
        _enable_design_ts_outputs(work)
        for directory in ("configs", "logs", "summary_outputs", "ts_outputs", "plots", "plots_post"):
            (work / "outputs" / directory).mkdir(parents=True, exist_ok=True)
        result = {"methods": {}}
        ts_output_files: list[Path] = []
        for method in METHODS:
            _run(work, method, "get_design_estimate", seed)
            _run(work, method, "get_operate_variables", seed)
            design = _summary(work, method, seed, "get_ds")
            operate = _summary(work, method, seed, "get_op")
            values = [float(design.loc[name]) for name in CAPACITIES]
            unmet = float(operate.loc["gen_unmet_total"])
            if not all(value == value and abs(value) != float("inf") for value in [*values, unmet]):
                raise RuntimeError("official workflow produced non-finite output")
            result["methods"][method] = {"capacity_totals": values, "unserved_energy": unmet}
            ts_output_files.append(_ts_outputs_present(work, method, seed))
            if method == "B":
                # D/E/F stratify using method B's full-time-series operate variables
                # (gen_unmet_total, generation_cost); persist that ts_outputs too so the
                # independent audit can reconstruct the D/E/F stratification input exactly.
                op_pattern = f"{METHODS[method]}--03y--0030d_*--{seed:04d}--get_op.csv"
                op_matches = list((work / "outputs/ts_outputs").glob(op_pattern))
                if len(op_matches) != 1:
                    raise RuntimeError(f"expected one operate ts_outputs for B, found {op_matches}")
                ts_output_files.append(op_matches[0])
        if raw_output_dir is not None:
            if raw_output_dir.exists():
                raise RuntimeError(f"raw output directory already exists: {raw_output_dir}")
            shutil.copytree(work / "outputs/summary_outputs", raw_output_dir / "summary_outputs")
            ts_dir = raw_output_dir / "ts_outputs"
            ts_dir.mkdir(parents=True, exist_ok=True)
            for source in ts_output_files:
                shutil.copy2(source, ts_dir / source.name)
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output-dir", type=Path)
    args = parser.parse_args()
    if args.task != "0016":
        parser.error("unsupported task")
    value = solve(
        json.loads(args.input.read_text(encoding="utf-8")),
        args.checkout,
        args.raw_output_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
