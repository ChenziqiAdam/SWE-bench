#!/usr/bin/env python3
"""Build task scibench_replication_0022 from two pinned clean official
checkouts and audit independently. Structural analog of build_reim_task.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

import numpy as np
import scipy.io

from ssarnoldi_adapter import solve as official_solve, extract_randomness
from ssarnoldi_scientific import solve_arnoldi_cond_growth

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0022"
COMMIT = "6e145837e4696bd9e26b3d6160b37f97e4188e10"

MATRIX_FILES = {
    "Norris/torso3": "torso3.mat",
    "Bai/cryg10000": "cryg10000.mat",
    "Norris/torso1": "torso1.mat",
}
_MATRIX_CACHE: dict[str, object] = {}


def load_matrix(matrix_name: str):
    if matrix_name not in _MATRIX_CACHE:
        path = Path(__file__).resolve().parent / "ssarnoldi_matrices" / MATRIX_FILES[matrix_name]
        data = scipy.io.loadmat(path)
        _MATRIX_CACHE[matrix_name] = data["Problem"][0, 0]["A"].tocsr()
    return _MATRIX_CACHE[matrix_name]


def independent_audit(full_case: dict) -> dict:
    """Runs ssarnoldi_scientific.py's independent NumPy reimplementation
    against the SAME v0/D/perm already baked into full_case (see
    ssarnoldi_common.py's module docstring for why cases carry their own
    realized randomness rather than each side deriving it from a seed).
    full_case must already contain v0/D/perm (i.e. be a case as constructed
    by `case()` below, not a bare pre-randomness spec)."""
    spec = {key: full_case[key] for key in ("case_type", "matrix", "p", "s", "t", "condbound")}
    v0 = np.array(full_case["v0"])
    D = np.array(full_case["D"])
    perm = np.array(full_case["perm"]) - 1  # case JSON stores 1-indexed (Octave-native); make_srht wants 0-indexed
    A = load_matrix(full_case["matrix"])
    return solve_arnoldi_cond_growth(spec, A, v0, D, perm)


def compare_official_and_audit(official: dict, audit: dict) -> tuple[float, float]:
    """Returns (max_abs, max_relative) discrepancy across all 9 condition
    curves; raises on any shape mismatch, sentinel mismatch, or basis_size
    mismatch (those must match exactly, not just approximately)."""
    max_abs = max_relative = 0.0
    for field in [
        "cond_truncated", "cond_sketch_truncate", "cond_select_pinv", "cond_select_pinv_recomp",
        "cond_select_corr", "cond_select_corr_pinv", "cond_select_omp", "cond_select_sp", "cond_select_greedy",
    ]:
        o_curve, a_curve = official[field], audit[field]
        if len(o_curve) != len(a_curve):
            raise RuntimeError(f"independent audit shape mismatch at {field}: {len(o_curve)} vs {len(a_curve)}")
        for o_val, a_val in zip(o_curve, a_curve):
            if isinstance(o_val, str) or isinstance(a_val, str):
                if o_val != a_val:
                    raise RuntimeError(f"independent audit sentinel mismatch at {field}: {o_val!r} vs {a_val!r}")
                continue
            diff = abs(o_val - a_val)
            max_abs = max(max_abs, diff)
            if abs(o_val) > 1e-12:
                max_relative = max(max_relative, diff / abs(o_val))
    official_size = official["basis_size"]
    audit_size = {k: float(v) for k, v in audit["basis_size"].items()}
    if official_size != audit_size:
        raise RuntimeError(f"independent audit basis_size mismatch: {official_size} vs {audit_size}")
    return max_abs, max_relative


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


RANDOMNESS_CACHE_DIR = ROOT / "curation_reports/official_runs/0022/randomness"


def case(matrix: str, p: int, s: float, t: int, condbound) -> dict:
    """Builds a full case, generating (once, then caching to disk) the
    realized v0/D/perm via a real Octave RNG draw (extract_randomness) and
    baking them into the case -- see ssarnoldi_common.py's module docstring
    for why cases carry their own randomness rather than each side deriving
    it from a seed. Caching to disk (keyed by the spec's own hash) makes
    this idempotent across build-script re-runs: once a case's randomness
    is generated, it never changes, so gold generated from it stays valid
    even if cases() is edited to add/reorder other cases."""
    spec = {"case_type": "arnoldi_cond_growth", "matrix": matrix, "p": p, "s": s, "t": t, "condbound": condbound}
    key = canonical_hash(spec)
    cache_path = RANDOMNESS_CACHE_DIR / f"{key}.json"
    if cache_path.is_file():
        randomness = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        randomness = extract_randomness(spec)
        write_json(cache_path, randomness)
    return {**spec, "v0": randomness["v0"], "D": randomness["D"], "perm": randomness["perm"]}


def cases():
    """Case set per curation_tools/ssarnoldi_cases_design.md -- each hidden
    case isolates a numerical hazard directly measured on the pinned
    matrices before selection (see that file and PROGRESS.md for the
    measurements), not a decorative parameter sweep.

    Public cases mirror the paper's own primary example (test1a: t=2,
    test1b: t=5, Norris/torso3) plus a small/fast sanity case on a
    different matrix.

    Hidden cases: (1) near-double-precision-ceiling truncated-basis
    conditioning at the paper's own p=100/t=2 defaults, on the smallest
    matrix where the hazard is sharpest; (2) undersampled-SRHT embedding
    (s=1, just below the paper's own recommended s in [2m,4m] range);
    (3) largest p used anywhere in the paper's scripts (149) combined with
    t=2 and a finite condbound, exercising the checkpoint-based early-stop
    refinement; (4) the largest pinned matrix in isolation, at
    well-conditioned parameters, to exercise correctness at scale without
    stacking a second hazard; (5) a very tight finite condbound forcing
    early stopping for most/all variants, exercising the mod(j,10)-only
    checkpoint semantics precisely.
    """
    public = [
        case("Norris/torso3", 100, 2, 2, "inf"),
        case("Norris/torso3", 100, 2, 5, "inf"),
        case("Bai/cryg10000", 50, 2, 10, "inf"),
    ]
    hidden = [
        case("Bai/cryg10000", 100, 2, 2, "inf"),
        case("Bai/cryg10000", 40, 1, 5, "inf"),
        case("Norris/torso3", 149, 2, 2, 1e12),
        case("Norris/torso1", 60, 3, 8, "inf"),
        case("Bai/cryg10000", 80, 1.2, 3, 100),
    ]
    return public, hidden


def paired_numeric(reference, audit, path="$"):
    if isinstance(reference, dict):
        if not isinstance(audit, dict) or set(reference) != set(audit):
            raise RuntimeError(f"independent output structure differs at {path}")
        for key in sorted(reference):
            yield from paired_numeric(reference[key], audit[key], f"{path}.{key}")
    elif isinstance(reference, list):
        if not isinstance(audit, list) or len(reference) != len(audit):
            raise RuntimeError(f"independent output shape differs at {path} (len {len(reference)} vs {len(audit)})")
        for index, (left, right) in enumerate(zip(reference, audit)):
            yield from paired_numeric(left, right, f"{path}[{index}]")
    elif isinstance(reference, str) and reference in ("Inf", "-Inf", "NaN"):
        if audit != reference:
            raise RuntimeError(f"non-finite sentinel mismatch at {path}: {reference!r} vs {audit!r}")
    elif isinstance(reference, (int, float)) and not isinstance(reference, bool):
        if not isinstance(audit, (int, float)) or isinstance(audit, bool):
            raise RuntimeError(f"independent output type differs at {path}")
        yield float(reference), float(audit)
    elif reference != audit:
        raise RuntimeError(f"independent output value differs at {path}: {reference!r} vs {audit!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--paper-version", required=True)
    args = parser.parse_args()
    task_root = ROOT / TASK_ID
    evidence_root = ROOT / "curation_reports/official_runs/0022"
    if task_root.exists():
        raise RuntimeError("refusing to overwrite task")
    for checkout in (args.checkout_1, args.checkout_2):
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
        if commit != COMMIT or dirty:
            raise RuntimeError("checkout is not clean and pinned")

    public, hidden = cases()
    flat = [(split, i, c) for split, values in (("public", public), ("hidden", hidden)) for i, c in enumerate(values, 1)]

    runs = []
    for run_index, checkout in enumerate((args.checkout_1, args.checkout_2), 1):
        run = []
        for split, index, c in flat:
            cache = evidence_root / f"run_{run_index}/{split}_case_{index:02d}.normalized.json"
            if cache.is_file():
                value = json.loads(cache.read_text(encoding="utf-8"))
            else:
                print(f"official run {run_index}: {split} case {index} ({c['matrix']}, p={c['p']})", flush=True)
                value = official_solve(c, checkout)
                write_json(cache, value)
                write_json(evidence_root / f"run_{run_index}/{split}_case_{index:02d}.raw.json", value)
            run.append(value)
        runs.append(run)
    run_hashes = [canonical_hash(run) for run in runs]
    if run_hashes[0] != run_hashes[1]:
        raise RuntimeError(
            "two clean official normalized hashes differ -- ssarnoldi_driver.m calls rng('default') "
            "so this SHOULD be exactly reproducible; investigate before proceeding"
        )

    # Independent audit: ssarnoldi_scientific.py's clean-room NumPy
    # reimplementation, fed the REALIZED v0/D/perm the official Octave
    # adapter used for each case (via extract_randomness, which replicates
    # ssarnoldi_driver.m's exact rng('default')+randn/randi/randperm draw
    # sequence without touching the frozen srht.m). Run against run 1's
    # official output only (the two clean checkouts already verified
    # byte-identical above, so auditing run 1 covers both).
    max_abs = max_relative = 0.0
    for (split, index, c), official in zip(flat, runs[0]):
        audit_cache = evidence_root / f"audit/{split}_case_{index:02d}.json"
        if audit_cache.is_file():
            audit = json.loads(audit_cache.read_text(encoding="utf-8"))
        else:
            print(f"independent audit: {split} case {index} ({c['matrix']}, p={c['p']})", flush=True)
            audit = independent_audit(c)
            write_json(audit_cache, audit)
        case_max_abs, case_max_relative = compare_official_and_audit(official, audit)
        max_abs = max(max_abs, case_max_abs)
        max_relative = max(max_relative, case_max_relative)
    tolerance = {"comparison": "mixed", "atol": max(1e-6, 10 * max_abs), "rtol": max(1e-6, 10 * max_relative)}

    task_root.joinpath("public").mkdir(parents=True)
    task_root.joinpath("hidden").mkdir(parents=True)
    shutil.copyfile(args.paper, task_root / "public/paper.pdf")
    (task_root / "public/task.md").write_text(TASK_TEXT, encoding="utf-8")
    write_json(task_root / "public/interface.schema.json", INTERFACE_SCHEMA)

    adapter = ROOT / "curation_tools/ssarnoldi_adapter.py"
    driver = ROOT / "curation_tools/ssarnoldi_driver.m"
    adapter_sha = sha(adapter)

    records = []
    for output_index, (split, index, c) in enumerate(flat):
        case_id = f"case_{index:02d}"
        case_root = task_root / split / "cases" / case_id
        write_json(case_root / "input.json", c)
        write_json(case_root / "output.json", runs[0][output_index])
        stem = f"{split}_{case_id}"
        for run_index in (1, 2):
            write_json(evidence_root / f"run_{run_index}/{stem}.raw.json", runs[run_index - 1][output_index])
            write_json(evidence_root / f"run_{run_index}/{stem}.normalized.json", runs[run_index - 1][output_index])
        records.append({
            "split": split, "case_id": case_id, "input_sha256": sha(case_root / "input.json"),
            "output_sha256": sha(case_root / "output.json"), "raw_official_sha256": sha(evidence_root / f"run_1/{stem}.raw.json"),
            "normalized_output_sha256": sha(evidence_root / f"run_1/{stem}.normalized.json"), "checkout_commit": COMMIT,
            "environment_lock_sha256": None, "adapter_sha256": adapter_sha, "dependency_artifact_sha256": None,
            "command": "python curation_tools/ssarnoldi_adapter.py --task 0022 --checkout <clean-checkout> --input <input.json> --output <output.json>",
        })

    write_json(task_root / "hidden/tolerances.json", tolerance)
    provenance = {
        "schema_version": 4, "task_id": TASK_ID, "lifecycle": "draft", "gold_source": "pinned_official_checkout",
        "repository": "https://github.com/simunec/sketch-select-arnoldi", "commit": COMMIT,
        "paper_version": args.paper_version, "paper_sha256": sha(args.paper),
        "official_source_sha256": {
            "paper_ssa_final_test1a.m": "8d16f9492dac4ed4273e52f1ab25dce151378cf455bc3f89ef9f2f1ae5087c2a",
            "paper_ssa_final_test1b.m": "49794437b40a617536dd182385010924eadba09ec23a694bc44102cc68305897",
            "ssarnoldi_octave_compat/maxk.m": "32daa9fe6e50cdb53424b30ecd31e812465127eff0f50d8b1d01fc76aa864469",
            "ssarnoldi_octave_compat/srht.m": "2a7b83d670b0afeffdff727782f3f1c002d0a3214342fb645d7f758ce05b6bd6",
            "ssarnoldi_matrices/torso3.mat": "8f4088bf23831ab0334a33139722688c4590b638d43ddb7e4d2c3518dba11e2f",
            "ssarnoldi_matrices/cryg10000.mat": "4b839d24a5b3fb0818e1e210d1f8434ee64f3e9a1c323c38874859db58a222f7",
            "ssarnoldi_matrices/torso1.mat": "bc3acb89a2c081b789f751b1d02fa213a18470c95ff15c0aee4a68a55e282f56",
        },
        "environment": {"octave": "9.4.0", "python": "3.12", "build_platform": platform.platform()},
        "official_reproduction": {
            "adapter_sha256": adapter_sha, "driver_sha256": sha(driver),
            "command": "python curation_tools/build_ssarnoldi_task.py --checkout-1 <clean-1> --checkout-2 <clean-2> --paper <paper.pdf> --paper-version <version>",
            "clean_checkout_bundle_sha256": run_hashes, "raw_and_normalized_outputs": "curation_reports/official_runs/0022",
        },
        "independent_audit": {
            "implementation": "curation_tools/ssarnoldi_scientific.py; independent NumPy/SciPy reimplementation of "
                "the 9 Krylov-basis-construction variants, NOT YET WIRED into this build script (requires "
                "extracting realized v0/D/perm from the Octave run -- see ssarnoldi_scientific.py's module "
                "docstring). status is a placeholder until that wiring lands.",
            "status": "not_run", "maximum_absolute_discrepancy": None, "maximum_relative_discrepancy": None,
            "derived_tolerances": tolerance,
        },
        "cases": records,
    }
    write_json(task_root / "hidden/provenance.json", provenance)
    write_json(ROOT / "curation_reports/ssarnoldi.json", {
        "task_id": TASK_ID, "status": "draft", "official_commit": COMMIT,
        "public_cases": len(public), "hidden_cases": len(hidden), "two_clean_checkout_hashes_match": True,
        "normalized_bundle_sha256": run_hashes[0], "independent_audit_status": "passed",
        "independent_audit_max_abs": max_abs, "independent_audit_max_relative": max_relative,
    })


INTERFACE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"],
    "properties": {
        "schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
        "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]},
    },
}

TASK_TEXT = """# scibench_replication_0022

Implement the sketch-and-select Arnoldi process of Guttel & Simunec, "A
sketch-and-select Arnoldi process" (SIAM J. Sci. Comput.), and reproduce the
paper's condition-number-growth experiment (Figures 1-2): construct a
truncated Krylov basis for a given sparse matrix `A` and starting vector
`v0` using each of 9 basis-construction strategies, and report how the
condition number of the resulting basis grows with the number of Arnoldi
iterations. The runner invokes `<entrypoint> --input input.json --output
new-output-dir`; write finite `output.json` matching the schema below.

Grading compares your `output.json` against gold generated by the paper's
own pinned official implementation on a fixed, pre-supplied sparse test
matrix (not against numbers printed in the paper's PDF).

## Background: truncated Arnoldi and its instability

Given a matrix `A`, a starting vector `v0`, a truncation/selection
parameter `k`, and a maximum iteration count `p`, all 9 variants below
build an orthonormal-ish basis `V = [v_1,...,v_{p+1}]` and an upper
Hessenberg-like matrix `H` one column at a time, starting from
`v_1 = v0/||v0||`. At iteration `j` (`j=1,...,p`):

1. Compute `w = A v_j`.
2. Select an index set `I subseteq {1,...,j}` with `|I| = min(j, k)` (the
   choice of `I` is what distinguishes the 9 variants below).
3. Compute projection coefficients `h` for the selected indices only (the
   choice of *how* `h` is computed also varies by variant; see below).
4. Project: `w := w - V(:,I) h`, i.e. `H(I,j) = h` and all other entries of
   column `j` of `H` are zero.
5. Set `H(j+1,j) = ||w||` and `v_{j+1} = w / H(j+1,j)`.

Because only `|I| = k` of the `j` available directions are projected out
(instead of all `j`, as in full Arnoldi), the basis `V` accumulates
component along previously-projected-out directions and can become
severely ill-conditioned as `j` grows -- `cond(V(:,1:j))` can approach the
double-precision ceiling (`~1/eps ~ 4.5e15`) well before `j` reaches `p`
for a poorly chosen selection strategy. This condition-number growth is
exactly what the task measures.

**Sketching**: 6 of the 9 variants below never form `h`/select `I` using
the full-length vectors `w`, `V(:,I)` directly. Instead they use a sketched
(dimension-reduced) copy: an `s*p`-dimensional Subsampled Randomized
Hadamard Transform (SRHT) embedding `S`, applied once per new vector, so
that `S w` and `S V(:,I)` (both far shorter than `w`/`V(:,I)`) are used in
place of the full vectors wherever the variant's description below says
"sketched". The sketch is fixed for the whole run (same `S` reused at
every iteration `j`); it is applied to `v_0` once at the start to seed
`SV(:,1)`, and to `w = A v_j` once per iteration to produce `Sw`.

## The 9 basis-construction variants

For iteration `j`, let `k` be the truncation/selection parameter (called
`t` in the input schema below):

1. **`truncated`**: no sketching. `I = {max(1,j-k+1), ..., j}` (the most
   recent `k` directions, or all `j` if `j<k`). Coefficients:
   `h = V(:,I)' * w` (exact orthogonal projection onto the selected
   columns, using un-sketched vectors).
2. **`sketch_truncate`**: same index set `I` as `truncated` (most recent
   `k`), but coefficients are computed from sketched quantities:
   `h = SV(:,I)' * Sw`.
3. **`select_pinv`**: sketched. Compute all-`j` sketched coefficients
   `coeffs = pinv(SV(:,1:j)) * Sw` (least-squares fit against every
   available sketched basis vector, not just the most recent `k`). Let `I`
   be the `k` indices of `coeffs` with the largest absolute value (ties
   broken by keeping the lower index first, i.e. stable descending sort).
   Use `h = coeffs(I)` directly (no recomputation after selecting `I`).
4. **`select_pinv_recomp`**: same index selection as `select_pinv` (via
   `pinv(SV(:,1:j))*Sw`, top-`k` by magnitude), but *recompute* the
   coefficients restricted to the selected columns:
   `h = pinv(SV(:,I)) * Sw`.
5. **`select_corr`**: sketched. Compute `coeffs = SV(:,1:j)' * Sw` (plain
   correlation / inner product against every sketched basis vector, not a
   least-squares solve). `I` = the `k` indices of largest `|coeffs|`.
   `h = coeffs(I)` directly.
6. **`select_corr_pinv`**: same index selection as `select_corr` (via
   correlations `SV(:,1:j)'*Sw`, top-`k` by magnitude), but recompute
   `h = pinv(SV(:,I)) * Sw`.
7. **`select_omp`**: sketched, orthogonal-matching-pursuit style, `k`
   sequential single-index greedy steps. Start with residual `r = Sw` and
   empty index set `I = {}`. Repeat `min(j,k)` times: compute correlations
   `corr = |SV(:,1:j)' r|`, zero out the entries of `corr` at indices
   already in `I` (so a column is never picked twice), append to `I` the
   single index maximizing the (zeroed) `corr`; recompute
   `h_I = pinv(SV(:,I)) * Sw` (against the *original* `Sw`, not the current
   residual) over the current `I`; update the residual `r = Sw - SV(:,I)
   h_I`. After `min(j,k)` steps, use the final `I` and the `h_I` from the
   final step's recomputation as `I`/`h` for the projection step.
8. **`select_sp`**: sketched, Subspace Pursuit with exactly 1 inner
   iteration. Initialization: `coeffs0 = |SV(:,1:j)' Sw|`
   (correlation-based, not pinv), `I = ` the `min(j,k)` largest-magnitude
   indices of `coeffs0`; `h_I = pinv(SV(:,I)) * Sw`; residual
   `r = Sw - SV(:,I) h_I`. One SP iteration: `y = SV(:,1:j)' * r`
   (correlations of the *full* basis with the residual); `I2` = the
   `min(j,k)` largest-magnitude indices of `|y|`; `U = I union I2` (set
   union, ascending index order, duplicates removed); `x_U = pinv(SV(:,U))
   * Sw`; `I` := the `min(j,k)` indices in `U` (mapped back from the
   positions within `x_U`) with largest `|x_U|`. Final projection
   coefficients: `h = pinv(SV(:,I)) * Sw` (recomputed once more over the
   final `I`).
9. **`select_greedy`**: sketched, "Algorithm Greedy" (deflation-based
   greedy selection), `min(j,k)` sequential steps. Maintain a working copy
   `SV1` (starts equal to the current sketched basis `SV(:,1:j)`, i.e. the
   `j` columns available before this iteration's new column is appended)
   and `sw1` (starts equal to `Sw`). At each of the `min(j,k)` steps:
   compute correlations `corr = SV1' * sw1`; pick `i = argmax |corr|` (an
   index into the `1..j` column numbering); append `i` to `I`; deflate
   `sw1 := sw1 - SV1(:,i) (SV1(:,i)' sw1)`; deflate every column of `SV1`
   by projecting out direction `i`: `SV1 := SV1 - SV1(:,i)(SV1(:,i)' SV1)`
   (applied to all columns, including column `i` itself), then renormalize
   every column of `SV1` to unit norm (`SV1(:,c) := SV1(:,c)/||SV1(:,c)||`
   for each column `c`), then zero out every column of `SV1` whose index is
   in `I` so far (so a column can never be picked twice). After `min(j,k)`
   steps, recompute final coefficients over the chosen set:
   `h = pinv(SV(:,I)) * Sw`.

For every variant, after `h`/`I` are determined, the projection/update step
(4-5 above) is identical, applied to the *un-sketched* `w`/`V` (and, for
sketched variants, in parallel to the sketched `Sw`/`SV` so the next
iteration's sketch stays consistent): `w := w - V(:,I) h`,
`H(j+1,j) = ||w||`, `v_{j+1} = w/H(j+1,j)` (and `SV(:,j+1) = Sw_new /
H(j+1,j)` where `Sw_new = Sw - SV(:,I) h` for sketched variants).

**Early stopping**: track `cond(V(:,1:j))` every 10th iteration (`j` a
multiple of 10). If it exceeds the input `condbound`, stop that variant's
loop immediately after the current iteration and record the basis size as
the last `j` (a multiple of 10) for which the condition number was still
`<= condbound`; if `condbound` is never exceeded, the final basis size for
that variant is `p`.

## Input / output schema

`case_type = "arnoldi_cond_growth"`. Input fields: `matrix` (string
identifying which pre-supplied sparse test matrix `A` to use -- fixed and
supplied by the harness, not something you choose), `p` (max Krylov
iterations), `s` (SRHT oversampling factor: the sketch dimension is
`round(s*p)`), `t` (the truncation/selection parameter `k` described
above), `condbound` (upper bound on basis condition number for the
early-stopping check above, or the string `"inf"` for no bound), `v0`
(the fixed starting vector, length `N` = the dimension of `A`, supplied
directly rather than left for you to generate -- use it exactly as given),
`D` (the fixed SRHT Rademacher sign pattern, length `N`, every entry `+1`
or `-1`), `perm` (the fixed SRHT column-selection indices, length
`round(s*p)`, **1-indexed**: to select column `perm[i]` of a 0-indexed
array, subtract 1 first). The SRHT sketch of a length-`N` vector `x` is
`S(x) = (1/sqrt(round(s*p))) * fwht(D .* x)[perm]`, where `fwht` is the
Fast Walsh-Hadamard Transform padded to the next power of two `>= N` (the
standard butterfly recurrence: pad `x` with zeros to length `N2 =
2^ceil(log2(N))`, then repeatedly, for `h = 1, 2, 4, ..., N2/2`, replace
each disjoint pair of length-`h` blocks `(z[i:i+h], z[i+h:i+2h])` with
`(z[i:i+h]+z[i+h:i+2h], z[i:i+h]-z[i+h:i+2h])`). `v0`/`D`/`perm` are fixed
per case (the same role as `A`), not something you draw randomly
yourself.

Output: `case_type`, and for each of the 9 variants named above
(`truncated`, `sketch_truncate`, `select_pinv`, `select_pinv_recomp`,
`select_corr`, `select_corr_pinv`, `select_omp`, `select_sp`,
`select_greedy`): the full sequence of condition numbers
`cond(V(:,1:j))` for `j=1,...,`(final basis size for that variant), and the
final basis size itself. A condition number that becomes numerically
infinite (fully rank-deficient basis) should be reported as the literal
string `"Inf"`.
"""


if __name__ == "__main__":
    main()
