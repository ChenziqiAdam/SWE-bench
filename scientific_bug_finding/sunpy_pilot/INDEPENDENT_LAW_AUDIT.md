# Independent audit of the 7 foreknowledge-flagged laws (2026-10-08)

Fresh Opus 5.5 agent; saw only the 7 law texts (Pre/Law/Obs/Alarm) and pristine upstream `87d916c65` (no checkers, no
curator notes, no Why fields). Full report with derivations and scripts' results: `INDEPENDENT_LAW_AUDIT_report.md`.
Result: **all 7 laws are mathematically and physically correct as stated**; for 5 of them the agent independently
found library violations on valid inputs, consistent with what the fresh-agent runs triggered.

| Law | Law correct | Library | Key number |
|---|---|---|---|
| FRM-001 | yes | bug: back-facing look direction gets negative distance | (180 deg, 0): d = -1.0059 AU, D - d cos(alpha) = -rsun |
| FRM-002 | yes (forward ray) | same `make_3d` bug; predicate itself correct | 99/4000 all-sky disagreements, 0 on ~30k on-disk/near-limb |
| SCR-001 | yes | numerical: quadratic cancellation | 88.9 x the law tolerance (116 m) at |C|/R = 2.3e4; stable form 4e-4 x |
| MAP-001 | yes (integer dims) | bug: scale not updated for GONG, PC without CDELT/PC1_1, KeyError without PC1_2 | 13-28 px; standard headers <= 1.6e-12 px |
| MAP-002 | yes | same metadata code as MAP-001, same failures | GONG 853 px |
| MAP-003 | yes | OK | 0/3014 outside [min, max] incl. float32, 1e-30..1e30 |
| MAP-004 | yes | bug: CD-only header at scale 1 (14 px); GONG / CEA synoptic at scale != 1 (674 px, NaN) | standard headers <= 3.6e-13 px |

## Adjudication
- **Real, already covered:** FRM-001/002 (DRC-001 follows from it), MAP-001/002/004 (source-overridden `scale`).
- **New facets of the same MAP root cause** (metadata rescaling assumes `cdelt` + `pc1_1` present): PC without CDELT,
  PC without PC1_1, PC without off-diagonals (`KeyError`), CD-only `rotate` at scale 1, CEA synoptic maps at scale != 1.
  Candidates for the issue drafts.
- **SCR-001:** the auditor reports a cancellation-limited accuracy defect (116 m on a 1 AU-scale screen), not a gross
  error. The checker's tolerance was widened after the Sonnet audit to `1e-9 R + C eps (|C| + |C|^2/R)` (log item 16),
  so it no longer alarms on this; the auditor recommends keeping the tight law and fixing the library. Decision: keep the
  widened tolerance (precision-level, physically small); recorded here. The law text now needs the `|C|^2/R` term.
- **MAP-003:** correct and not violated; NaN contamination reaches zero-weight cell corners, so the "finite samples used"
  precondition should count all cell corners. The checker only compares finite outputs, so it conforms.

## Law-text follow-ups (frozen commit unchanged)
FRM-001: Pre float64 input (checker already skips lower-precision input). FRM-002: read "line of sight" as the forward
ray. SCR-001: define `tol` and add the `|C|^2/R` term. MAP-001: add integer target dimensions to Pre (checker does not
exclude non-integer dimensions; the library accepts them and moves a corner by ~2 px, not exercised by agents or fuzz).
MAP-002: `dims`/`offset` are `int()`-truncated; add finite. MAP-003: as above.
