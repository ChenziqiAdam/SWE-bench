#!/usr/bin/env python3
"""Record a public-equivalent, hidden-divergent 0018_core implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

import energy_tsa_core_scientific as scientific


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
REPORT = ROOT / "curation_reports/official_runs/0018_core/identifiability/report.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(case: Path, atol: float, rtol: float) -> dict[str, object]:
    result = scientific.solve(json.loads((case / "input.json").read_text()))
    gold = json.loads((case / "output.json").read_text())
    actual_y = np.asarray(result["y"], dtype=float)
    expected_y = np.asarray(gold["y"], dtype=float)
    return {
        "case": case.relative_to(TASK).as_posix(),
        "z_exact": result["z"] == gold["z"],
        "r_exact": result["r"] == gold["r"],
        "w_exact": result["w"] == gold["w"],
        "y_pass": bool(np.all(np.abs(actual_y - expected_y) <= atol + rtol * np.abs(expected_y))),
        "y_max_abs_error": float(np.max(np.abs(actual_y - expected_y))),
    }


def main() -> None:
    tolerances = json.loads((TASK / "hidden/tolerances.json").read_text())["field_rules"]["y"]
    original = float(scientific.CAP_COST[13])
    alternative = 150.05
    scientific.CAP_COST[13] = alternative
    try:
        public = [compare(case, tolerances["atol"], tolerances["rtol"])
                  for case in sorted((TASK / "public/cases").glob("case_*"))]
        hidden = compare(TASK / "hidden/cases/case_02", tolerances["atol"], tolerances["rtol"])
    finally:
        scientific.CAP_COST[13] = original
    report = {
        "schema_version": 1,
        "task_id": TASK.name,
        "G4": "FAIL",
        "conclusion": (
            "The public bundle is not executable-closure complete: two parameterizations "
            "allowed by the paper are indistinguishable on all public cases but diverge on hidden case_02."
        ),
        "paper_evidence": (
            "Appendix B, Table B.4 prints the Region 1-5 transmission cost as 150,000 and "
            "states only that regional costs are perturbed slightly (<0.1%); it does not "
            "specify the perturbation."
        ),
        "official_parameter": original,
        "alternative_parameter": alternative,
        "alternative_relative_perturbation": (alternative - 150.0) / 150.0,
        "parameter": "CAP_COST[13], Region 1-5 transmission annual install cost (thousand GBP/MWyr)",
        "public_results": public,
        "hidden_result": hidden,
        "public_equivalent": all(
            row["z_exact"] and row["r_exact"] and row["w_exact"] and row["y_pass"] for row in public
        ),
        "hidden_divergent": not (
            hidden["z_exact"] and hidden["r_exact"] and hidden["w_exact"] and hidden["y_pass"]
        ),
        "tolerances": tolerances,
        "hashes": {
            "paper": sha(TASK / "public/paper.pdf"),
            "scientific_implementation": sha(ROOT / "curation_tools/energy_tsa_core_scientific.py"),
            "recorder": sha(Path(__file__)),
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not report["public_equivalent"] or not report["hidden_divergent"]:
        raise RuntimeError("identifiability counterexample did not reproduce")


if __name__ == "__main__":
    main()
