# Core Algorithm Review v2

Model: `stealth/ox-alpha`

| Paper | Core algorithm | G1–G5 | Decision | Evidence gaps |
| --- | --- | --- | --- | --- |
| 0011 | — | — | FAILED | full-review failed after 4 attempts: selected_core_algorithm is not a candidate |
| 0014 | — | — | FAILED | full-review failed after 4 attempts: $.evidence_catalog[4].excerpt does not match PDF page 2 |
| 0015 | — | — | FAILED | full-review failed after 4 attempts: $.evidence_catalog[1].excerpt does not match PDF page 3 |
| 0017 | — | — | FAILED | full-review failed after 4 attempts: $.evidence_catalog[1].excerpt does not match PDF page 12 |
| 0018 | Storage importance subsampling framework | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Exact clustering implementation details (Wald hierarchical) only briefly described; Operation model rolling-horizon details given only in prose |
| 0019 | — | — | FAILED | full-review failed after 4 attempts: scientific_contract must be null without selected core |
| 0020 | SUR-SLM maximum likelihood estimation | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Paper does not provide closed-form likelihood derivation details, relying on Lopez et al. 2014 and spsur package references. |
| 0021 | rEIM greedy rational interpolation (Algorithm 2.1) | G1:PASS, G2:PASS, G3:PASS, G4:PASS, G5:PASS | ACCEPT_FOR_DESIGN | Exact practical choices of B and Σ are repository-tuned, not fully specified in paper. |
| 0022 | — | — | FAILED | full-review failed after 4 attempts: selected core and core-role count inconsistent |
