#!/usr/bin/env python3
"""Finalize G8 evidence after the 0018_core 2B redesign."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
OFFICIAL = ROOT / "curation_reports/official_runs/0018_core/g8_official_independent/report.json"
CURATOR = ROOT / "curation_reports/official_runs/0018_core/g8_curator_reference/report.json"
REPORT = ROOT / "curation_reports/official_runs/0018_core/g8/report.json"
G5 = ROOT / "curation_reports/official_runs/0018_core/g5_shortcuts/report.json"
ROBUSTNESS = ROOT / "curation_reports/official_runs/0018_core/parameter_robustness/report.json"
CLOSURE = ROOT / "curation_reports/official_runs/0018_core/executable_closure/report.json"
G7 = ROOT / "curation_reports/0018_core_g7.json"
G6 = ROOT / "core_algorithm_audits/0018_core_blind.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    official = json.loads(OFFICIAL.read_text())
    curator = json.loads(CURATOR.read_text())
    g5 = json.loads(G5.read_text())
    robustness = json.loads(ROBUSTNESS.read_text())
    curator_solution = ROOT / "core_algorithm_audits/0018_core_curator_submission/solution.py"
    curator_manifest = curator_solution.with_name("submission.json")
    if not (
        official.get("official_clean_repeats_exact") is True
        and len(official.get("rows", [])) == 11
        and all(row["z_exact"] and row["r_exact"] and row["w_exact"] for row in official["rows"])
        and official["derived_atol"] <= .05 and official["derived_rtol"] <= 1e-4
        and curator.get("G8_curator_reference") == "PASS"
        and curator.get("public_score") == curator.get("hidden_score") == 1.0
        and curator.get("full_success") is True
        and curator.get("submission_sha256") == sha(curator_solution)
        and curator.get("submission_manifest_sha256") == sha(curator_manifest)
        and len(curator.get("cases", [])) == 11
        and all(not row["timed_out"] and row["exit_code"] == 0 and row["wall_seconds"] < 600
                for row in curator["cases"])
        and g5.get("G5") == "PASS"
        and robustness.get("G4") == "PASS"
    ):
        raise RuntimeError("G8 evidence is incomplete or stale")
    implementations = {
        **official["implementation_sha256"],
        "curator_reference_submission": sha(curator_solution),
    }
    report = {
        "schema_version": 1,
        "task_id": TASK.name,
        "G8": "PASS",
        "official_commit": official["official_commit"],
        "official_clean_repeats_exact": True,
        "official_independent_rows": official["rows"],
        "z_r_w_exact_all_cases": True,
        "max_abs_error": official["max_abs_error"],
        "max_relative_error": official["max_relative_error"],
        "derived_atol": official["derived_atol"],
        "derived_rtol": official["derived_rtol"],
        "curator_reference": {
            "public_score": curator["public_score"],
            "hidden_score": curator["hidden_score"],
            "full_success": curator["full_success"],
            "submission_sha256": curator["submission_sha256"],
            "evidence": "../g8_curator_reference/report.json",
        },
        "implementation_sha256": implementations,
        "provenance_independence": {
            "official_oracle": "pinned official Calliope/CBC source checkout",
            "independent_scientific": "separately authored SciPy/HiGHS mathematical implementation",
            "curator_reference": "unified-runner wrapper over the registered scientific implementation",
        },
    }
    write(REPORT, report)
    provenance_path = TASK / "hidden/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["g8_audit"] = {
        "status": "pass", "evidence": REPORT.relative_to(ROOT).as_posix(),
        "official_independent_evidence": OFFICIAL.relative_to(ROOT).as_posix(),
        "curator_reference_evidence": CURATOR.relative_to(ROOT).as_posix(),
        "official_clean_repeats_exact": True, "z_r_w_exact_all_cases": True,
        "y_max_abs_error": official["max_abs_error"],
        "y_max_relative_error": official["max_relative_error"],
        "derived_atol": official["derived_atol"], "derived_rtol": official["derived_rtol"],
        "curator_reference_public_hidden_score": [1.0, 1.0],
    }
    provenance["g5_audit"] = {
        "status": "pass", "evidence": G5.relative_to(ROOT).as_posix(),
        "hazards_covered": 8,
        "maximum_shortcut_hidden_score": g5["maximum_shortcut_hidden_score"],
    }
    provenance["implementation_sha256"] = implementations
    provenance["lifecycle"] = "candidate_ready"
    provenance["readiness_scope"] = "research candidate; not active validated benchmark"
    if G6.is_file():
        g6 = json.loads(G6.read_text())
        provenance["g6_audit"] = {
            "status": str(g6.get("G6", "FAIL")).lower(),
            "evidence": G6.relative_to(ROOT).as_posix(),
            "evidence_sha256": sha(G6),
            "pass_count": g6.get("pass_count"),
            "independent_contexts": g6.get("independent_contexts"),
            "configured_model": g6.get("configured_model"),
            "fallback_model": g6.get("fallback_model"),
        }
    if G7.is_file():
        g7 = json.loads(G7.read_text())
        provenance["g7_audit"] = {
            "status": str(g7.get("G7", "FAIL")).lower(),
            "evidence": G7.relative_to(ROOT).as_posix(),
            "evidence_sha256": sha(G7),
            "model": g7.get("model"),
            "public_hidden_score": [g7.get("public_score"), g7.get("hidden_score")],
            "solution_sha256": g7.get("solution_sha256"),
            "codex_exit_code": g7.get("codex_exit_code"),
            "all_cases_executed_without_timeout": (
                len(g7.get("cases", [])) == 11
                and all(row.get("exit_code") == 0 and not row.get("timed_out")
                        for row in g7["cases"])
            ),
        }
    provenance["promotion_blockers"] = []
    if not G6.is_file() or json.loads(G6.read_text()).get("G6") != "PASS":
        provenance["promotion_blockers"].append("G6 blind identification has not passed")
    if not G7.is_file() or json.loads(G7.read_text()).get("G7") != "PASS":
        latest_g7 = json.loads(G7.read_text()) if G7.is_file() else {}
        if "public_score" in latest_g7:
            detail = (f"latest attempt scored public/hidden "
                      f"{latest_g7.get('public_score')}/{latest_g7.get('hidden_score')}")
        else:
            detail = "latest attempt produced no solution.py"
        provenance["promotion_blockers"].append(
            f"G7 blind implementation has not passed; {detail}")
    provenance["known_failures"] = ["G7_blind_implementation"]
    write(provenance_path, provenance)
    write(CLOSURE, {
        "schema_version": 1,
        "task_id": TASK.name,
        "G4": "PASS",
        "conclusion": (
            "The 2B redesign removes the demonstrated hidden dependence on paper-unspecified "
            "parameters without relaxing tolerances or scientific shortcut coverage."
        ),
        "parameter_robustness_evidence": ROBUSTNESS.relative_to(ROOT).as_posix(),
        "parameter_robustness_sha256": sha(ROBUSTNESS),
        "registered_variants": [row["variant"] for row in robustness["variants"]],
        "all_registered_variants_public_hidden_pass": True,
        "rederived_tolerances": {"atol": official["derived_atol"], "rtol": official["derived_rtol"]},
        "shortcut_evidence": G5.relative_to(ROOT).as_posix(),
        "shortcut_evidence_sha256": sha(G5),
        "historical_failure": {
            "evidence": "curation_reports/official_runs/0018_core/identifiability/report.json",
            "status": "superseded_by_hidden_redesign",
            "description": "The former hidden case_02 distinguished 150.15 from paper-consistent 150.05."
        },
        "paper_sha256": sha(TASK / "public/paper.pdf"),
        "official_commit": official["official_commit"],
        "limitation": (
            "This is constructive robustness over the registered public-equivalent uncertainty set, "
            "not a proof over every possible implementation. G7 remains required before promotion."
        ),
    })


if __name__ == "__main__":
    main()
