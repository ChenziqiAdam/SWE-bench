#!/usr/bin/env python3
"""Construct 0022_core from the pinned MATLAB block and independent NumPy audit."""

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

from ssarnoldi_core_adapter import COMMIT, DRIVER, SOURCE_SHA256, solve as official_solve
from ssarnoldi_core_common import select_largest
from ssarnoldi_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0022_core"


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value) -> str: return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
def matrix_list(x: np.ndarray) -> list[list[float]]: return x.astype(float).tolist()


def payload(A: np.ndarray, b: np.ndarray, S: np.ndarray, m: int, k: int) -> dict:
    return {"matrix": matrix_list(A), "start_vector": b.astype(float).tolist(),
            "sketch_matrix": matrix_list(S), "iterations": m, "selection_budget": k}


def base_matrix(rng: np.random.Generator, n: int, strength: float, spread: float = 0.8) -> np.ndarray:
    diagonal = np.linspace(1.0 - spread / 2, 1.0 + spread / 2, n)
    A = np.diag(diagonal)
    A += strength * np.diag(np.ones(n - 1), 1)
    A += 0.025 * rng.normal(size=(n, n))
    return A


def cases() -> tuple[list[dict], list[dict], list[dict]]:
    rng = np.random.Generator(np.random.PCG64(220022))
    specs = [
        ("public", 8, 3, 1, 4, 0.25, "small budget and first-step budget clamping"),
        ("public", 16, 5, 3, 8, 0.8, "nonnormal matrix and non-unit start"),
        ("public", 28, 7, 7, 8, 0.4, "minimal sketch and budget larger than early bases"),
        ("hidden", 32, 8, 2, 9, 2.5, "strongly nonnormal upper coupling"),
        ("hidden", 20, 6, 1, 7, 0.1, "canonical starting vector with minimal sketch and selection budget one"),
        ("hidden", 40, 10, 4, 18, 0.65, "oversampled sketch"),
        ("hidden", 56, 12, 3, 13, 0.9, "slightly perturbed canonical start"),
        ("hidden", 64, 12, 5, 18, 0.35, "moderately clustered spectrum and gradual Krylov conditioning"),
        ("hidden", 72, 16, 2, 20, 3.0, "long strongly nonnormal recurrence"),
        ("hidden", 48, 10, 6, 14, 0.55, "near-dependent sketch rows with selection margin"),
        ("hidden", 96, 20, 8, 30, 0.75, "largest dimension and iteration count"),
    ]
    public, hidden, designs = [], [], []
    for split, n, m, k, sdim, strength, hazard in specs:
        spread = 0.30 if "clustered" in hazard else 0.8
        A = base_matrix(rng, n, strength, spread)
        b = rng.normal(size=n) * (3.7 if split == "public" else 1.9)
        if "canonical starting" in hazard:
            b = np.zeros(n); b[0] = 4.0
        if "perturbed canonical" in hazard:
            b = np.zeros(n); b[0] = 4.0; b[1:] = 1e-3 * rng.normal(size=n - 1)
        S = rng.normal(size=(sdim, n)) / np.sqrt(sdim)
        if "near-dependent" in hazard:
            S[-1] = S[0] + 2e-4 * rng.normal(size=n)
        item = payload(A, b, S, m, k)
        (public if split == "public" else hidden).append(item)
        if split == "hidden": designs.append({"case_id": f"case_{len(hidden):02d}", "hazard": hazard})
    return public, hidden, designs


def diagnostics(case: dict, output: dict) -> dict:
    A = np.array(case["matrix"]); S = np.array(case["sketch_matrix"])
    V = np.array(output["basis"]); SV = np.array(output["sketched_basis"])
    margins, conds = [], []
    k = case["selection_budget"]
    for j in range(case["iterations"]):
        sw = S @ (A @ V[:, j]); c = np.linalg.pinv(SV[:, :j + 1]) @ sw
        order = select_largest(c, j + 1); count = min(j + 1, k)
        if count < j + 1: margins.append(float(abs(c[order[count - 1]]) - abs(c[order[count]])))
        conds.append(float(np.linalg.cond(SV[:, :j + 1])))
    return {"minimum_selection_margin": min(margins) if margins else None,
            "maximum_sketched_basis_condition": max(conds)}


SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
          "required": ["schema_version", "task_id", "entrypoint"], "properties": {
              "schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
              "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}}}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--official-source", type=Path, required=True)
    args = parser.parse_args(); destination = ROOT / TASK_ID
    if destination.exists(): raise RuntimeError("refusing to overwrite candidate")
    public, hidden, designs = cases(); flat = [(s, i, c) for s, rows in (("public", public), ("hidden", hidden)) for i, c in enumerate(rows, 1)]
    with tempfile.TemporaryDirectory(prefix="build_0022_core_", dir=ROOT) as tmp:
        stage = Path(tmp); task = stage / TASK_ID; evidence = stage / "official_runs"
        outputs, independent_outputs = [], []
        max_abs = max_rel = 0.0
        field_max = {name: 0.0 for name in ("basis", "hessenberg", "sketched_basis", "sketched_products")}
        official_hashes = []
        for run in (1, 2):
            run_values = []
            for split, index, case in flat:
                value = official_solve(case, args.official_source)
                write(evidence / f"run_{run}/{split}_case_{index:02d}.json", value); run_values.append(value)
            official_hashes.append(canonical(run_values))
            if run == 1: outputs = run_values
        if official_hashes[0] != official_hashes[1]: raise RuntimeError("two official runs are not byte-equivalent")
        for (split, index, case), official in zip(flat, outputs):
            audit = independent_solve(case); independent_outputs.append(audit)
            write(evidence / f"independent/{split}_case_{index:02d}.json", audit)
            for field in official:
                left, right = np.array(official[field]), np.array(audit[field]); difference = np.abs(left - right)
                max_abs = max(max_abs, float(difference.max(initial=0)))
                field_max[field] = max(field_max[field], float(difference.max(initial=0)))
                denominator = np.maximum(np.abs(left), 1e-8)
                max_rel = max(max_rel, float((difference / denominator).max(initial=0)))
        tolerance = {"comparison": "fieldwise", "field_rules": {
            name: {"atol": max(1e-13, 8 * discrepancy), "rtol": 1e-12}
            for name, discrepancy in field_max.items()}}
        if any(rule["atol"] > 1e-10 or rule["rtol"] > 1e-9 for rule in tolerance["field_rules"].values()):
            raise RuntimeError(f"oracle disagreement exceeds cap: {max_abs}, {max_rel}")
        records = []
        for (split, index, case), official in zip(flat, outputs):
            root = task / split / "cases" / f"case_{index:02d}"; write(root / "input.json", case); write(root / "output.json", official)
            records.append({"split": split, "case_id": f"case_{index:02d}", "input_sha256": sha(root / "input.json"),
                            "output_sha256": sha(root / "output.json"), "diagnostics": diagnostics(case, official)})
        (task / "public").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "curation_tools/ssarnoldi_paper/paper_original_arxiv_v3.pdf", task / "public/paper.pdf")
        (task / "public/task.md").write_text("solution.py\n", encoding="utf-8"); write(task / "public/interface.schema.json", SCHEMA)
        write(task / "hidden/tolerances.json", tolerance)
        implementation = ROOT / "curation_tools/ssarnoldi_core_scientific.py"
        reference = ROOT / "curation_tools/fixtures/0022_core_reference_solution.py"
        provenance = {"schema_version": 4, "task_id": TASK_ID, "lifecycle": "candidate_ready", "gold_source": "pinned_official_source",
            "paper_version": "arXiv:2306.03592v3", "paper_sha256": sha(task / "public/paper.pdf"),
            "repository": "https://github.com/simunec/sketch-select-arnoldi", "commit": COMMIT,
            "official_source_sha256": SOURCE_SHA256, "adapter_patch_sha256": sha(DRIVER),
            "official_adapter_sha256": sha(ROOT / "curation_tools/ssarnoldi_core_adapter.py"),
            "independent_implementation_sha256": sha(implementation), "curator_reference_sha256": sha(reference),
            "construction_script_sha256": sha(Path(__file__)),
            "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0022-octave-environment.yml"),
            "dependency_artifact_sha256": None,
            "runner_sha256": sha(ROOT / "run_submission.py"),
            "cases_bundle_sha256": canonical([c for _, _, c in flat]), "outputs_bundle_sha256": official_hashes[0],
            "environment": {"python": platform.python_version(), "numpy": np.__version__, "octave": "9.4.0", "platform": platform.platform()},
            "tolerances": tolerance, "case_design": designs, "cases": records,
            "official_reproduction": {"two_clean_runs_byte_identical": True, "run_hashes": official_hashes,
                "adapter_sha256": sha(ROOT / "curation_tools/ssarnoldi_core_adapter.py"),
                "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0022-octave-environment.yml"),
                "dependency_artifact_sha256": None, "clean_checkout_bundle_sha256": official_hashes,
                "raw_and_normalized_outputs": "curation_reports/official_runs/0022_core"},
            "independent_audit": {"status": "passed", "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_rel,
                "derived_tolerances": tolerance}}
        write(task / "hidden/provenance.json", provenance)
        report = {"schema_version": 1, "task_id": TASK_ID, "status": "oracle_passed", "G8": "PASS",
                  "two_clean_official_runs_match": True, "maximum_absolute_discrepancy": max_abs,
                  "maximum_relative_discrepancy": max_rel, "tolerances": tolerance, "provenance": provenance}
        write(stage / "report.json", report)
        os.replace(task, destination)
        target_evidence = ROOT / "curation_reports/official_runs/0022_core"; target_evidence.parent.mkdir(parents=True, exist_ok=True)
        os.replace(evidence, target_evidence); os.replace(stage / "report.json", ROOT / "curation_reports/0022_core_oracle.json")


if __name__ == "__main__": main()
