#!/usr/bin/env python3
"""Install and record clean official gold for the redesigned 0018_core cases."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
EVIDENCE = ROOT / "curation_reports/official_runs/0018_core/g8_official_independent"
CHANGED = ("case_01", "case_02", "case_08")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def compare(official: dict, independent: dict, key: str) -> dict[str, object]:
    independent.pop("diagnostics", None)
    left = np.asarray(official["y"], dtype=float)
    right = np.asarray(independent["y"], dtype=float)
    absolute = np.abs(left - right)
    relative = np.zeros(5)
    nonzero = np.abs(left) > 1e-12
    relative[nonzero] = absolute[nonzero] / np.abs(left[nonzero])
    return {"case": key, "z_exact": official["z"] == independent["z"],
            "r_exact": official["r"] == independent["r"],
            "w_exact": official["w"] == independent["w"],
            "max_abs_error": float(absolute.max()),
            "max_relative_error": float(relative.max())}


def main() -> None:
    changed_rows = []
    for case_id in CHANGED:
        first = Path(f"/private/tmp/0018_core_2b_run1_case{case_id[-2:]}.json")
        second = Path(f"/private/tmp/0018_core_2b_run2_case{case_id[-2:]}.json")
        if not first.is_file() or not second.is_file() or first.read_bytes() != second.read_bytes():
            raise RuntimeError(f"clean official repeats differ or are missing: {case_id}")
        case_root = TASK / "hidden/cases" / case_id
        independent = json.loads((case_root / "output.json").read_text())
        official = json.loads(first.read_text())
        row = compare(official, independent.copy(), f"hidden/{case_id}")
        if not row["z_exact"] or not row["r_exact"] or not row["w_exact"]:
            raise RuntimeError(f"official-independent clusters differ: {row}")
        changed_rows.append(row)
        write(EVIDENCE / "independent/hidden" / f"{case_id}.json", independent)
        shutil.copyfile(first, EVIDENCE / "official/hidden" / f"{case_id}.json")
        shutil.copyfile(first, case_root / "output.json")

    rows = []
    for split in ("public", "hidden"):
        for case_root in sorted((TASK / split / "cases").glob("case_*")):
            official_path = EVIDENCE / "official" / split / f"{case_root.name}.json"
            independent_path = EVIDENCE / "independent" / split / f"{case_root.name}.json"
            official = json.loads(official_path.read_text())
            independent = json.loads(independent_path.read_text())
            if official != json.loads((case_root / "output.json").read_text()):
                raise RuntimeError(f"installed gold differs: {split}/{case_root.name}")
            row = compare(official, independent, f"{split}/{case_root.name}")
            if not row["z_exact"] or not row["r_exact"] or not row["w_exact"]:
                raise RuntimeError(f"official-independent clusters differ: {row}")
            rows.append(row)
    max_abs = max(row["max_abs_error"] for row in rows)
    max_rel = max(row["max_relative_error"] for row in rows)
    atol = max(1e-6, 5 * max_abs)
    rtol = max(1e-7, 5 * max_rel)
    if atol > .05 or rtol > 1e-4:
        raise RuntimeError(f"derived tolerance exceeds cap: {(atol, rtol)}")
    tolerances_path = TASK / "hidden/tolerances.json"
    tolerances = json.loads(tolerances_path.read_text())
    tolerances["field_rules"]["y"] = {"atol": atol, "rtol": rtol}
    write(tolerances_path, tolerances)

    provenance_path = TASK / "hidden/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    for record in provenance["cases"]:
        case_root = TASK / record["split"] / "cases" / record["case_id"]
        record["input_sha256"] = sha(case_root / "input.json")
        record["output_sha256"] = sha(case_root / "output.json")
        record["gold_source"] = "official_pinned_adapter_two_clean_checkouts"
    provenance["promotion_blockers"] = [
        "G4 parameter robustness must be rerun under rederived tolerances",
        "G8 curator reference must be rerun after hidden redesign",
        "G6 blind identification blocked by upstream 429",
        "G7 must be rerun on the final redesigned bundle",
    ]
    write(provenance_path, provenance)
    write(EVIDENCE / "report.json", {
        "task_id": TASK.name,
        "status": "official_independent_pass_curator_stale",
        "official_commit": "c162068f61bafbe640bbd40ee4a47312498ed153",
        "official_clean_repeats_exact": True,
        "redesigned_clean_repeat_cases": list(CHANGED),
        "rows": rows,
        "max_abs_error": max_abs,
        "max_relative_error": max_rel,
        "derived_atol": atol,
        "derived_rtol": rtol,
        "implementation_sha256": {
            "official_adapter": sha(ROOT / "curation_tools/energy_tsa_core_adapter.py"),
            "independent_scipy": sha(ROOT / "curation_tools/energy_tsa_core_scientific.py"),
            "shared_numeric": sha(ROOT / "curation_tools/energy_tsa_core_common.py"),
        },
    })


if __name__ == "__main__":
    main()
