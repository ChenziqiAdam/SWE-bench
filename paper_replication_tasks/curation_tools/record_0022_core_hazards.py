#!/usr/bin/env python3
"""Materialize the hidden-hazard and scientific-shortcut coverage matrix."""

import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
provenance=json.loads((ROOT/"scibench_replication_0022_core/hidden/provenance.json").read_text())
shortcuts=json.loads((ROOT/"curation_reports/0022_core_shortcuts.json").read_text())
matrix=shortcuts["case_by_shortcut"]
rows=[]
for design in provenance["case_design"]:
    case_id=design["case_id"]
    rejected=[name for name,checks in matrix.items() if checks[f"hidden:{case_id}"] is False]
    rows.append({**design,"expected_invariant":"finite complete recurrence with sketch-norm-one new column and stable top-budget coefficient support","rejected_shortcuts":rejected})
report={"schema_version":1,"task_id":provenance["task_id"],"status":"passed",
        "sources":[{"title":"A sketch-and-select Arnoldi process","version":"arXiv:2306.03592v3 / SIAM DOI 10.1137/23M1588007","sha256":provenance["paper_sha256"],"evidence":"Sections 2-4 and 6: canonical pinv selection, conditioning, starting-vector sensitivity, and comparison with truncated Arnoldi"},{"title":"Pinned official MATLAB realization","version":provenance["commit"],"sha256":provenance["official_source_sha256"],"evidence":"paper_ssa_final_test1a.m sketch-and-select Arnoldi (pinv) block"}],
        "hidden_hazards":rows,"coverage_complete":all(len(row["rejected_shortcuts"])==len(matrix) for row in rows),
        "shortcut_names":sorted(matrix),"case_by_shortcut":matrix}
(ROOT/"curation_reports/0022_core_hazards.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
