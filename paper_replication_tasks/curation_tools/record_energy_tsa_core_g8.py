#!/usr/bin/env python3
"""Record the reproducible official/independent portion of 0018_core G8."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from energy_tsa_core_common import TASK_ID

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / TASK_ID
TEMP = Path("/private/tmp")
EVIDENCE = ROOT / "curation_reports/official_runs/0018_core/g8_official_independent"
CURATOR_REPORT = ROOT / "curation_reports/official_runs/0018_core/g8_curator_reference/report.json"
COMBINED_REPORT = ROOT / "curation_reports/official_runs/0018_core/g8/report.json"

INDEPENDENT = {
    "public/case_01": "0018_core_independent_public_01.json",
    "public/case_02": "0018_core_independent_public_02.json",
    "public/case_03": "0018_core_independent_public_03_onebus.json",
    "hidden/case_01": "0018_core_independent_hidden_01_q1.json",
    "hidden/case_02": "0018_core_independent_h2_fixed.json",
    "hidden/case_03": "0018_core_independent_hidden_03.json",
    "hidden/case_04": "0018_core_independent_hidden_04.json",
    "hidden/case_05": "0018_core_independent_h5_fixed.json",
    "hidden/case_06": "0018_core_independent_h6_fixed.json",
    "hidden/case_07": "0018_core_independent_hidden_07_q1.json",
    "hidden/case_08": "0018_core_independent_hidden_08.json",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main() -> None:
    rows = []
    max_abs = 0.0
    max_rel = 0.0
    for key, independent_name in INDEPENDENT.items():
        split, case_id = key.split("/")
        official = TEMP / f"0018_core_official2_{split}_{case_id[-2:]}.json"
        independent = TEMP / independent_name
        gold = TASK / split / "cases" / case_id / "output.json"
        if not official.is_file() or not independent.is_file():
            raise FileNotFoundError(key)
        official_value = json.loads(official.read_text())
        independent_value = json.loads(independent.read_text())
        independent_value.pop("diagnostics", None)
        if official_value != json.loads(gold.read_text()):
            raise AssertionError(f"gold differs from clean official output: {key}")
        y_official = np.asarray(official_value["y"], dtype=float)
        y_independent = np.asarray(independent_value["y"], dtype=float)
        absolute = np.abs(y_official - y_independent)
        nonzero = np.abs(y_official) > 1e-12
        relative = np.zeros(5)
        relative[nonzero] = absolute[nonzero] / np.abs(y_official[nonzero])
        row = {
            "case": key,
            "z_exact": official_value["z"] == independent_value["z"],
            "r_exact": official_value["r"] == independent_value["r"],
            "w_exact": official_value["w"] == independent_value["w"],
            "max_abs_error": float(absolute.max()),
            "max_relative_error": float(relative.max()),
        }
        if not row["z_exact"] or not row["r_exact"] or not row["w_exact"]:
            raise AssertionError(row)
        rows.append(row)
        max_abs = max(max_abs, row["max_abs_error"])
        max_rel = max(max_rel, row["max_relative_error"])
        for kind, source in (("official", official), ("independent", independent)):
            target = EVIDENCE / kind / split / f"{case_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    atol = max(1e-6, 5 * max_abs)
    rtol = max(1e-7, 5 * max_rel)
    if atol > .05 or rtol > 1e-4:
        raise AssertionError((atol, rtol))
    curator = json.loads(CURATOR_REPORT.read_text())
    curator_solution = ROOT / "core_algorithm_audits/0018_core_curator_submission/solution.py"
    curator_manifest = curator_solution.with_name("submission.json")
    if not (
        curator.get("G8_curator_reference") == "PASS"
        and curator.get("public_score") == curator.get("hidden_score") == 1.0
        and curator.get("full_success") is True
        and curator.get("submission_sha256") == sha(curator_solution)
        and curator.get("submission_manifest_sha256") == sha(curator_manifest)
        and len(curator.get("cases", [])) == 11
        and all(row.get("exit_code") == 0 and row.get("timed_out") is False
                and row.get("wall_seconds", 600) < 600 for row in curator["cases"])
    ):
        raise AssertionError("curator reference evidence is stale or incomplete")
    tolerance_path = TASK / "hidden/tolerances.json"
    tolerances = json.loads(tolerance_path.read_text())
    tolerances["field_rules"]["y"] = {"atol": atol, "rtol": rtol}
    write(tolerance_path, tolerances)

    provenance_path = TASK / "hidden/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    for record in provenance["cases"]:
        case_root = TASK / record["split"] / "cases" / record["case_id"]
        record["input_sha256"] = sha(case_root / "input.json")
        record["output_sha256"] = sha(case_root / "output.json")
        record["gold_source"] = "official_pinned_adapter_two_clean_checkouts"
    provenance["g8_audit"] = {
        "status": "pass",
        "evidence": "curation_reports/official_runs/0018_core/g8/report.json",
        "official_independent_evidence": "curation_reports/official_runs/0018_core/g8_official_independent/report.json",
        "curator_reference_evidence": "curation_reports/official_runs/0018_core/g8_curator_reference/report.json",
        "official_clean_repeats_exact": True,
        "z_r_w_exact_all_cases": True,
        "y_max_abs_error": max_abs,
        "y_max_relative_error": max_rel,
        "derived_atol": atol,
        "derived_rtol": rtol,
        "curator_reference_public_hidden_score": [1.0, 1.0],
    }
    provenance["implementation_sha256"] = {
        "official_adapter": sha(ROOT / "curation_tools/energy_tsa_core_adapter.py"),
        "independent_scipy": sha(ROOT / "curation_tools/energy_tsa_core_scientific.py"),
        "shared_numeric": sha(ROOT / "curation_tools/energy_tsa_core_common.py"),
    }
    provenance["implementation_sha256"]["curator_reference_submission"] = sha(curator_solution)
    provenance["promotion_blockers"] = [
        "G6 blind identification not run",
        "G7 blind implementation not run",
    ]
    write(provenance_path, provenance)
    write(EVIDENCE / "report.json", {
        "task_id": TASK_ID,
        "status": "official_independent_pass_curator_pending",
        "official_commit": "c162068f61bafbe640bbd40ee4a47312498ed153",
        "official_clean_repeats_exact": True,
        "rows": rows,
        "max_abs_error": max_abs,
        "max_relative_error": max_rel,
        "derived_atol": atol,
        "derived_rtol": rtol,
        "implementation_sha256": provenance["implementation_sha256"],
    })
    write(COMBINED_REPORT, {
        "schema_version": 1,
        "task_id": TASK_ID,
        "G8": "PASS",
        "official_commit": "c162068f61bafbe640bbd40ee4a47312498ed153",
        "official_clean_repeats_exact": True,
        "official_independent_rows": rows,
        "z_r_w_exact_all_cases": True,
        "max_abs_error": max_abs,
        "max_relative_error": max_rel,
        "derived_atol": atol,
        "derived_rtol": rtol,
        "curator_reference": {
            "public_score": curator["public_score"],
            "hidden_score": curator["hidden_score"],
            "full_success": curator["full_success"],
            "submission_sha256": curator["submission_sha256"],
            "evidence": "../g8_curator_reference/report.json",
        },
        "implementation_sha256": provenance["implementation_sha256"],
        "provenance_independence": {
            "official_oracle": "pinned official Calliope/CBC source checkout",
            "independent_scientific": "separately authored SciPy/HiGHS mathematical implementation",
            "curator_reference": "unified-runner wrapper over registered scientific implementation; evaluator-path evidence only",
        },
    })


if __name__ == "__main__":
    main()
