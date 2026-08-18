#!/usr/bin/env python3
"""Build task 0015 from two pinned clean official checkouts and audit independently."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

import numpy as np

from fixed_sparsity_adapter import solve as official_solve
from fixed_sparsity_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0015"
COMMIT = "6da600d95dbcf8a2f6f8424432601e31a243ba5e"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def curve(label, n, matrix, pattern, parameters, counts, trials):
    return {"label": label, "n": n, "matrix": matrix, "pattern": pattern,
            "pattern_parameters": parameters, "matvec_counts": counts, "trials": trials}


def cases():
    public = [
        {"mode": "curves", "seed": 1500, "experiments": [curve("figure_2_tridiagonal_inverse", 1000, "tridiagonal_inverse", "banded", [0, 1, 2, 3, 4, 5], np.geomspace(1, 1001, 20, dtype=int).tolist(), 20)]},
        {"mode": "curves", "seed": 1501, "experiments": [curve("figure_4_trefethen_primes", 1000, "trefethen_inverse", "power_bands", [0, 1, 2, 5, 10], np.geomspace(10, 501, 20, dtype=int).tolist(), 100)]},
        {"mode": "hard_coloring", "seed": 1502, "experiments": [{"label": "paper_hard_coloring", "k": 6}]},
    ]
    hidden = [
        {"mode": "curves", "seed": 1511, "experiments": [
            curve("reduced_tridiagonal", 96, "tridiagonal_inverse", "banded", [0, 3], [12, 24, 48], 12),
            curve("reduced_trefethen", 96, "trefethen_inverse", "power_bands", [0, 2], [30, 60, 100], 12)]},
        {"mode": "curves", "seed": 1512, "experiments": [curve("irregular_sparsity", 48, "random_dense", "irregular", [7], [12, 24, 40], 16)]},
        {"mode": "curves", "seed": 1513, "experiments": [curve("exact_sparse_recovery", 60, "random_sparse", "matrix_support", [6], [10, 18, 30], 12)]},
        {"mode": "curves", "seed": 1514, "experiments": [curve("nonuniform_row_sparsity", 64, "random_dense", "nonuniform", [14], [20, 35, 60], 16)]},
        {"mode": "hard_coloring", "seed": 1515, "experiments": [{"label": f"growth_k_{k}", "k": k} for k in (3, 5, 8, 12)]},
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
    evidence_root = ROOT / "curation_reports/official_runs/0015"
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
        # Relative discrepancies below 1e-8 are scientifically meaningless and
        # must not weaken tolerance for finite-scale curve values.
        max_relative = max(max_relative, float((delta / np.maximum(np.abs(x), 1e-8)).max(initial=0)))
    if max_abs > 1e-10 or max_relative > 1e-5:
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
    adapter = ROOT / "curation_tools/fixed_sparsity_adapter.py"
    lock = ROOT / "curation_tools/environments/0015-environment.yml"
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
            "command": "<pinned-environment>/bin/python curation_tools/fixed_sparsity_adapter.py --task 0015 --checkout <clean-checkout> --input <input.json> --output <output.json>"})
    write_json(task_root / "hidden/tolerances.json", tolerance)
    provenance = {"schema_version": 4, "task_id": TASK_ID, "lifecycle": "validated", "gold_source": "pinned_official_checkout",
        "repository": "https://github.com/tchen-research/fixed_sparsity_matrix_approximation", "commit": COMMIT,
        "paper_version": args.paper_version, "paper_sha256": sha(args.paper),
        "notebook_sha256": {name: sha(args.checkout_1 / name) for name in ("sparse_recovery.ipynb", "hard_example.ipynb")},
        "parameter_patch": "One explicit numpy.random.seed(MT19937) call at the experiment-driver boundary; invalid m<s+2 points are omitted so output JSON remains finite. The sparse_recovery function is extracted and executed unchanged.",
        "environment": {"python": "3.10.9", "numpy": "1.24.2", "scipy": "1.10.1", "sympy": "1.11.1", "networkx": "3.0", "build_platform": platform.platform()},
        "environment_lock_sha256": sha(lock), "dependency_artifact_sha256": None,
        "official_reproduction": {"adapter_sha256": sha(adapter), "environment_lock_sha256": sha(lock), "dependency_artifact_sha256": None,
            "command": "python curation_tools/build_fixed_sparsity_task.py --checkout-1 <clean-1> --checkout-2 <clean-2> --paper <paper.pdf> --paper-version <version>",
            "clean_checkout_bundle_sha256": run_hashes, "raw_and_normalized_outputs": "curation_reports/official_runs/0015"},
        "independent_audit": {"implementation": "curation_tools/fixed_sparsity_scientific.py; independent Gaussian sketch, normal-equations row solves, matrix/pattern construction, errors, quantiles, and Theorem 1 bounds",
            "status": "passed", "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_relative, "derived_tolerances": tolerance},
        "cases": records}
    write_json(task_root / "hidden/provenance.json", provenance)
    write_json(ROOT / "curation_reports/fixed_sparsity.json", {"task_id": TASK_ID, "status": "validated", "official_commit": COMMIT,
        "public_cases": 3, "hidden_cases": 5, "two_clean_checkout_hashes_match": True, "normalized_bundle_sha256": run_hashes[0],
        "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_relative, "tolerances": tolerance})


INTERFACE_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"], "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
    "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}}}

TASK_TEXT = """# scibench_replication_0015

Implement Gaussian-sketch fixed-sparsity matrix approximation. The runner invokes `<entrypoint> --input input.json --output new-output-dir`; write finite `output.json`.

For every curve experiment, construct the named float64 matrix and normalize it to unit Frobenius norm. `tridiagonal_inverse` is `tridiag(-1,4,-1)^{-1}`. `trefethen_inverse` is the inverse of the diagonal matrix of the first `n` primes plus symmetric unit diagonals at offsets `2^j`, `j=1,...,floor(log2(n))`. `random_dense` uses standard normal entries. `random_sparse` chooses `pattern_parameters[0]` columns independently without replacement in each row and fills them with standard normal entries.

Construct `banded`, `power_bands`, `irregular`, `nonuniform`, or `matrix_support` Boolean patterns as follows. Banded includes offsets `-b,...,b`. Power bands include symmetric offsets within `b` of `2^j` for `j=0,...,floor(log2(n))`. Irregular chooses `s` columns independently per row. Nonuniform row `i` chooses `1+floor(i(s-1)/(n-1))` columns. Matrix support is the exact nonzero support.

At the case boundary initialize `numpy.random.RandomState(seed)` (MT19937), then process experiments and pattern parameters in listed order without reseeding. For every listed `m >= max_row_sparsity+2` and trial, draw `G` with shape `(n,m)`, compute `Z=AG`, and solve independently for each row `argmin_x ||Z_i-x G[S_i,:]||_2`. Return the exact structure shown by public outputs: maximum row sparsity, retained matvec counts, off-pattern Frobenius error, recovery RMSE, 10%/90% quantiles, displayed approximation values (off-pattern error plus recovery values), and Theorem 1 bounds `sqrt(s/(m-s-1))*off_error` and `off_error` plus that bound.

For `hard_coloring`, construct the paper pattern of dimension `k^2`: entry `(p*k+i,q*k+j)` is present iff `i=q` or `j=p`. Return its dimension, maximum row/column sparsity, exact coloring matvec count, and Gaussian exact-recovery threshold.
"""


if __name__ == "__main__":
    main()
