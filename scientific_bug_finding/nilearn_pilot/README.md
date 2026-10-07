# Nilearn scientific-sanitizer task

Fork `https://github.com/ChenziqiAdam/nilearn`, branch `scibench-scientific-checkers-pilot`
(pushed; frozen commit `0b2557ea4`), built on upstream `nilearn/nilearn` main
`d6c09c9a4a30ec5f6d7b5211268e0163825a9f2e` (2026-10-02; Python >= 3.11).

**42 scientific sanitizers, 41 root-cause families.** Scientific bank only; no traditional
reference bank yet (SANITIZER.md 12 is a separate, independently designed step). New domain:
neuroimaging (fMRI) statistics.

| Area | IDs | Subsystem |
|---|---|---|
| Signal cleaning | SIG-001..008 | `signal.py` (detrend, z-score/psc, Butterworth, confound regression, cosine drift, CompCor) |
| General linear model | GLM-001..008 | `glm/{regression,contrasts,_utils}.py` (OLS, R^2, z-scores, t/F contrasts, fixed effects) |
| Hemodynamic regressors | HRF-001..004 | `glm/first_level/hemodynamic_models.py` |
| Multiple-comparison control | THR-001..003 | `glm/thresholding.py`, `image/image.py` (BH-FDR, ordering, cluster extent) |
| Functional connectivity | CON-001..009 | `connectome/` (correlation, partial correlation, tangent space, Frechet mean, group-sparse precision) |
| Permutation inference | MU-001..005 | `mass_univariate/` (t vs GLM, TFCE, p-values, cluster measures) |
| Images | IMG-001..005 | `image/{image,resampling}.py`, `regions/signal_extraction.py` |

IDs are `NL-<AREA>-<NNN>`. Excluded (engineering gate, SANITIZER.md 5.6): I/O, BIDS/fMRIPrep, datasets,
plotting/reporting, surfaces, thin wrappers over scikit-learn/SciPy (decoding, SpaceNet, ReNA, CanICA).

## Files

- `LAW_CANDIDATES.md`: laws written **before** any checker code or execution (Step 3), a foreknowledge
  disclosure, and the revision log (checker-side defects and adjudicated natural triggers).
- `sanitizers.json` (built by `build_manifest.py` from the law document). Public copy in the fork:
  `SCIENTIFIC_CHECKERS.{json,md}` (`../sync_public_checker_materials.py`; `../validate_checker_banks.py --nilearn-repo`).
- Fork: `nilearn/_scientific_checkers.py` (opt-in logger + checkers) and `if _sc.enabled():` hooks in 13
  production modules.
- `probe_reachability.py`, `test_scientific_checkers.py`, `fuzz_scientific_checkers.py`, `behaviour_parity.py`:
  curator-side reachability, isolated sensitivity, false-positive fuzzing and non-disruption tooling.
- `evaluate_submission.py` + `scibench_pytest_plugin.py`: deterministic scorer; `demo_submissions/`.

## Frozen task (Step 7)

- **Input to the agent:** the instrumented repo, `SCIENTIFIC_CHECKERS.{md,json}` and `SCIBENCH_TRIGGER_LOG=<file>`.
  Checkers are inert when it is unset.
- **Output:** a test-only patch. Approved locations: `nilearn/**/tests/test_*.py` and `nilearn/**/tests/data/**`.
  Any other path, deletion/rename, and any added line mentioning `_scientific_checkers`, `SCIBENCH_`,
  `SCIENTIFIC_CHECKERS`, `trigger_if`, `checker_id`, `trigger_log` or `sanitizers.json`, or patching/assigning
  `nilearn` attributes, is rejected before running (9.1). Run-time replacement or mocking of a loaded
  production `nilearn*` callable is flagged as `tampered_tests` and its triggers do not count.
- **Run:** fresh clone at the frozen commit (+ the install-generated `nilearn/_version.py`), patch applied, only
  the submitted test files, `-p no:randomly`, 120 s per test, 900 s total, fresh log.
- **Score:** primary = distinct families triggered by **passing, untampered** tests; secondary = IDs, tests
  executed/passed, wall time. The scientific bank is never summed with a traditional bank.
- **Environment:** CPython 3.13.11, numpy 2.5.3, scipy 1.18.1, pandas 3.0.6, scikit-learn 1.9.1, nibabel 5.4.2
  (`uv pip install -e . --group test`).

```text
python evaluate_submission.py --repo <fork checkout> --patch sub.diff --python <abs path to venv python> --out result.json
```

## Audit record (details in `sanitizers.json`)

- **Behaviour parity:** sha256 over 65 public-API outputs and the global NumPy RNG state identical on the pristine
  base, instrumented/off and instrumented/on.
- **Upstream tests** (1,708 tests in the instrumented modules): same 20 baseline failures (report rendering) on the
  pristine and the instrumented tree; no new failure with checking on.
- **Isolated sensitivity:** 42/42 IDs (33 tests). **Observation reachability:** 42/42.
- **Adversarial rounds:** 10 checker-side defects found and fixed (all tolerance-conditioning, precondition or unit
  classes, see `LAW_CANDIDATES.md`); the last three batches (19,200 cases) are clean.
- **Natural trigger observed:** `NL-SIG-002`. `standardize_signal` treats `std < finfo(float64).eps` as constant, so a
  non-constant column of amplitude below ~2e-16 (for example femtotesla-scale data in SI units) is not scaled to unit
  variance, contrary to the documented "scaled to unit variance". Reached by upstream tests through internal
  rounding-noise columns. Root cause is the absolute guard at `signal.py` (`std[std < eps] = 1.0`); tracker not
  searched; nothing filed.
- **Fresh agent, Sonnet 5.5** (`fresh_sonnet55/`, 41/41 tests passed): 28 IDs scored on the first commit; replay and
  exact (mpmath) references showed 23 were checker defects (float32 with float64 eps, float64 underflow/overflow of the
  checker's own products, four preconditions: Butterworth band width, truncated HRF kernel, unconverged Frechet mean,
  integer resampling output). After repair the same patch scores 5 IDs / 5 families: SIG-001/003/008 (float32
  accumulation on long or offset series), SIG-002 (std < eps guard) and THR-003 (a single cluster that fills the volume
  is never size-tested). Re-verification: sensitivity 33/33, reachability 42/42, parity identical, upstream suite same
  20 baseline failures, fuzz 0 alarms (seeds 50-57) and only SIG-002 at extreme scale under 30-decade stress.
- **Not yet done:** Opus fresh run, independent audit of the laws flagged in the foreknowledge
  disclosure (GLM-003/006/008, SIG-003/007, THR-001, CON-008), upstream tracker search, optional traditional bank,
  tracker search for THR-003.
