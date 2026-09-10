#!/usr/bin/env python3
"""Materialize the hidden-hazard x scientific-shortcut coverage matrix for 0023_core."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

provenance = json.loads((ROOT / "scibench_replication_0023_core/hidden/provenance.json").read_text())
validation = json.loads((ROOT / "curation_reports/0023_core_validation.json").read_text())
_g7_path = ROOT / "curation_reports/0023_core_g7.json"
g7 = json.loads(_g7_path.read_text()) if _g7_path.is_file() else {}
# case_by_shortcut is keyed "split:case_id" -> {shortcut_name: passed_bool}
matrix = validation["case_by_shortcut"]
shortcut_names = sorted({m for row in matrix.values() for m in row})

HAZARD_INVARIANT = {
    "SIR analytic single founder": "CDF matches the closed form q + (1-q)(1-e^{-(1-q)w}); "
    "w_moments match k!/(1-q)^k (W | W>0)",
    "near-critical growth": "small lambda forces a long recursion (large kappa); the CDF stays monotone and reaches 1",
    "quadratic high extinction": "w_cdf(0) equals the large q_star; the conditional tail is a proper exponential-type decay",
    "strong type asymmetry": "the multinomial moment aggregation over a mixed multi-type founder set is exact",
    "low moment count": "the 3-moment truncation shifts the CDF ~7e-3 from an n=30 computation; gold is the correct n=3 result",
    "low moment count near-critical": "small n and small lambda: the n=4 truncation shifts the CDF ~4e-3 from n=30, long recursion",
    "large embedding step": "the embedded progeny GF over a long step and mu=exp(lambda h) leave the answer h-insensitive within tolerance",
    "multi-founder SEIR": "phi_W = prod_i phi_{W_i}^{Z0_i}; the multinomial moment aggregation over 7 founders is exact",
}


def rejected_for(case_id: str) -> list[str]:
    row = matrix.get(f"hidden:{case_id}", {})
    return sorted(name for name, passed in row.items() if not passed)


rows = []
for design in provenance["case_design"]:
    case_id = design["case_id"]
    rows.append(
        {
            **design,
            "expected_invariant": HAZARD_INVARIANT.get(design["hazard"], "see 0023_core_cases_design.md"),
            "rejected_shortcuts": rejected_for(case_id),
        }
    )

# Every shortcut must be rejected by at least one hidden case (== the
# all_shortcuts_fail_hidden gate); each hazard case additionally rejects its
# targeted shortcuts (see 0023_core_cases_design.md).
rejected_anywhere = {s for r in rows for s in r["rejected_shortcuts"]}
coverage_complete = rejected_anywhere == set(shortcut_names)

report = {
    "schema_version": 1,
    "task_id": provenance["task_id"],
    "status": "passed" if coverage_complete else "incomplete",
    "g8_status": "waiver",
    "scientific_contract": "core_algorithm_audits/0023.md (Scientific Contract section)",
    "contribution_graph": "core_algorithm_audits/0023.md (Contribution graph section)",
    "sources": [
        {
            "title": "Computation of random time-shift distributions for stochastic population models",
            "authors": "Morris, Maclean & Black",
            "version": "J. Math. Biol. 89:33 (2024), DOI 10.1007/s00285-024-02132-6",
            "sha256": provenance["paper_sha256"],
            "evidence": "Sections 3.2-3.6 (moment engine, Taylor LST, recursive contraction, CME inversion, moment matching); "
            "Eq. 41-42 (SIR closed form)",
        },
        {
            "title": "Approximating the distribution of a random walk with heavy tails / limiting martingale W",
            "authors": "Barbour, Hamza, Kaspi & Klebaner",
            "version": "Ann. Appl. Probab. 25 (2015)",
            "sha256": None,
            "evidence": "Existence of the random time-shift limit that this paper makes computable (origin paper)",
        },
        {
            "title": "A concentrated matrix exponential distribution / numerical inverse Laplace transform",
            "authors": "Horvath, Sekcova & Telek",
            "version": "2020; coefficient table http://inverselaplace.org/",
            "sha256": provenance["cme_table_sha256"],
            "evidence": "21-term quadrature used for the LST inversion (supplied as cme_coefficients input data)",
        },
        {
            "title": "Pinned Python-port oracle of RandomTimeShifts.jl",
            "authors": "curator port",
            "version": provenance["commit"],
            "sha256": provenance["official_adapter_sha256"],
            "evidence": "rts_core_adapter.py (follows paper Eq. 19 (n+1)! where the Julia uses n!); "
            "G8 waiver recorded in curation_reports/0023_core_oracle.json",
        },
        {
            "title": f"Blind implementation agent submission (G7 {g7.get('G7', '?')})",
            "authors": f"{g7.get('model', 'blind agent')}, public bundle only",
            "version": "curation_reports/0023_core_g7.json",
            "sha256": g7.get("solution_sha256"),
            "evidence": f"score {g7.get('score')}, full_success {g7.get('full_success')}; "
            "core_algorithm_audits/0023_core_g7_submission/",
        },
    ],
    "hidden_hazards": rows,
    "coverage_complete": coverage_complete,
    "shortcuts_rejected_by_case_count": {
        s: sum(1 for r in rows if s in r["rejected_shortcuts"]) for s in shortcut_names
    },
    "shortcut_names": shortcut_names,
    "case_by_shortcut": matrix,
    "shortcut_hidden_scores": validation["shortcut_hidden_scores"],
    "maximum_shortcut_hidden_score": validation["maximum_shortcut_hidden_score"],
    "maximum_shortcut_total_score": validation["maximum_shortcut_total_score"],
    "public_memorizer_score": validation["public_memorizer_score"],
}
(ROOT / "curation_reports/0023_core_hazards.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n"
)
print(json.dumps({"status": report["status"], "coverage_complete": report["coverage_complete"]}, indent=2))
