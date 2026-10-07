# Independent audit of the 7 foreknowledge-flagged laws (2026-10-07)

Fresh Opus 5.5 agent; saw only the 7 law texts and pristine upstream `d6c09c9a4` (no checkers, no curator notes).
Scripts: `.sanitizer_eval_workspace/audit_nl/work/`. Result: no real library bug behind any of the 7.

| Law | Verdict | Key number |
|---|---|---|
| GLM-003 | law correct, library OK | max C 1.37 (mpmath, 250k p), 2.98 via `Contrast` |
| GLM-006 | law correct, library OK | max C 19.2 (kappa 1.4), 1.04 at kappa 6e4 |
| GLM-008 | law correct, library OK | 526k pairs, max error 6e-4 of tolerance |
| SIG-003 | tolerance model incomplete | float32 mean error grows ~n (1e5 rows: 0.07 %; 2e6: 1.8 %) |
| SIG-007 | law correct, library OK | 0 violations / 80,000 cases incl. boundary +-1ulp |
| THR-001 | law correct, library OK | max ratio/alpha 0.9999; 545/600 finite thresholds |
| CON-008 | law correct, library OK | 600 fits, off-diagonals exactly 0; alpha_max tight |

Notes / follow-up (law text; checker already conforms except where stated):
- GLM-003: add `p + one_minus_p ~ 1` to the precondition (only violable by calling private `glm._utils.z_score` directly).
- GLM-006: C must be >= ~32; kappa should be max over labels.
- THR-001: R counts |stat| >= u in the two-sided case, n = masked voxel count. Checker already receives abs(stats).
- SIG-003: the `|mean| < finfo(float64).eps` zeroing is already excluded by the checker (`abs(mean) > _EPS`); the law
  text lacks it. Open question: float32 columns of 1e5+ rows lose accuracy in the mean (numpy sums float32 without
  pairwise summation along axis 0). The auditor calls this numpy precision, not a nilearn defect; curator adjudication
  had scored it as a library accuracy limitation (same class as SIG-001/008). Both readings are defensible.
