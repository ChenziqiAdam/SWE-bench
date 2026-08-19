#!/usr/bin/env python3
"""Build task 0019 from two pinned clean official checkouts and audit independently."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

import numpy as np

from stiefelcurv_adapter import solve as official_solve
from stiefelcurv_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0019"
COMMIT = "1dad75cf55f0f688d59b61e0d9a58b61779efe9f"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def zeros(rows: int, cols: int) -> list[list[float]]:
    return [[0.0] * cols for _ in range(rows)]


def stiefel_case(metric: str, p: int, np_: int, A1, B1, A2, B2) -> dict:
    return {"metric": metric, "p": p, "np": np_, "A1": A1, "B1": B1, "A2": A2, "B2": B2}


def rank_increase_case(metric: str, n: int, u: float) -> dict:
    """Reproduces one point of the paper's Figure 1 rank-increase family
    (Section 4.1): fixed B1(1,2)=1, B2(1,1)=1, single free entry pair at
    magnitude u in the second row/column block."""
    B1 = zeros(n, n); B1[0][1] = 1.0; B1[1][0] = -u
    B2 = zeros(n, n); B2[0][0] = 1.0; B2[1][1] = u
    A = zeros(n, n)
    return stiefel_case(metric, n, n, A, B2, A, B1)


def ddvv_a_block_case(metric: str, which: str, u: float) -> dict:
    """Reproduces one point of the paper's Figure 4 A-block growth family
    (Section 4.3, DDVV matrices from Ge's inequality paper), p=n=4."""
    def a1(s): return [[0, s, 0, 0], [-s, 0, 0, 0], [0, 0, 0, s], [0, 0, -s, 0]]
    def a2(s): return [[0, 0, s, 0], [0, 0, 0, -s], [-s, 0, 0, 0], [0, s, 0, 0]]
    def a3(s): return [[0, 0, 0, s], [0, 0, s, 0], [0, -s, 0, 0], [-s, 0, 0, 0]]
    def b1(uu, vv): return [[0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, uu], [0, 0, -vv, 0]]
    def b2(uu, vv): return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, uu, 0], [0, 0, 0, vv]]
    scale_a = a1(1) if which == "A1A2" else a3(1)
    A1 = (np.asarray(scale_a) * u).tolist()
    A2 = (np.asarray(a2(1)) * u).tolist()
    B1 = (np.asarray(b1(0, 0)) * (1 - u)).tolist()
    B2 = (np.asarray(b2(0, 0)) * (1 - u)).tolist()
    return stiefel_case(metric, 4, 4, A1, B1, A2, B2)


def ddvv_b_block_case(metric: str, u: float, v: float) -> dict:
    """Reproduces one point of the paper's Figure 3 B-block rank-test surface
    (Section 4.3), p=n=4."""
    def b1(uu, vv): return [[0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, uu], [0, 0, -vv, 0]]
    def b2(uu, vv): return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, uu, 0], [0, 0, 0, vv]]
    A = zeros(4, 4)
    return stiefel_case(metric, 4, 4, A, b2(u, v), A, b1(u, v))


def grassmann_case(np_: int, p: int, B1, B2) -> dict:
    return {"metric": "grassmann", "p": p, "np": np_, "B1": B1, "B2": B2}


def so_n_case(n: int, X, Y) -> dict:
    return {"metric": "so_n", "n": n, "X": X, "Y": Y}


def near_degenerate_stiefel_euclidean_case() -> dict:
    """Y nearly parallel to X before Gram-Schmidt: the post-orthogonalization
    normY collapses to ~1e-6 (vs. O(1) for a generic pair). Every seccurv_*.m
    formula divides by this norm, so an implementation that reorders the
    normalize/project steps, or normalizes with the wrong (pre- vs.
    post-projection) vector, is amplified by ~1e6 here while still matching
    to machine precision on well-separated public cases. X, Y remain linearly
    independent (normY > 0), so the input is valid per the paper's own
    assumption, not a boundary violation."""
    p, np_ = 3, 3
    A1 = [[0, 1, 0], [-1, 0, 0], [0, 0, 0]]
    B1 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    c, eps = 5.0, 1e-6
    A2 = (np.asarray(A1) * c).tolist()
    B2 = (np.asarray(B1) * c).tolist()
    B2[0][1] += eps
    return stiefel_case("stiefel_euclidean", p, np_, A1, B1, A2, B2)


def rank_deficient_near_parallel_grassmann_case() -> dict:
    """B1, B2 are both rank-deficient (each column concentrated in a distinct
    2-dim subspace of a 5-dim ambient space) and near-parallel before
    projection: post-projection normY collapses to ~9e-8. Isolates
    seccurv_Grassmann.m under the same near-degenerate-orthogonalization
    hazard as the Stiefel case above, combined with low-rank B-blocks
    (the paper's own 'low rank' theme) rather than full-rank generic
    matrices."""
    np_, p = 5, 3
    B1 = [[1, 0, 0], [2, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 1]]
    c, eps = 3.0, 1e-7
    B2 = (np.asarray(B1, dtype=float) * c).tolist()
    B2[0][0] += eps
    return grassmann_case(np_, p, B1, B2)


def high_dimensional_so_n_case() -> dict:
    """Generic but high-dimensional (n=30) skew pair, isolating seccurv_SOn.m
    at a scale far beyond the paper's own p=4 examples: exercises whether an
    implementation's trace/Lie-bracket computation accumulates floating-point
    error differently at scale (900-entry matrices) rather than only matching
    at the small hand-checkable sizes used elsewhere in this task."""
    n = 30
    rng1 = np.random.RandomState(1)
    rng2 = np.random.RandomState(2)
    raw1 = rng1.normal(size=(n, n))
    raw2 = rng2.normal(size=(n, n))
    X = (raw1 - raw1.T).tolist()
    Y = (raw2 - raw2.T).tolist()
    return so_n_case(n, X, Y)


def cases():
    public = [
        rank_increase_case("stiefel_canonical", 10, 0.3),
        ddvv_a_block_case("stiefel_canonical", "A1A2", 0.5),
        ddvv_b_block_case("stiefel_euclidean", 0.4, 0.7),
    ]
    hidden = [
        # Near-degenerate Gram-Schmidt orthogonalization (Y nearly parallel
        # to X): the numerical hazard every seccurv_*.m formula shares.
        near_degenerate_stiefel_euclidean_case(),
        # Late-stage high-rank regime (large u, deep into the 9-stage family).
        rank_increase_case("stiefel_canonical", 10, 0.95),
        # DDVV A3-vs-A2 pairing at the midpoint, exercising the alternate matrix.
        ddvv_a_block_case("stiefel_euclidean", "A3A2", 0.6),
        # Grassmann metric on rank-deficient, near-parallel B-blocks: the same
        # near-degenerate-orthogonalization hazard combined with low rank.
        rank_deficient_near_parallel_grassmann_case(),
        # SO(n) metric at n=30 (vs. the paper's own p=4 examples): floating-
        # point accumulation at scale, independent of the Stiefel/Grassmann
        # block forms.
        high_dimensional_so_n_case(),
    ]
    return public, hidden


def paired_numeric(reference, audit, path="$"):
    """Yield numeric leaves paired by semantic JSON path, validating structure."""
    if isinstance(reference, dict):
        if not isinstance(audit, dict) or set(reference) != set(audit):
            raise RuntimeError(f"independent output structure differs at {path}")
        for key in sorted(reference):
            yield from paired_numeric(reference[key], audit[key], f"{path}.{key}")
    elif isinstance(reference, list):
        if not isinstance(audit, list) or len(reference) != len(audit):
            raise RuntimeError(f"independent output shape differs at {path}")
        for index, (left, right) in enumerate(zip(reference, audit)):
            yield from paired_numeric(left, right, f"{path}[{index}]")
    elif isinstance(reference, (int, float)) and not isinstance(reference, bool):
        if not isinstance(audit, (int, float)) or isinstance(audit, bool):
            raise RuntimeError(f"independent output type differs at {path}")
        yield float(reference), float(audit)
    elif reference != audit:
        raise RuntimeError(f"independent output value differs at {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--paper-version", required=True)
    args = parser.parse_args()
    task_root = ROOT / TASK_ID
    evidence_root = ROOT / "curation_reports/official_runs/0019"
    if task_root.exists():
        raise RuntimeError("refusing to overwrite task")
    for checkout in (args.checkout_1, args.checkout_2):
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
        if commit != COMMIT or dirty:
            raise RuntimeError("checkout is not clean and pinned")
    public, hidden = cases()
    flat = [(split, i, case) for split, values in (("public", public), ("hidden", hidden)) for i, case in enumerate(values, 1)]
    runs = []
    for run_index, checkout in enumerate((args.checkout_1, args.checkout_2), 1):
        run = []
        for split, index, case in flat:
            cache = evidence_root / f"run_{run_index}/{split}_case_{index:02d}.normalized.json"
            if cache.is_file():
                value = json.loads(cache.read_text(encoding="utf-8"))
            else:
                print(f"official run {run_index}: {split} case {index}", flush=True)
                value = official_solve(case, checkout)
                write_json(cache, value)
                write_json(evidence_root / f"run_{run_index}/{split}_case_{index:02d}.raw.json", value)
            run.append(value)
        runs.append(run)
    run_hashes = [canonical_hash(run) for run in runs]
    if run_hashes[0] != run_hashes[1]:
        raise RuntimeError("two clean official normalized hashes differ")
    independent = []
    for split, index, case in flat:
        cache = evidence_root / f"independent/{split}_case_{index:02d}.json"
        if cache.is_file():
            value = json.loads(cache.read_text(encoding="utf-8"))
        else:
            print(f"independent: {split} case {index}", flush=True)
            value = independent_solve(case)
            write_json(cache, value)
        independent.append(value)
    max_abs = max_relative = 0.0
    for official, audit in zip(runs[0], independent):
        pairs = list(paired_numeric(official, audit))
        x = np.asarray([left for left, _ in pairs])
        y = np.asarray([right for _, right in pairs])
        delta = np.abs(x - y)
        max_abs = max(max_abs, float(delta.max(initial=0)))
        max_relative = max(max_relative, float((delta / np.maximum(np.abs(x), 1e-8)).max(initial=0)))
    if max_abs > 1e-8 or max_relative > 1e-5:
        raise RuntimeError(
            f"independent audit discrepancy exceeds fail-closed limits: "
            f"max_abs={max_abs}, max_relative={max_relative}"
        )
    tolerance = {"comparison": "mixed", "atol": max(1e-10, 10 * max_abs), "rtol": max(1e-8, 10 * max_relative)}
    task_root.joinpath("public").mkdir(parents=True)
    task_root.joinpath("hidden").mkdir(parents=True)
    shutil.copyfile(args.paper, task_root / "public/paper.pdf")
    (task_root / "public/task.md").write_text(TASK_TEXT, encoding="utf-8")
    write_json(task_root / "public/interface.schema.json", INTERFACE_SCHEMA)
    adapter = ROOT / "curation_tools/stiefelcurv_adapter.py"
    lock = ROOT / "curation_tools/environments/0019-octave-environment.yml"
    records = []
    for output_index, (split, index, case) in enumerate(flat):
        case_id = f"case_{index:02d}"
        case_root = task_root / split / "cases" / case_id
        write_json(case_root / "input.json", case)
        write_json(case_root / "output.json", runs[0][output_index])
        stem = f"{split}_{case_id}"
        for run_index in (1, 2):
            write_json(evidence_root / f"run_{run_index}/{stem}.raw.json", runs[run_index - 1][output_index])
            write_json(evidence_root / f"run_{run_index}/{stem}.normalized.json", runs[run_index - 1][output_index])
        records.append({"split": split, "case_id": case_id, "input_sha256": sha(case_root / "input.json"),
            "output_sha256": sha(case_root / "output.json"), "raw_official_sha256": sha(evidence_root / f"run_1/{stem}.raw.json"),
            "normalized_output_sha256": sha(evidence_root / f"run_1/{stem}.normalized.json"), "checkout_commit": COMMIT,
            "environment_lock_sha256": sha(lock), "adapter_sha256": sha(adapter), "dependency_artifact_sha256": None,
            "command": "<pinned-environment>/bin/python curation_tools/stiefelcurv_adapter.py --task 0019 --checkout <clean-checkout> --input <input.json> --output <output.json>"})
    write_json(task_root / "hidden/tolerances.json", tolerance)
    provenance = {"schema_version": 4, "task_id": TASK_ID, "lifecycle": "validated", "gold_source": "pinned_official_checkout",
        "repository": "https://github.com/RalfZimmermannSDU/StiefelCurvatureSIMAX", "commit": COMMIT,
        "paper_version": args.paper_version, "paper_sha256": sha(args.paper),
        "official_source_sha256": {
            "seccurv_Stiefel_canon.m": "bcf921bec55711ae21890e54e57efcaabceeeb708990c1a561d64d621cd30693",
            "seccurv_Stiefel_euclid.m": "6b00f2426f6762e570ed5b312ce79061b0f8fe40e8b598acdc467f5c2087db0c",
            "seccurv_Grassmann.m": "cc28a7de1cf68e718e3a9138ac99c1f3b4acdfc57062bf19dd186ae3256c278c",
            "seccurv_SOn.m": "8a9997320bde51645a7247c304bda4df3262037f9cce9735c879046303fe35cb",
        },
        "parameter_patch": "None: the four pinned seccurv_*.m functions are called verbatim with curator-constructed "
            "input matrices matching the paper's own Figure 1/3/4 configurations plus independently designed "
            "hidden regimes; the stochastic Figure 2 experiment (script_curvature_SIMAX_exp42.m, unseeded rand(), "
            "no rng() call anywhere in the repository) is out of scope because it is not bit-reproducible without "
            "modifying official code.",
        "environment": {"octave": "9.4.0", "python": "3.12", "build_platform": platform.platform()},
        "environment_lock_sha256": sha(lock), "dependency_artifact_sha256": None,
        "official_reproduction": {"adapter_sha256": sha(adapter), "environment_lock_sha256": sha(lock), "dependency_artifact_sha256": None,
            "command": "python curation_tools/build_stiefelcurv_task.py --checkout-1 <clean-1> --checkout-2 <clean-2> --paper <paper.pdf> --paper-version <version>",
            "clean_checkout_bundle_sha256": run_hashes, "raw_and_normalized_outputs": "curation_reports/official_runs/0019"},
        "independent_audit": {"implementation": "curation_tools/stiefelcurv_scientific.py; independent NumPy reimplementation "
            "of the four sectional-curvature formulas (Stiefel canonical, Stiefel Euclidean, Grassmann, SO(n)) from the "
            "paper's Section 3 equations",
            "status": "passed", "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_relative, "derived_tolerances": tolerance},
        "cases": records}
    write_json(task_root / "hidden/provenance.json", provenance)
    write_json(ROOT / "curation_reports/stiefel_curvature.json", {"task_id": TASK_ID, "status": "validated", "official_commit": COMMIT,
        "public_cases": 3, "hidden_cases": 5, "two_clean_checkout_hashes_match": True, "normalized_bundle_sha256": run_hashes[0],
        "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_relative, "tolerances": tolerance,
        "scope_exclusion": "script_curvature_SIMAX_exp42.m (Figure 2) excluded: unseeded rand(), no rng() call in the "
            "repository, not bit-reproducible without modifying official code; also the runtime long pole at paper "
            "settings (runs=100, max_dim=1000, matrices up to 2000x2000)."})


INTERFACE_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"], "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
    "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}}}

TASK_TEXT = """# scibench_replication_0019

Implement sectional curvature of Grassmann, Stiefel, and SO(n) manifolds under the paper's four metrics. The runner invokes `<entrypoint> --input input.json --output new-output-dir`; write finite `output.json` with fields `metric` (echoed) and `seccurv` (float).

Each input case gives `metric` plus the tangent-vector coordinate matrices for that metric (all as nested row-major float lists), and the caller must compute a single sectional curvature value `K` for the plane they span.

`stiefel_canonical` and `stiefel_euclidean` inputs give integer block sizes `p`, `np` (= n-p) and four `p x p` / `np x p` matrices `A1, B1, A2, B2`: `A1, A2` are `p x p` skew-symmetric, `B1, B2` are `np x p`. These represent tangent vectors `X = [[A1,-B1'],[B1,0]]`, `Y = [[A2,-B2'],[B2,0]]` at the identity of the Stiefel manifold St(n,p), n = p+np.

For `stiefel_canonical` (canonical metric), first orthonormalize: `normX = sqrt(0.5*trace(A1'A1) + trace(B1'B1))`, divide `A1,B1` by `normX`; then `d = 0.5*trace(A1'A2) + trace(B1'B2)`, subtract `d*(A1,B1)` from `(A2,B2)`, and normalize the result by `normY = sqrt(0.5*trace(A2'A2) + trace(B2'B2))`. With Lie brackets `[A1,A2] = A1A2-A2A1`, `L1 = B1'B2-B2'B1`, `L2 = B2B1'-B1B2'`, curvature is `K = (1/8)||[A1,A2]-L1||_F^2 + (1/4)||B1A2-B2A1||_F^2 + (1/2)||L2||_F^2`.

For `stiefel_euclidean` (Euclidean metric), orthonormalize using unweighted norms `normX = sqrt(trace(A1'A1)+trace(B1'B1))` and `d = trace(A1'A2)+trace(B1'B2)` (no 0.5 factors), then `K = (1/4)||[A1,A2]+L1||_F^2 + ||B1A2-B2A1||_F^2 + trace(B1(B2'B2)B1') - trace((B1'B2)(B2'B1))`.

`grassmann` inputs give `B1, B2` (both `np x p`) representing `X=[0;B1], Y=[0;B2]` in the tangent space of Gr(n,p). Normalize `B1` by its Frobenius norm; subtract `trace(B2'B1)*B1` from `B2` and normalize the result by its Frobenius norm. With `M = B1'B2`, `K = trace(MM') + trace((B1'B1)(B2'B2)) - 2*trace(MM)`.

`so_n` inputs give an integer `n` and two `n x n` skew-symmetric matrices `X, Y` representing tangent vectors at the identity of SO(n). Normalize `X` by its Frobenius norm; subtract `trace(X'Y)*X` from `Y` and normalize by its Frobenius norm. `K = 0.5*trace([X,Y]'[X,Y])` where `[X,Y] = XY-YX`.
"""


if __name__ == "__main__":
    main()
