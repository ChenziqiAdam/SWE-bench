#!/usr/bin/env python3
"""Build 0015_core from two pinned checkouts and an independent QR audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import tempfile
from pathlib import Path

import numpy as np

from fixed_sparsity_core_adapter import COMMIT, NOTEBOOK_SHA256, PATCH_SHA256, solve as official_solve
from fixed_sparsity_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0015_core"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def serial(matrix: np.ndarray) -> list[list[float]]:
    return matrix.astype(float).tolist()


def payload(matrix: np.ndarray, mask: np.ndarray, sketch: np.ndarray) -> dict:
    return {"A": serial(matrix), "S": mask.astype(int).tolist(), "G": serial(sketch)}


def band(n: int, radius: int) -> np.ndarray:
    i, j = np.indices((n, n))
    return np.abs(i - j) <= radius


def hard_pattern(k: int) -> np.ndarray:
    result = np.zeros((k * k, k * k), dtype=bool)
    for p in range(k):
        for i in range(k):
            for q in range(k):
                for j in range(k):
                    result[p * k + i, q * k + j] = i == q or j == p
    return result


def primes(count: int) -> np.ndarray:
    found = []
    value = 2
    while len(found) < count:
        if all(value % p for p in found if p * p <= value):
            found.append(value)
        value += 1
    return np.asarray(found, dtype=float)


def cases() -> tuple[list[dict], list[dict], list[dict]]:
    rng = np.random.RandomState(15015)
    public: list[dict] = []

    s1 = np.array([[1, 0, 1, 0, 0], [0, 1, 0, 1, 0], [1, 0, 0, 0, 1], [0, 1, 1, 0, 0]], bool)
    a1 = rng.normal(size=s1.shape) * s1
    public.append(payload(a1, s1, rng.normal(size=(5, 2))))

    s2 = band(6, 1)
    public.append(payload(rng.normal(size=(6, 6)), s2, rng.normal(size=(6, 5))))

    s3 = np.zeros((5, 8), bool)
    supports = ([0], [1, 4], [0, 3, 7], [2, 5], [1, 2, 6, 7])
    for row, columns in enumerate(supports):
        s3[row, columns] = True
    public.append(payload(rng.normal(size=s3.shape), s3, rng.normal(size=(8, 8))))

    hidden: list[dict] = []
    designs: list[dict] = []

    x = rng.normal(size=(9, 9)); a = x.T @ x; s = np.eye(9, dtype=bool)
    hidden.append(payload(a, s, rng.normal(size=(9, 1))))
    designs.append({"case_id": "case_01", "hazard": "Wishart diagonal; rejects S*A, G-independent, and diagonal-estimator shortcuts"})

    x = rng.normal(size=(10, 10)); a = x.T @ x; s = band(10, 2)
    hidden.append(payload(a, s, rng.normal(size=(10, 7))))
    designs.append({"case_id": "case_02", "hazard": "Wishart band boundary m=s+2"})

    s = hard_pattern(3); a = rng.normal(size=s.shape) + 2.5 * rng.normal(size=s.shape) * ~s
    hidden.append(payload(a, s, rng.normal(size=(9, int(s.sum(axis=1).max()) + 3))))
    designs.append({"case_id": "case_03", "hazard": "paper hard-coloring pattern with off-pattern mass"})

    s = np.zeros((8, 8), bool)
    for start in range(0, 8, 2): s[start:start + 2, start:start + 2] = True
    a = 0.2 * rng.normal(size=(8, 8)) * s + 8.0 * rng.normal(size=(8, 8)) * ~s
    hidden.append(payload(a, s, rng.normal(size=(8, 4))))
    designs.append({"case_id": "case_04", "hazard": "coloring-favorable blocks with strong off-block mass"})

    n = 11; base = np.diag(primes(n))
    for offset in (2, 4, 8):
        base += np.diag(np.ones(n - offset), offset) + np.diag(np.ones(n - offset), -offset)
    a = np.linalg.inv(base); s = band(n, 2) | (np.abs(np.subtract.outer(np.arange(n), np.arange(n))) == 4)
    hidden.append(payload(a, s, rng.normal(size=(n, int(s.sum(axis=1).max()) + 3))))
    designs.append({"case_id": "case_05", "hazard": "Trefethen-primes inverse with multiband boundary rows"})

    s = np.zeros((4, 12), bool)
    for row, columns in enumerate(([0, 7], [1, 3, 10], [2], [0, 4, 8, 11])): s[row, columns] = True
    hidden.append(payload(rng.normal(size=s.shape), s, rng.normal(size=(12, 7))))
    designs.append({"case_id": "case_06", "hazard": "wide rectangular, asymmetric nonuniform supports"})

    s = np.zeros((12, 5), bool)
    for row in range(12): s[row, sorted({row % 5, (2 * row + 1) % 5})] = True
    scales = np.geomspace(1e-3, 1e3, 12)[:, None]
    hidden.append(payload(rng.normal(size=s.shape) * scales, s, rng.normal(size=(5, 5))))
    designs.append({"case_id": "case_07", "hazard": "tall rectangular with multiscale rows"})

    s = np.zeros((6, 7), bool)
    support_rows = ([0, 1, 2, 3], [1, 3], [0, 4, 6], [2], [1, 2, 5], [0, 3])
    for row, columns in enumerate(support_rows): s[row, columns] = True
    search = np.random.RandomState(81515)
    for _ in range(500000):
        g = search.normal(size=(7, 4))
        condition = float(np.linalg.cond(g[[0, 1, 2, 3]].T))
        if 1e3 <= condition <= 1e5: break
    else: raise RuntimeError("failed to find audited moderately ill-conditioned Gaussian realization")
    hidden.append(payload(rng.normal(size=s.shape), s, g))
    designs.append({"case_id": "case_08", "hazard": "iid-Gaussian realization with a moderately ill-conditioned legal row solve", "condition_number": condition})
    return public, hidden, designs


INTERFACE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"],
    "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
                   "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    args = parser.parse_args()
    destination = ROOT / TASK_ID
    evidence_destination = ROOT / "curation_reports/official_runs/0015_core"
    if destination.exists() or evidence_destination.exists():
        raise RuntimeError("refusing to overwrite existing task or evidence")
    public, hidden, designs = cases()
    flat = [(split, index, case) for split, values in (("public", public), ("hidden", hidden)) for index, case in enumerate(values, 1)]
    with tempfile.TemporaryDirectory(prefix="scibench_0015_core_build_", dir=ROOT) as temporary:
        stage = Path(temporary); task = stage / TASK_ID; evidence = stage / "official_runs"
        runs = []
        for run_index, checkout in enumerate((args.checkout_1, args.checkout_2), 1):
            run = []
            for split, index, case in flat:
                value = official_solve(case, checkout)
                run.append(value)
                write_json(evidence / f"run_{run_index}/{split}_case_{index:02d}.raw.json", value)
                write_json(evidence / f"run_{run_index}/{split}_case_{index:02d}.normalized.json", value)
            runs.append(run)
        run_hashes = [canonical_hash(run) for run in runs]
        if run_hashes[0] != run_hashes[1]:
            raise RuntimeError("official checkout outputs differ")
        audits = [independent_solve(case) for _, _, case in flat]
        max_abs = max_relative = 0.0
        for official, audit in zip(runs[0], audits):
            left = np.asarray(official["A_tilde"]); right = np.asarray(audit["A_tilde"])
            delta = np.abs(left - right)
            max_abs = max(max_abs, float(delta.max(initial=0)))
            max_relative = max(max_relative, float((delta / np.maximum(np.abs(left), 1e-10)).max(initial=0)))
        # The relative metric uses a 1e-10 denominator floor, so harmless
        # roundoff on near-zero entries may reach 1e-6 while absolute error
        # remains at 1e-12. Keep both limits fail-closed.
        if max_abs > 1e-8 or max_relative > 1e-5:
            raise RuntimeError(f"independent audit exceeds fail-closed threshold: {max_abs=}, {max_relative=}")
        tolerance = {"comparison": "mixed", "atol": max(1e-10, 10 * max_abs), "rtol": max(1e-9, 10 * max_relative)}
        (task / "public").mkdir(parents=True); (task / "hidden").mkdir()
        shutil.copyfile(ROOT / "scibench_replication_0015/public/paper.pdf", task / "public/paper.pdf")
        (task / "public/task.md").write_text("solution.py\n", encoding="utf-8")
        write_json(task / "public/interface.schema.json", INTERFACE_SCHEMA)
        records = []
        for offset, (split, index, case) in enumerate(flat):
            root = task / split / "cases" / f"case_{index:02d}"
            write_json(root / "input.json", case); write_json(root / "output.json", runs[0][offset])
            write_json(evidence / f"independent/{split}_case_{index:02d}.json", audits[offset])
            stem = f"{split}_case_{index:02d}"
            records.append({"split": split, "case_id": f"case_{index:02d}", "input_sha256": sha(root / "input.json"),
                            "output_sha256": sha(root / "output.json"),
                            "raw_official_sha256": sha(evidence / f"run_1/{stem}.raw.json"),
                            "normalized_output_sha256": sha(evidence / f"run_1/{stem}.normalized.json")})
        write_json(task / "hidden/tolerances.json", tolerance)
        provenance = {
            "schema_version": 4, "task_id": TASK_ID, "lifecycle": "validated", "gold_source": "pinned_official_checkout",
            "legacy_predecessor": "scibench_replication_0015", "repository": "https://github.com/tchen-research/fixed_sparsity_matrix_approximation",
            "commit": COMMIT, "paper_sha256": sha(task / "public/paper.pdf"), "notebook_sha256": NOTEBOOK_SHA256,
            "adapter_patch": "Inject input G in place of the notebook kernel's random draw; all downstream computation unchanged.",
            "adapter_patch_sha256": PATCH_SHA256, "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0015-core-environment.yml"),
            "dependency_artifact_sha256": None, "official_output_bundle_sha256": run_hashes,
            "official_reproduction": {"adapter_sha256": sha(ROOT / "curation_tools/fixed_sparsity_core_adapter.py"),
                "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0015-core-environment.yml"),
                "dependency_artifact_sha256": None, "clean_checkout_bundle_sha256": run_hashes,
                "raw_and_normalized_outputs": "curation_reports/official_runs/0015_core"},
            "independent_audit": {"implementation": "independent NumPy reduced-QR row least-squares", "status": "passed", "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_relative, "derived_tolerances": tolerance},
            "environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
            "case_design": designs, "cases": records,
        }
        write_json(task / "hidden/provenance.json", provenance)
        report = {"task_id": TASK_ID, "status": "oracle_passed", "G8": "PASS", "two_clean_checkouts_match": True,
                  "official_output_bundle_sha256": run_hashes[0], "adapter_patch_sha256": PATCH_SHA256,
                  "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_relative, "tolerances": tolerance}
        write_json(stage / "report.json", report)
        os.replace(task, destination)
        evidence_destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(evidence, evidence_destination)
        os.replace(stage / "report.json", ROOT / "curation_reports/0015_core_oracle.json")


if __name__ == "__main__":
    main()
