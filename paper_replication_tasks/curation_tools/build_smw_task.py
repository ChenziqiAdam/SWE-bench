#!/usr/bin/env python3
"""Build task 0014 from two pinned clean SMW checkouts and audit independently."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path

import numpy as np

from smw_adapter import solve as official_solve, validate_case
from smw_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0014"
COMMIT = "05c0aeff63094a1acc356ec8ebc320d826900040"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def noise(rng, shape, epsilon):
    value = rng.normal(size=shape)
    return value * epsilon / np.linalg.norm(value, 2)


def generated_point(seed, n, k, regime, condition=8.0, e1=1e-6, e2=2e-6):
    rng = np.random.RandomState(seed)
    q1, _ = np.linalg.qr(rng.normal(size=(n, n)))
    q2, _ = np.linalg.qr(rng.normal(size=(n, n)))
    A = q1 @ np.diag(np.geomspace(condition, 1.0, n)) @ q2.T
    U = rng.normal(size=(n, k)); U /= np.linalg.norm(U, 2)
    V = rng.normal(size=(n, k)); V /= np.linalg.norm(V, 2)
    scale = .5 * (np.linalg.svd(A, compute_uv=False)[-1] if regime == "small" else np.linalg.norm(A, 2))
    U *= np.sqrt(scale); V *= np.sqrt(scale)
    return {"mode": "point", "A": A.tolist(), "U": U.tolist(), "V": V.tolist(),
            "E1": noise(rng, (n, n), e1).tolist(), "E2": noise(rng, (k, k), e2).tolist()}


def capacitance_point(seed, n, k, condition, target, e1, e2):
    """Construct V so I + V^T A^-1 U has prescribed singular values."""
    rng = np.random.RandomState(seed)
    q1, _ = np.linalg.qr(rng.normal(size=(n, n)))
    q2, _ = np.linalg.qr(rng.normal(size=(n, n)))
    A = q1 @ np.diag(np.geomspace(condition, 1.0, n)) @ q2.T
    U = rng.normal(size=(n, k)); U /= np.linalg.norm(U, 2)
    X = np.linalg.solve(A, U)
    capacitance = np.diag(np.asarray(target, dtype=float))
    M = capacitance - np.eye(k)
    gram_inverse = np.linalg.inv(X.T @ X)
    V = X @ gram_inverse @ M.T
    orthogonal = rng.normal(size=(n, k))
    orthogonal -= X @ gram_inverse @ (X.T @ orthogonal)
    V += .1 * orthogonal / np.linalg.norm(orthogonal, 2)
    actual = np.eye(k) + V.T @ X
    if not np.allclose(actual, capacitance, atol=1e-11, rtol=1e-11):
        raise RuntimeError("failed to construct target capacitance matrix")
    return {"mode": "point", "A": A.tolist(), "U": U.tolist(), "V": V.tolist(),
            "E1": noise(rng, (n, n), e1).tolist(), "E2": noise(rng, (k, k), e2).tolist()}


def threshold_sweep(seed, n, k):
    """Place epsilon samples immediately below/above Theorem 6 and 2 thresholds."""
    rng = np.random.RandomState(seed)
    A = rng.normal(size=(n, n))
    U = rng.normal(size=(n, k)); U /= np.linalg.norm(U, 2)
    V = rng.normal(size=(n, k)); V /= np.linalg.norm(V, 2)
    lamda = .5 * np.linalg.norm(A, 2)
    U *= np.sqrt(lamda); V *= np.sqrt(lamda)
    A_inv = np.linalg.inv(A)
    alpha = np.linalg.norm(np.linalg.inv(np.eye(k) + V.T @ A_inv @ U), 2)
    beta = np.linalg.norm(np.eye(k) + V.T @ A_inv @ U, 2)
    theorem_2 = 1 / (2 * lamda * alpha)
    t6_first = 1 / (2 * np.linalg.norm(A, 2))
    t6_second = (-beta + np.sqrt(beta**2 + 2 * lamda)) / (2 * lamda)
    low, high = 0.0, max(t6_first, t6_second, theorem_2)
    for _ in range(100):
        middle = (low + high) / 2
        if 2 * (beta + lamda * middle) ** 2 * middle < .5:
            low = middle
        else:
            high = middle
    theorem_6 = min(t6_first, t6_second, low)
    epsilon = sorted({1e-8, .9 * theorem_6, 1.1 * theorem_6, .9 * theorem_2, 1.1 * theorem_2, 100.0})
    return {"mode": "sweep", "n": n, "k": k, "update_regime": "large", "update_factor": .5,
            "epsilon_grid": epsilon, "replicates": 8, "seed": seed}


def scientific_design_audit(hidden):
    rows = []
    for index, case in enumerate(hidden, 1):
        clean = validate_case(case)
        A, U, V = clean["A"], clean["U"], clean["V"]
        singular = np.linalg.svd(A, compute_uv=False)
        lamda = np.linalg.norm(U, 2) * np.linalg.norm(V, 2)
        A_inv = np.linalg.inv(A)
        alpha = np.linalg.norm(np.linalg.inv(np.eye(U.shape[1]) + V.T @ A_inv @ U), 2)
        beta = np.linalg.norm(np.eye(U.shape[1]) + V.T @ A_inv @ U, 2)
        row = {"case_id": f"case_{index:02d}", "mode": case["mode"], "n": A.shape[0], "k": U.shape[1],
               "condition_number_A": float(singular[0] / singular[-1]), "lambda_over_sigma_min_A": float(lamda / singular[-1]),
               "alpha": float(alpha), "beta": float(beta)}
        validity = []
        for e1, e2 in ((draw[0], draw[1]) for draw in clean["draws"][::clean.get("replicates", 1)]):
            theorem_2 = e1 < 1 / (2 * lamda * alpha)
            theorem_6 = (e1 < 1 / (2 * np.linalg.norm(A, 2)) and e2 < 1 / (2 * (beta + lamda * e1))
                         and 2 * (beta + lamda * e1) ** 2 * e2 < .5)
            validity.append({"epsilon_1": float(e1), "epsilon_2": float(e2), "theorem_2_assumptions": bool(theorem_2),
                             "theorem_6_assumptions": bool(theorem_6)})
        row["epsilon_validity"] = validity
        rows.append(row)
    return rows


def cases():
    rng = np.random.RandomState(1401)
    A = np.diag([2.0, 3.0, 4.0])
    U = np.array([[.2], [.1], [.15]])
    V = np.array([[.1], [-.05], [.08]])
    diagonal = {"mode": "point", "A": A.tolist(), "U": U.tolist(), "V": V.tolist(),
                "E1": noise(rng, (3, 3), 1e-7).tolist(), "E2": noise(rng, (1, 1), 2e-7).tolist()}
    public = [
        diagonal,
        generated_point(1402, 5, 2, "large", condition=12, e1=3e-7, e2=8e-7),
        {"mode": "sweep", "n": 24, "k": 3, "update_regime": "small", "update_factor": .5,
         "epsilon_grid": np.logspace(-8, 2, 4).tolist(), "replicates": 8, "seed": 1403},
    ]
    hidden = [
        generated_point(1411, 4, 1, "small", condition=5, e1=2e-8, e2=7e-8),
        generated_point(1412, 6, 2, "small", condition=1e3, e1=1e-9, e2=3e-9),
        capacitance_point(1413, 7, 3, condition=15, target=[1e-2, 1.0, 1.5], e1=1e-11, e2=1e-8),
        capacitance_point(1414, 8, 4, condition=20, target=[1.0, 2.0, 10.0, 100.0], e1=1e-10, e2=1e-9),
        threshold_sweep(1415, 30, 4),
    ]
    return public, hidden


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-1", type=Path, required=True)
    parser.add_argument("--checkout-2", type=Path, required=True)
    parser.add_argument("--paper", type=Path, required=True)
    args = parser.parse_args()
    task_root = ROOT / TASK_ID
    evidence_root = ROOT / "curation_reports/official_runs/0014"
    if task_root.exists() or evidence_root.exists():
        raise RuntimeError("refusing to overwrite task/evidence")
    for checkout in (args.checkout_1, args.checkout_2):
        import subprocess
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
        if commit != COMMIT or dirty:
            raise RuntimeError("checkout is not clean and pinned")
    public, hidden = cases()
    design_audit = scientific_design_audit(hidden)
    flat = [(split, i, case) for split, values in (("public", public), ("hidden", hidden)) for i, case in enumerate(values, 1)]
    runs = [[official_solve(case, checkout) for _, _, case in flat] for checkout in (args.checkout_1, args.checkout_2)]
    if canonical_hash(runs[0]) != canonical_hash(runs[1]):
        raise RuntimeError("two clean official bundle hashes differ")
    independent = [independent_solve(case) for _, _, case in flat]
    max_abs = max_rel = 0.0
    per_field = {}
    for (_, _, _), official, audit in zip(flat, runs[0], independent):
        for key in official:
            x, y = np.asarray(official[key]), np.asarray(audit[key])
            delta = np.abs(x - y)
            max_abs = max(max_abs, float(delta.max(initial=0)))
            relative = delta / np.maximum(np.abs(x), 1e-300)
            max_rel = max(max_rel, float(relative.max(initial=0)))
            row = per_field.setdefault(key, {"max_abs": 0.0, "max_relative": 0.0})
            row["max_abs"] = max(row["max_abs"], float(delta.max(initial=0)))
            row["max_relative"] = max(row["max_relative"], float(relative.max(initial=0)))
    tolerance = {"comparison": "mixed", "atol": max(1e-11, 10 * max_abs), "rtol": max(1e-8, 10 * max_rel)}
    task_root.joinpath("public").mkdir(parents=True)
    task_root.joinpath("hidden").mkdir(parents=True)
    shutil.copyfile(args.paper, task_root / "public/paper.pdf")
    (task_root / "public/task.md").write_text(TASK_TEXT, encoding="utf-8")
    write_json(task_root / "public/interface.schema.json", INTERFACE_SCHEMA)
    lock = ROOT / "curation_tools/environments/0014-environment.yml"
    adapter = ROOT / "curation_tools/smw_adapter.py"
    notebook_hashes = {
        "SMW_forward_same_epsilon.ipynb": sha(args.checkout_1 / "SMW_forward_same_epsilon.ipynb"),
        "SMW_backward_same_epsilon.ipynb": sha(args.checkout_1 / "SMW_backward_same_epsilon.ipynb"),
    }
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
                        "raw_official_sha256": sha(evidence_root / f"run_1/{stem}.raw.json"),
                        "normalized_output_sha256": sha(evidence_root / f"run_1/{stem}.normalized.json"),
                        "output_sha256": sha(case_root / "output.json"), "checkout_commit": COMMIT,
                        "environment_lock_sha256": sha(lock), "adapter_sha256": sha(adapter),
                        "command": "<pinned-environment>/bin/python curation_tools/smw_adapter.py --task 0014 --checkout <clean-checkout> --input <input.json> --output <output.json>"})
    write_json(task_root / "hidden/tolerances.json", tolerance)
    provenance = {
        "schema_version": 4, "task_id": TASK_ID, "lifecycle": "validated", "gold_source": "pinned_official_checkout",
        "repository": "https://github.com/LinkaiMa/SMW", "commit": COMMIT, "paper_version": "arXiv:2504.04554v1 (21 pages)",
        "paper_sha256": sha(args.paper), "notebook_sha256": notebook_hashes,
        "parameter_patch": "JSON/RNG boundary only. The two compute_SMW function bodies are extracted and executed unchanged. Driver-level correction computes alpha and beta from the actual scaled U,V passed to those functions.",
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        "environment_lock_sha256": sha(lock), "dependency_artifact_sha256": None,
        "official_reproduction": {"adapter_sha256": sha(adapter), "environment_lock_sha256": sha(lock), "dependency_artifact_sha256": None,
            "command": "python curation_tools/build_smw_task.py --checkout-1 <clean-1> --checkout-2 <clean-2> --paper <arxiv-v1.pdf>",
            "clean_checkout_bundle_sha256": [canonical_hash(runs[0]), canonical_hash(runs[1])], "raw_and_normalized_outputs": "curation_reports/official_runs/0014"},
        "independent_audit": {"implementation": "curation_tools/smw_scientific.py; direct paper Theorem 2/6, Corollary 3/7, and independent SMW construction",
            "status": "passed", "maximum_absolute_discrepancy": max_abs, "maximum_relative_discrepancy": max_rel,
            "per_field_discrepancy": per_field, "derived_tolerances": tolerance},
        "scientific_case_design": design_audit,
        "cases": records,
    }
    write_json(task_root / "hidden/provenance.json", provenance)
    write_json(ROOT / "curation_reports/smw_stability.json", {"task_id": TASK_ID, "status": "validated", "official_commit": COMMIT,
        "public_cases": 3, "hidden_cases": 5, "two_clean_checkout_hashes_match": True,
        "normalized_bundle_sha256": canonical_hash(runs[0]), "maximum_absolute_discrepancy": max_abs,
        "maximum_relative_discrepancy": max_rel, "tolerances": tolerance, "scientific_case_design": design_audit})


INTERFACE_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"], "properties": {"schema_version": {"const": 4},
    "task_id": {"const": TASK_ID}, "entrypoint": {"oneOf": [{"type": "string", "minLength": 1},
    {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}}}

TASK_TEXT = """# scibench_replication_0014

Implement the paper's approximate Sherman–Morrison–Woodbury inverse and its forward/backward error expressions. The runner invokes `<entrypoint> --input <input.json> --output <new-output-dir>`; write `output.json`.

For every case, use float64 spectral norms. Let `B=A+U V^T`, `lambda=||U||_2 ||V||_2`, `A_tilde_inverse=A^{-1}+E1`, `Z_inverse=(I+V^T A_tilde_inverse U)^{-1}+E2`, and `B_tilde_inverse=A_tilde_inverse-A_tilde_inverse U Z_inverse V^T A_tilde_inverse`. Set `epsilon_1=||E1||_2`, `epsilon_2=||E2||_2`, `alpha=||(I+V^T A^{-1}U)^{-1}||_2`, and `beta=||I+V^T A^{-1}U||_2`.

Return exactly eight arrays: `epsilon_1`, `epsilon_2`, `forward_error_mean`, `forward_simplified_expression`, `forward_full_bound`, `backward_error_mean`, `backward_simplified_expression`, and `backward_full_bound`. Forward error is `||B^{-1}-B_tilde_inverse||_2`; backward error is `||B-B_tilde_inverse^{-1}||_2`. The simplified expressions are `2 epsilon_2 ||A^{-1}||_2 + 12 epsilon_1` and `2 epsilon_1 ||A||_2^2 + 8 epsilon_2`. The full bounds are Theorem 2 equation (16) and Theorem 6 equation (22).

`point` inputs supply `A,U,V,E1,E2` and produce arrays of length one. `sweep` inputs supply `n,k,update_regime,update_factor,epsilon_grid,replicates,seed`. Use `numpy.random.RandomState(seed)` (MT19937), float64, and draw in the order `A`, normalized `U`, normalized `V`, then for each epsilon and replicate `E1`, `E2`. Normalize each noise matrix to the epsilon spectral norm. Scale both normalized update factors by `sqrt(update_factor*sigma_min(A))` for `small` or `sqrt(update_factor*sigma_max(A))` for `large`. Average each quantity over replicates. Do not return matrices.
"""


if __name__ == "__main__":
    main()
