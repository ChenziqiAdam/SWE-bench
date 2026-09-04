#!/usr/bin/env python3
"""Build 0017_core from two pinned sobiEquity checkouts and literature evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import tempfile
from pathlib import Path

import numpy as np

from sobiEquity_core_adapter import COMMIT, solve as official_solve
from sobiEquity_core_common import FIXTURE_SHA256
from sobiEquity_core_scientific import scientific_metrics, solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0017_core"
LEGACY_ID = "scibench_replication_0017"
CASES = {
    "public": [
        {"threshold": 5, "hub_filter": "conventional_active"},
        {"threshold": 5, "hub_filter": "all_active"},
        {"threshold": 10, "hub_filter": "conventional_active"},
    ],
    "hidden": [
        {"threshold": 0.5, "hub_filter": "conventional_active"},
        {"threshold": 4, "hub_filter": "all_active"},
        {"threshold": 8, "hub_filter": "conventional_active"},
        {"threshold": 17, "hub_filter": "all_active"},
        {"threshold": 30, "hub_filter": "conventional_active"},
    ],
}
EXPECTED_REACHABILITY = [(188, 187, 103), (5889, 4497, 129), (18586, 6740, 119), (80969, 9162, 131), (190179, 10733, 119)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def discrepancy(left: dict, right: dict) -> tuple[float, float]:
    maximum = squared = 0.0
    count = 0
    for key in ("hub", "level_of_service", "population_unit", "accessibility"):
        a = np.asarray(left[key], dtype=float); b = np.asarray(right[key], dtype=float)
        if a.shape != b.shape:
            raise RuntimeError(f"independent output shape differs for {key}")
        delta = np.abs(a - b)
        maximum = max(maximum, float(delta.max(initial=0)))
        squared += float(np.square(delta).sum()); count += delta.size
    return maximum, float(np.sqrt(squared / max(count, 1)))


def hazard_catalog(target_hash: str, source_hash: str, baseline_hash: str) -> list[dict]:
    target = {"paper": "Desjardins, Higgins & Paez (2022)", "doi": "10.1016/j.trd.2021.103091", "version": "Transportation Research Part D 102:103091", "sha256": target_hash}
    source = {"paper": "Paez, Higgins & Vivona (2019)", "doi": "10.1371/journal.pone.0218773", "version": "PLOS ONE 14(6):e0218773 printable PDF", "sha256": source_hash}
    baseline = {"paper": "Luo & Qi (2009)", "doi": "10.1016/j.healthplace.2009.06.002", "version": "Health & Place 15(4), publisher HTML", "sha256": baseline_hash}
    invariants = ["origin weights sum to one over reachable hubs", "hub weights sum to one over reachable origins", "reachable population is allocated once", "level of service is allocated once", "sum accessibility equals sum level of service", "only nonzero-denominator entities are output"]
    return [
        {"hazard_id": "HZ1", "source": source, "evidence": "Sections 'A numerical example' and 'Suboptimal system configurations': peripheral origins and zero-reach structure expose demand/supply inflation and undefined denominators.", "failure_mode": "sparse and disconnected catchments", "construction": "0.5-minute binary threshold on original Hamilton network", "expected_invariants": invariants, "faults": ["retain_zero_denominators", "global_normalization", "conventional_2sfca"], "hidden_cases": ["case_01"]},
        {"hazard_id": "HZ2", "source": baseline, "evidence": "The baseline defines inclusive threshold catchments and introduces distance-zone decay; BFCA retains the binary inclusive boundary without importing that extension.", "failure_mode": "threshold endpoint or distance-decay model substituted for BFCA", "construction": "new 4-minute threshold including exact-boundary paths and ERI stations", "expected_invariants": invariants, "faults": ["strict_threshold", "ignore_hub_filter", "distance_decay"], "hidden_cases": ["case_02"]},
        {"hazard_id": "HZ3", "source": target, "evidence": "Accessibility peaks near five minutes and decreases substantially after eight minutes as demand reaches limited supply.", "failure_mode": "congestion transition hidden by one-sided or conventional normalization", "construction": "8-minute conventional-active system", "expected_invariants": invariants, "faults": ["origin_only", "hub_only", "conventional_2sfca"], "hidden_cases": ["case_03"]},
        {"hazard_id": "HZ4", "source": target, "evidence": "The paper compares 3, 5, 10 and 15 minutes and the inclusion of twelve equity stations.", "failure_mode": "interpolation/memorization over reported thresholds or conventional-only stations", "construction": "unreported 17-minute threshold with all active stations", "expected_invariants": invariants, "faults": ["ignore_hub_filter", "public_memorizer", "uniform_rack_capacity"], "hidden_cases": ["case_04"]},
        {"hazard_id": "HZ5", "source": source, "evidence": "Row/column standardization is required to avoid inflation under overlapping catchments; the numerical analysis emphasizes conservation as overlap grows.", "failure_mode": "extreme overlap, scale, and accumulation error", "construction": "maximum supported 30-minute matrix threshold with conventional stations", "expected_invariants": invariants, "faults": ["conventional_2sfca", "origin_only", "hub_only", "swapped_denominators", "uniform_population", "uniform_rack_capacity"], "hidden_cases": ["case_05"]},
    ]


INTERFACE = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
             "required": ["schema_version", "task_id", "entrypoint"],
             "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
                            "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    parser.add_argument("--bfca-paper", type=Path, required=True)
    parser.add_argument("--baseline-source", type=Path, required=True)
    args = parser.parse_args()
    destination = ROOT / TASK_ID
    evidence_destination = ROOT / "curation_reports/official_runs/0017_core"
    if destination.exists() or evidence_destination.exists():
        raise RuntimeError("refusing to overwrite existing task or evidence")
    legacy = ROOT / LEGACY_ID
    legacy_hashes_before = tree_hashes(legacy)
    flat = [(split, index, case) for split, values in CASES.items() for index, case in enumerate(values, 1)]
    with tempfile.TemporaryDirectory(prefix="scibench_0017_core_build_", dir=ROOT) as temporary:
        stage = Path(temporary); task = stage / TASK_ID; evidence = stage / "official_runs"
        literature = evidence / "literature"; literature.mkdir(parents=True)
        shutil.copyfile(args.bfca_paper, literature / "paez_higgins_vivona_2019.pdf")
        shutil.copyfile(args.baseline_source, literature / "luo_qi_2009_publisher.html")
        official_runs = []
        for run_index, checkout in enumerate((args.checkout_1, args.checkout_2), 1):
            run = []
            for split, index, case in flat:
                value = official_solve(case, checkout)
                run.append(value)
                write_json(evidence / f"run_{run_index}/{split}_case_{index:02d}.normalized.json", value)
            official_runs.append(run)
        run_hashes = [canonical_hash(run) for run in official_runs]
        if run_hashes[0] != run_hashes[1]:
            raise RuntimeError("official checkouts disagree")
        independent = [independent_solve(case) for _, _, case in flat]
        errors = [discrepancy(a, b) for a, b in zip(official_runs[0], independent)]
        max_abs = max(item[0] for item in errors); max_rmse = max(item[1] for item in errors)
        if max_abs > 1e-10 or max_rmse > 1e-11:
            raise RuntimeError(f"independent audit failed: {max_abs=}, {max_rmse=}")
        tolerance = {"comparison": "absolute_rmse", "max_abs": max(1e-11, 10 * max_abs), "rmse": max(2e-12, 10 * max_rmse)}
        (task / "public/data").mkdir(parents=True); (task / "hidden").mkdir(parents=True)
        shutil.copyfile(legacy / "public/paper.pdf", task / "public/paper.pdf")
        shutil.copyfile(legacy / "public/data/travel_time_matrix.csv", task / "public/data/travel_time_matrix.csv")
        if sha(task / "public/data/travel_time_matrix.csv") != FIXTURE_SHA256:
            raise RuntimeError("public matrix differs from archived fixture")
        (task / "public/task.md").write_text("solution.py\n", encoding="utf-8")
        write_json(task / "public/interface.schema.json", INTERFACE)
        records = []
        for offset, (split, index, case) in enumerate(flat):
            case_root = task / split / "cases" / f"case_{index:02d}"
            write_json(case_root / "input.json", case); write_json(case_root / "output.json", official_runs[0][offset])
            write_json(evidence / f"independent/{split}_case_{index:02d}.json", independent[offset])
            records.append({"split": split, "case_id": f"case_{index:02d}", "input_sha256": sha(case_root / "input.json"), "output_sha256": sha(case_root / "output.json"), "independent_error": {"max_abs": errors[offset][0], "rmse": errors[offset][1]}})
        metrics = [scientific_metrics(case) for case in CASES["hidden"]]
        measured = [(item["reachable_rows"], item["reachable_origins"], item["reachable_hubs"]) for item in metrics]
        if measured != EXPECTED_REACHABILITY:
            raise RuntimeError(f"hidden topology changed: {measured}")
        if any(max(item[key] for key in ("origin_weight_max_error", "hub_weight_max_error", "population_conservation_error", "service_conservation_error")) > 1e-10 for item in metrics):
            raise RuntimeError("scientific conservation invariant failed")
        catalog = hazard_catalog(sha(task / "public/paper.pdf"), sha(literature / "paez_higgins_vivona_2019.pdf"), sha(literature / "luo_qi_2009_publisher.html"))
        write_json(task / "hidden/tolerances.json", tolerance)
        write_json(task / "hidden/provenance.json", {"schema_version": 4, "task_id": TASK_ID, "lifecycle": "candidate_revise", "gold_source": "pinned_official_checkout", "legacy_predecessor": LEGACY_ID, "repository": "https://github.com/paezha/Accessibility-Sobi-Hamilton", "commit": COMMIT, "paper_sha256": sha(task / "public/paper.pdf"), "travel_time_matrix_sha256": FIXTURE_SHA256, "official_output_bundle_sha256": run_hashes, "official_reproduction": {"two_clean_checkouts": True, "adapter_sha256": sha(ROOT / "curation_tools/sobiEquity_core_adapter.py"), "driver_sha256": sha(ROOT / "curation_tools/sobiEquity_core_driver.R"), "evidence": "curation_reports/official_runs/0017_core"}, "independent_audit": {"implementation": "independent pandas formulation from the source paper", "implementation_sha256": sha(ROOT / "curation_tools/sobiEquity_core_scientific.py"), "maximum_absolute_discrepancy": max_abs, "maximum_rmse": max_rmse, "derived_tolerances": tolerance}, "environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()}, "scientific_hazard_catalog": catalog, "hidden_case_metrics": [{"case_id": f"case_{i:02d}", **value} for i, value in enumerate(metrics, 1)], "cases": records})
        report = {"schema_version": 1, "task_id": TASK_ID, "status": "oracle_passed", "G8": "PASS", "two_clean_checkouts_match": True, "official_output_bundle_sha256": run_hashes[0], "maximum_absolute_discrepancy": max_abs, "maximum_rmse": max_rmse, "tolerances": tolerance, "legacy_hashes_before": legacy_hashes_before}
        if tree_hashes(legacy) != legacy_hashes_before:
            raise RuntimeError("legacy 0017 changed during build")
        write_json(stage / "oracle.json", report)
        os.replace(task, destination)
        evidence_destination.parent.mkdir(parents=True, exist_ok=True); os.replace(evidence, evidence_destination)
        os.replace(stage / "oracle.json", ROOT / "curation_reports/0017_core_oracle.json")


if __name__ == "__main__":
    main()
