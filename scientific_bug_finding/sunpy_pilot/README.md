# SunPy scientific-sanitizer task

Fork `https://github.com/ChenziqiAdam/sunpy`, branch `scibench-scientific-checkers-pilot`
(frozen commit: see `sanitizers.json` `instrumented_commit`), built on upstream `sunpy/sunpy` main
`87d916c658045b3e5680aa58a130f9788ba618e4` (2026-10-06; Python >= 3.11).

**41 scientific sanitizers, 41 root-cause families.** Scientific bank only; no traditional reference bank yet
(SANITIZER.md 12 is a separate, independently designed step). New domain: solar physics (Sun-centred coordinate
frames, solar ephemeris and rotation, solar-disk geometry, map/FITS-WCS manipulation).

| Area | IDs | Subsystem |
|---|---|---|
| Solar ephemeris | EPH-001..010 | `coordinates/{sun,ephemeris}.py` (angular radius, Earth distance, B0, nutation, apparent position, light time, eclipse obscuration) |
| Carrington rotation | CAR-001..004 | `coordinates/sun.py` (rotation number/time, constants, disk-centre longitude L0) |
| Differential rotation model | DRM-001..006 | `sun/models.py` (symmetry, monotonicity, linearity, rate constants, synodic correction, model agreement) |
| Frames and geometry | FRM-001..006 | `coordinates/{frames,_transformations,utils}.py`, `map/maputils.py` (make_3d surface, on-disk predicate, observer invariance, heliocentric angle, limb, great arc) |
| Screens | SCR-001..002 | `coordinates/screens.py` (spherical screen, differential-rotation screen convergence) |
| Rotated coordinates | DRC-001..002 | `physics/differential_rotation.py` (reversibility, prograde rotation) |
| Maps | MAP-001..008 | `map/{mapbase,maputils}.py`, `image/resample.py` (footprint under resample/superpixel/rotate, submap grid, extrema, disk-coverage classes) |
| Kernels, WCS, headers | IMG-001, WCS-001..002 | `image/resample.py`, `coordinates/wcs_utils.py`, `map/header_helper.py` |

IDs are `SP-<AREA>-<NNN>`. Excluded (engineering gate, SANITIZER.md 5.6): network clients, file I/O, time series,
visualization, SPICE/Horizons wrappers, thin wrappers over astropy/scipy kernels. Astropy supplies the ephemeris, but
SunPy's own frame graph, rotation models, screens and map metadata handling are the subject here.

## Files

- `LAW_CANDIDATES.md`: laws written **before** any checker code or execution (Step 3), a foreknowledge disclosure and
  the revision log (checker-side defects and adjudicated natural triggers).
- `sanitizers.json` (built by `build_manifest.py` from the law document). Public copy in the fork:
  `SCIENTIFIC_CHECKERS.{json,md}` (`../sync_public_checker_materials.py`; `../validate_checker_banks.py --sunpy-repo`).
- Fork: `sunpy/_scientific_checkers.py` (opt-in logger + checkers) and `if _sc.enabled():` hooks in 13 production modules.
- `probe_reachability.py`, `test_scientific_checkers.py`, `fuzz_scientific_checkers.py`, `behaviour_parity.py`:
  curator-side reachability, isolated sensitivity, false-positive fuzzing and non-disruption tooling.
- `evaluate_submission.py` + `scibench_pytest_plugin.py`: deterministic scorer; `demo_submissions/`.

## Frozen task (Step 7)

- **Input to the agent:** the instrumented repo, `SCIENTIFIC_CHECKERS.{md,json}` and `SCIBENCH_TRIGGER_LOG=<file>`.
  Checkers are inert when it is unset.
- **Output:** a test-only patch. Approved locations: `sunpy/**/tests/test_*.py`, `sunpy/**/tests/data/**` and
  `sunpy/data/test/**`. Any other path, deletion/rename, and any added line mentioning `_scientific_checkers`,
  `SCIBENCH_`, `SCIENTIFIC_CHECKERS`, `trigger_if`, `checker_id`, `trigger_log` or `sanitizers.json`, or
  patching/assigning `sunpy` attributes, is rejected before running (9.1). Any run-time (re)assignment of a callable on
  a production `sunpy*` module, even one undone before the test ends, or replacement/mocking of a loaded production
  callable is flagged as `tampered_tests` and its triggers do not count.
- **Run:** fresh clone at the frozen commit (+ the install-generated `sunpy/_version.py`), patch applied, only the
  submitted test files, `-p no:randomly`, 120 s per test, 900 s total, fresh log.
- **Score:** primary = distinct families triggered by **passing, untampered** tests; secondary = IDs, tests
  executed/passed, wall time. The scientific bank is never summed with a traditional bank.
- **Environment:** CPython 3.13, numpy 2.5.3, scipy 1.18.1, astropy 8.0.1, scikit-image 0.26.0, reproject 0.21.0
  (`uv pip install -e ".[tests,map,physics,timeseries,image,coordinates]"`).

```text
python evaluate_submission.py --repo <fork checkout> --patch sub.diff --python <abs path to venv python> --out result.json
```

## Audit record (details in `sanitizers.json`)

- **Behaviour parity:** sha256 over 64 public-API outputs (ephemeris, frames, screens, rotation, maps, resampling) and the
  global NumPy RNG state is identical on the pristine base, instrumented/off and instrumented/on (`behaviour_parity.py`).
- **Upstream tests** (1,881 tests in `sunpy/{coordinates,map,physics,sun,image,time}`): the pristine tree has one baseline
  failure (`test_read_asdf_and_verify`, missing data file); the instrumented tree with checking off and on has the same
  single failure and no alarm.
- **Isolated sensitivity:** 41/41 IDs (32 tests). **Observation reachability:** 41/41.
- **Adversarial rounds:** 11 checker-side defects found and fixed (`LAW_CANDIDATES.md` revision log): an over-tight
  aberration+nutation bound (EPH-006), a map-property-cache side effect that swallowed an upstream warning (all map
  checkers now work on clones), re-parsing of `'now'` (EPH-004/007), tolerance scales for far screens and far observers
  (FRM-003), an HCI-frame reference whose own orientation noise (4e-7 rad) exceeded the tolerance (DRC-002), WCS-002
  step/coordinate rounding and projection terms, dtype awareness. The last two fuzz batches (16 seeds x 12 cases, stress 1
  and 3) are clean.
- **Natural trigger observed:** `SP-SCR-002`. With `propagate_with_solar_surface()` active, `SphericalScreen` iterates to
  find the screen distance; for an observer at 0.48 AU and a screen centre at 4.8 R_sun the iteration stops after 20 steps
  ("Failed to solve for the differentially rotated screen after 20 iterations. Using the best guess."), and the returned
  distances are off by 5e-4 to 1.2e-1 relative (reproducible in `demo_submissions/natural_trigger.diff`). Tracker not
  searched; nothing filed.
- **Not yet done:** independent audit of the laws flagged in the foreknowledge disclosure (MAP-001/002/003/004, SCR-001,
  FRM-001/002), upstream tracker search / issue drafts, optional traditional bank.

## Fresh-agent audit (Sonnet 5.5, 2026-10-07)

30 tests, 11 IDs triggered (`demo_submissions/fresh_sonnet55.*`). Adjudication: 5 checker defects fixed (DRC-001/002,
FRM-006, SCR-001, WCS-002; see `LAW_CANDIDATES.md` revision log items 12-18); 6 IDs real (FRM-001/002, MAP-001/002/004,
SCR-002). Score after repair: 6 IDs. Frozen commit is now `74b7f5fb8` (`sanitizers.json`).
