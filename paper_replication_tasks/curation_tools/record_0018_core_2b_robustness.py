#!/usr/bin/env python3
"""Audit 0018_core cases against public-equivalent paper parameterizations."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import sys
import time
import types
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
IMPLEMENTATION = ROOT / "curation_tools/energy_tsa_core_scientific.py"
REPORT = ROOT / "curation_reports/official_runs/0018_core/parameter_robustness/report.json"
VARIANTS = {
    "paper_low": {"cap13": 150.05, "gen_scale": .25, "storage_power": 100.0,
                  "base_inactive_cap_indices": [2, 8, 11, 14]},
    "paper_mid": {"cap13": 150.10, "gen_scale": .50, "storage_power": 100.0,
                  "base_inactive_cap_indices": []},
    "paper_high": {"cap13": 150.149, "gen_scale": .75, "storage_power": 100.0,
                   "base_inactive_cap_indices": []},
}
BASE_CAP = np.array([300., 300., 300., 100., 100., 100., 100., 100., 100.,
                     1., 1., 1., 100., 150., 100., 100., 100., 100., 100.])
BASE_GEN = np.array([.005, .005, .005, .035, .035, .035, 0., 0., 0.])


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_variant(name: str) -> types.ModuleType:
    spec = VARIANTS[name]
    source = IMPLEMENTATION.read_text()
    source = source.replace("(0, 100.0)", f"(0, {spec['storage_power']})")
    source = source.replace(
        "6.000002 + np.arange(3) * .000001", "6.0 + np.arange(3) * 0.0"
    )
    module = types.ModuleType(f"energy_tsa_core_{name}")
    exec(compile(source, str(IMPLEMENTATION), "exec"), module.__dict__)
    module.CAP_COST[13] = spec["cap13"]
    for index in spec["base_inactive_cap_indices"]:
        module.CAP_COST[index] = BASE_CAP[index]
    module.GEN_COST[:] = BASE_GEN + spec["gen_scale"] * (module.GEN_COST - BASE_GEN)
    return module


def run_variant(name: str) -> dict[str, object]:
    module = load_variant(name)
    tolerance = json.loads((TASK / "hidden/tolerances.json").read_text())["field_rules"]["y"]
    rows = []
    for split in ("public", "hidden"):
        for case_dir in sorted((TASK / split / "cases").glob("case_*")):
            actual = module.solve(json.loads((case_dir / "input.json").read_text()))
            expected = json.loads((case_dir / "output.json").read_text())
            left = np.asarray(actual["y"], dtype=float)
            right = np.asarray(expected["y"], dtype=float)
            row = {
                "case": f"{split}/{case_dir.name}",
                "z_exact": actual["z"] == expected["z"],
                "r_exact": actual["r"] == expected["r"],
                "w_exact": actual["w"] == expected["w"],
                "y_max_abs_error": float(np.max(np.abs(left - right))),
                "y_pass": bool(np.all(
                    np.abs(left - right) <= tolerance["atol"] + tolerance["rtol"] * np.abs(right)
                )),
            }
            row["pass"] = row["z_exact"] and row["r_exact"] and row["w_exact"] and row["y_pass"]
            rows.append(row)
    return {"variant": name, "parameters": VARIANTS[name], "rows": rows,
            "public_pass": all(row["pass"] for row in rows if row["case"].startswith("public/")),
            "hidden_pass": all(row["pass"] for row in rows if row["case"].startswith("hidden/"))}


def main() -> None:
    started = time.monotonic()
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(VARIANTS)) as pool:
        results = list(pool.map(run_variant, VARIANTS))
    report = {
        "schema_version": 1,
        "task_id": TASK.name,
        "G4": "PASS" if all(row["public_pass"] and row["hidden_pass"] for row in results) else "FAIL",
        "criterion": (
            "Every retained parameterization must pass all public cases and all redesigned hidden cases "
            "under the frozen field tolerances."
        ),
        "scope": (
            "Representative low/mid/high combinations of paper-unspecified regional generation and "
            "transmission cost perturbations, unperturbed VOLL, and inactive regional costs. "
            "Nearby storage power limits are excluded because the rederived tolerance rejects them publicly."
        ),
        "variants": results,
        "runtime_seconds": time.monotonic() - started,
        "hashes": {
            "paper": sha(TASK / "public/paper.pdf"),
            "scientific_implementation": sha(IMPLEMENTATION),
            "recorder": sha(Path(__file__)),
            "hidden_inputs": {case.name: sha(case / "input.json")
                              for case in sorted((TASK / "hidden/cases").glob("case_*"))},
            "hidden_outputs": {case.name: sha(case / "output.json")
                               for case in sorted((TASK / "hidden/cases").glob("case_*"))},
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["G4"] != "PASS":
        raise SystemExit("2B parameter robustness failed; inspect report")


if __name__ == "__main__":
    main()
