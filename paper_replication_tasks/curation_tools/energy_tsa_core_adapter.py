#!/usr/bin/env python3
"""Injection-only official Calliope adapter for 0018_core."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

COMMIT = "c162068f61bafbe640bbd40ee4a47312498ed153"
INPUT_COLUMNS = ["demand_region2", "demand_region4", "demand_region5",
                 "wind_region2", "wind_region5", "wind_region6"]
CAPACITY_TOTALS = ["cap_baseload_total", "cap_peaking_total", "cap_wind_total",
                   "cap_storage_energy_total", "cap_transmission_total"]


def _validate(case: dict) -> tuple[np.ndarray, int, float, int]:
    if not isinstance(case, dict) or set(case) != {"x", "n", "p", "q"}: raise ValueError("case fields differ")
    x = np.asarray(case["x"], dtype=float); n, p, q = case["n"], case["p"], case["q"]
    if x.ndim != 3 or x.shape[1:] != (24, 6) or not 4 <= x.shape[0] <= 366: raise ValueError("x shape differs")
    if not np.isfinite(x).all() or (x < 0).any(): raise ValueError("x must be finite and nonnegative")
    if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n < x.shape[0]: raise ValueError("n differs")
    if isinstance(q, bool) or q not in (0, 1, 2): raise ValueError("q differs")
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p < .5: raise ValueError("p differs")
    return x, n, float(p), int(q)


def _config(config, n: int, p: float, q: int | None) -> dict:
    value = copy.deepcopy(config.main_run_config)
    value["simulation"].update({"name": "oracle", "type": "get_design_estimate", "id": "oracle", "replication": 0})
    value["ts_base"].update({"roll_days": 0, "resample_num_years": None})
    agg = value["ts_aggregation"]; agg["aggregate"] = True; agg["num_days"] = n
    agg["representative_day"] = "closest"; agg["clustering"]["columns_used"] = list(INPUT_COLUMNS)
    agg["stratification"].update({"stratify": q is not None,
                                  "column_used": "gen_unmet_total" if q == 0 else "generation_cost",
                                  "aggfunc": "sum", "ts_base_split_extreme": p, "ts_agg_split_extreme": .5})
    if q == 2:
        agg["clustering"]["columns_used"] += ["gen_storage_region2", "gen_storage_region5", "gen_storage_region6"]
    agg["num_days_extreme"] = 0 if q is None else round(.5 * n)
    value["save"].update({"save_run_config": False, "save_summary_outputs": False,
                          "save_ts_outputs": False, "save_plot": False, "save_full_outputs": False})
    return value


def _model(work: Path, models, ts: pd.DataFrame, fixed: dict | None = None):
    run_id = "oracle"; source = work / "model_files/6_region"; target = work / f"model_files/6_region_{run_id}"
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(source, target)
    model = models.models.SixRegionModel(ts_data=ts, run_mode="operate" if fixed else "plan",
        allow_unmet=fixed is not None, fixed_caps=fixed, run_id=run_id)
    shutil.rmtree(target); model.run(); return model


def _capacity_dict(summary: pd.DataFrame) -> dict:
    values = summary["output"].copy(); values.loc[values < .0001] = .0001
    out = values.filter(regex=r"^cap_.*_region\d(_region\d)?$").to_dict()
    if len(out) != 22: raise RuntimeError(f"official capacity vector has {len(out)} rather than 22 entries")
    return out


def _aggregate(aggregation, ts: pd.DataFrame, cfg: dict, operate: pd.DataFrame | None = None):
    used = ts if operate is None else pd.concat([ts, operate], axis=1)
    vectors = aggregation.get_vectors_used_to_aggregate(used, cfg)
    raw_labels = aggregation.cluster_stratified(vectors, cfg).to_numpy(dtype=int)
    mapping: dict[int, int] = {}; labels = np.asarray([mapping.setdefault(int(v), len(mapping)) for v in raw_labels])
    original = aggregation.get_daily_vectors(ts); reps = []
    for label in range(len(mapping)):
        idx = np.flatnonzero(labels == label); features = vectors.iloc[idx].drop(columns=["is_extreme_day"])
        distance = features.subtract(features.mean()).pow(2).sum(axis=1)
        reps.append(int(np.flatnonzero(original.index == distance.idxmin())[0]))
    reps_arr = np.asarray(reps, dtype=int)
    rebuilt = ts.to_numpy().reshape(-1, 24, 6)[reps_arr[labels]].reshape(-1, 6)
    clustered = pd.DataFrame(rebuilt, index=ts.index, columns=ts.columns)
    clustered["cluster"] = np.repeat(labels, 24)
    return clustered, labels, reps_arr, np.bincount(labels, minlength=cfg["ts_aggregation"]["num_days"])


def solve(case: dict, checkout: Path, diagnostics: bool = False) -> dict:
    x, n, p, q = _validate(case)
    import subprocess
    if subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip() != COMMIT:
        raise ValueError("checkout commit differs")
    with tempfile.TemporaryDirectory(prefix="scibench_0018_core_official_") as temporary:
        work = Path(temporary) / "official"; shutil.copytree(checkout, work, ignore=shutil.ignore_patterns(".git", "outputs"))
        old_cwd = Path.cwd(); old_path = list(sys.path)
        try:
            os.chdir(work); sys.path.insert(0, str(work))
            import aggregation, config, models
            ts = pd.DataFrame(x.reshape(-1, 6), index=pd.date_range("2021-01-01", periods=x.shape[0] * 24, freq="h"), columns=INPUT_COLUMNS)
            preliminary_ts, preliminary_labels, preliminary_reps, preliminary_weights = _aggregate(
                aggregation, ts, _config(config, n, 0, None)
            )
            preliminary = _model(work, models, preliminary_ts)
            preliminary_summary = preliminary.get_summary_outputs()["output"]
            preliminary_caps = _capacity_dict(preliminary.get_summary_outputs())
            operate_model = _model(work, models, ts, preliminary_caps)
            operate = operate_model.get_timeseries_outputs().round(3)
            operate["gen_unmet_total"] = operate.filter(regex=r"^gen_unmet_region\d$").sum(axis=1)
            required = ["gen_unmet_total"] if q == 0 else ["generation_cost"]
            if q == 2: required += ["gen_storage_region2", "gen_storage_region5", "gen_storage_region6"]
            final_ts, labels, reps, weights = _aggregate(aggregation, ts, _config(config, n, p, q), operate[required])
            final = _model(work, models, final_ts); summary = final.get_summary_outputs()["output"]
            y = [float(summary.loc[name]) for name in CAPACITY_TOTALS]
            result = {"y": y, "z": labels.tolist(), "r": reps.tolist(), "w": weights.astype(int).tolist()}
            if diagnostics:
                result["diagnostics"] = {
                    "preliminary": {
                        "z": preliminary_labels.tolist(),
                        "r": preliminary_reps.tolist(),
                        "w": preliminary_weights.astype(int).tolist(),
                        "capacities": {key: float(value) for key, value in preliminary_caps.items()},
                        "totals": [float(preliminary_summary.loc[name]) for name in CAPACITY_TOTALS],
                    },
                    "operation": {
                        "unmet_daily": operate["gen_unmet_total"].to_numpy().reshape(-1, 24).sum(axis=1).tolist(),
                        "generation_cost_daily": operate["generation_cost"].to_numpy().reshape(-1, 24).sum(axis=1).tolist(),
                        "storage_net": operate[["gen_storage_region2", "gen_storage_region5", "gen_storage_region6"]].to_numpy().tolist(),
                    },
                }
            return result
        finally:
            os.chdir(old_cwd); sys.path[:] = old_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args(); value = solve(
        json.loads(args.input.read_text()), args.checkout, diagnostics=args.diagnostics
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__": main()
