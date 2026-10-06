# DeepChem scientific-sanitizer task

Fork `https://github.com/ChenziqiAdam/deepchem`, branch
`scibench-scientific-checkers-pilot` (pushed 2026-10-06, head `73c13e799`),
built on upstream master `455d07f3e17e880a4d980b5b0365e4a02b417e14`
(2.8.1.dev, 2026-08-21). The fork's `master` equals that commit.

**38 scientific sanitizers, 34 root-cause families.** Scientific bank only; no
traditional reference bank yet (SANITIZER.md 12 is a separate, independently
designed step). Domain: chemistry/physics ML infrastructure, which complements
the existing banks (biology, astronomy, seismology, materials, quantum
dynamics, quantum chemistry).

| Area | IDs | Subsystem |
|---|---|---|
| SO(3) representation theory | EQ-001..005, 007, 008, 010..012 | `utils/equivariance_utils.py` |
| VMC electron sampler | ES-001..004 | `utils/electron_sampler.py` |
| Rigid-body geometry | GU-001..005 | `utils/geometry_utils.py` |
| Coordinate boxes | BX-001, 003 | `utils/coordinate_box_utils.py` |
| Non-covalent interactions | NC-001..005 | `utils/noncovalent_utils.py`, `rdkit_utils.py` |
| Molecular fragments | FR-001..003 | `utils/fragment_utils.py` |
| Coulomb-matrix descriptors | CM-001..004 | `feat/molecule_featurizers/coulomb_matrices.py` |
| Element constants | PT-001..003 | `utils/periodic_table_utils.py` |
| Chemical splitters | SP-001, 002 | `splits/splitters.py` |

IDs are `DC-<AREA>-<NNN>`. Excluded by the engineering gate: the libcint-backed
DFT stack (`dqclibs` has no wheel for CPython 3.12), DGL graph networks and
matminer wrappers.

## Files

- `LAW_CANDIDATES.md`: laws written **before** any checker code or execution
  (Step 3), with the Step 5/6 disposition and a foreknowledge disclosure.
- `sanitizers.json`: curator manifest (schema as the other pilots) plus the
  audit record. Public copy in the fork: `SCIENTIFIC_CHECKERS.{json,md}`
  (`sync_public_checker_materials.py`; `validate_checker_banks.py --deepchem-repo`).
- Fork: `deepchem/_scientific_checkers.py` (opt-in logger + checkers) and
  `if _scientific_checkers.enabled():` hooks at the observation points.
- `probe_reachability.py`, `test_scientific_checkers.py`,
  `fuzz_scientific_checkers.py`: curator-side reachability, isolated
  sensitivity and checker-false-positive tooling.
- `evaluate_submission.py` + `scibench_pytest_plugin.py`: deterministic scorer.
  `demo_submissions/`: one legitimate and two rejected demo patches with results.

## Frozen task (Step 7)

- **Input to the agent:** the instrumented repo, `SCIENTIFIC_CHECKERS.{md,json}`,
  and `SCIBENCH_TRIGGER_LOG=<file>`. Checkers are inert when it is unset.
- **Output:** a test-only patch.
- **Approved locations:** `deepchem/**/tests?/**/test_*.py` and
  `deepchem/**/tests?/{assets,data}/**`. Any other path, any deletion/rename,
  and any added line mentioning `_scientific_checkers`, `SCIBENCH_`,
  `SCIENTIFIC_CHECKERS`, `trigger_if`, `checker_id`, `trigger_log` or
  `sanitizers.json` is rejected before running (SANITIZER.md 9.1).
- **Run:** fresh clone at the frozen commit, patch applied, only the submitted
  test files, `pytest-timeout` 120 s per test, 900 s total, fresh log.
- **Score:** primary = distinct families triggered by **passing** tests;
  secondary = distinct IDs, tests executed/passed, wall time. Triggers from
  failing tests are reported separately and not counted. The scientific bank
  is never summed with a traditional bank.
- **Environment:** Python 3.12.7, numpy 2.5.3, scipy 1.18.1, torch 2.11.0,
  torchvision 0.26.0, rdkit 2026.03.6, pandas 3.0.6, scikit-learn 1.9.1,
  pytest 9.1.1 (+ pytest-timeout, flaky, pdbfixer/openmm). Not available:
  `dqclibs`, a working `dgl`, vina, matminer, mordred, transformers. The
  equivariance unit tests cannot run (their `setUp` builds a DGL graph) but the
  functions can; `get_basis` accepts any object with `edata['edge_attr']`.

```text
python evaluate_submission.py --repo <fork checkout> --patch sub.diff \
    --python <venv python> --out result.json
```

## Audit record (details in `sanitizers.json`)

- Disabled and enabled runs return byte-identical results to the pristine base
  on ~90 deterministic public-API outputs (sha256 equal in all three modes).
- Upstream tests of the 15 instrumented-module targets: 147 pass / 42 fail with
  checking off, the same 42 with it on (missing optional dependencies).
- Isolated sensitivity 38/38 IDs; observation reachability 38/38 IDs.
- Six adversarial fuzz rounds + a static T/X/P/N derivation: 6 checker-side
  defects found and fixed (tolerance, transform, precondition classes); the last
  four rounds (seeds 3-6) were clean.
- **Observed triggered (3 IDs, 3 mechanisms, root causes confirmed by patching
  the suspect lines in-process):** `DC-NC-003` (`is_hydrogen_bond`: stale loop
  index, early return, misplaced angle-cutoff argument); `DC-ES-004`
  (`log_prob_gaussian` normalisation depends on sigma's shape); `DC-EQ-005`
  (float32 overflow of the associated-Legendre prefactor for degree >= 29).
  All 35 other IDs observed untriggered under the stated search.
- Upstream tracker searched 2026-10-06 (no duplicates). Issues drafted for
  `DC-NC-003` and `DC-ES-004` in `issues/`; nothing filed.
- Fresh-context audit 2 (Opus 5.5, `fresh_opus55/`): 17/17 tests passed, 5 IDs
  (EQ-005, ES-004, NC-003, NC-004 again, plus `DC-EQ-008`). No checker defect.
  `DC-EQ-008`: float64 exp/log round-trip error ~1.7e-11 just below the
  documented 0.07 Taylor threshold (`sinc_inv`); a deliberate approximation,
  not drafted. Union over both agents: 6 IDs; 32 IDs never triggered.
- Fresh-context audit 1 (Sonnet 5.5, `fresh_sonnet55/`): 5 IDs triggered, 30/30
  tests passed; one checker defect (`DC-EQ-011` precondition) found and fixed.
  `DC-NC-004` is sound but weak in the library (contrived), not drafted.

## Known limits

- Two fresh-context audits (Sonnet 5.5, Opus 5.5). The curator read the code before writing
  the laws, and two spots (NC-002/003, ES-004) were noticed during that read;
  both are flagged in `LAW_CANDIDATES.md` for an independent curator. Neither
  agent triggered `DC-EQ-012`, `DC-SP-001/002`; reach of
  `DC-NC-001/002/005`, `DC-FR-*`, `DC-CM-*` is unconfirmed.
- `DC-EQ-012` uses a fixed 1e-6 slack tied to the library's own kernel
  tolerance (1e-10 singular values); it is not derived per call.
- `DC-EQ-006` (rotation equivariance of harmonics) and solver-residual laws for
  `differentiation_utils` were left out (frame convention / user-set
  tolerances); recorded in `LAW_CANDIDATES.md`.
- The `get_basis` check caches results per basis, so repeated calls do not
  re-check.
