#!/usr/bin/env python3
"""Construct scibench_replication_0023_core from the Python-port oracle + independent audit.

The oracle (``rts_core_adapter.py``) is a Python transcription of RandomTimeShifts.jl
pinned at commit ``baf6da64`` and is promoted under a recorded G8 waiver (no Julia
toolchain in this repo).  Every case is cross-checked against a separately written
independent implementation (``rts_core_scientific.py``); comparison tolerances are
derived from the maximum fieldwise discrepancy.
"""

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

from rts_core_adapter import _PORT_COMMIT, solve as official_solve
from rts_core_common import validate_output
from rts_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0023_core"
PAPER_SHA256 = "228fb9a21cdaa68a52711aaa7f6cf25b5fee0eba429743760c9c70696d49e1dc"
PAPER_VERSION = "J. Math. Biol. 89:33 (2024), publisher PDF"
REPOSITORY = "https://github.com/djmorris7/RandomTimeShifts.jl"

_CME_TABLE = ROOT / "curation_tools/rts_iltcme_ext.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def cme_coefficients(n_terms: int = 21) -> dict:
    table = json.loads(_CME_TABLE.read_text())
    best = table[0]
    for p in table:
        if p["cv2"] < best["cv2"] and p["n"] + 1 <= n_terms:
            best = p
    return {
        "eta_real": list(best["eta_re"]),
        "eta_imag": list(best["eta_im"]),
        "beta_real": list(best["beta_re"]),
        "beta_imag": list(best["beta_im"]),
    }


def _grid(stop: float, step: float) -> list[float]:
    return [round(x, 6) for x in np.arange(0.0, stop + step / 2, step)]


def _sir(r0: float, gamma: float, z0: list[int], n: int, h: float, eps: float, grid: list[float]) -> dict:
    beta = r0 * gamma
    return {
        "mean_matrix": [[beta - gamma]],
        "linear_terms": [],
        "quadratic_terms": [[1, 1, 1, beta]],
        "lifetimes": [beta + gamma],
        "initial_condition": z0,
        "n_moments": n,
        "embedding_step": h,
        "taylor_epsilon": eps,
        "cdf_grid": grid,
        "cme_coefficients": CME,
    }


def _seir(r0: float, sig_inv: float, gam_inv: float, z0: list[int], n: int, h: float, eps: float, grid: list[float]) -> dict:
    sig = 1.0 / sig_inv
    gam = 1.0 / gam_inv
    beta = r0 * gam
    return {
        "mean_matrix": [[-sig, sig], [beta, -gam]],
        "linear_terms": [[1, 2, sig]],
        "quadratic_terms": [[2, 1, 2, beta]],
        "lifetimes": [sig, beta + gam],
        "initial_condition": z0,
        "n_moments": n,
        "embedding_step": h,
        "taylor_epsilon": eps,
        "cdf_grid": grid,
        "cme_coefficients": CME,
    }


def _chain(rates: dict, z0: list[int], n: int, h: float, eps: float, grid: list[float]) -> dict:
    e12, e23, iback, irem = rates["e12"], rates["e23"], rates["iback"], rates["irem"]
    return {
        "mean_matrix": [[-e12, e12, 0.0], [0.0, -e23, e23], [iback, 0.0, -irem]],
        "linear_terms": [[1, 2, e12], [2, 3, e23]],
        "quadratic_terms": [[3, 1, 3, iback]],
        "lifetimes": [e12, e23, iback + irem],
        "initial_condition": z0,
        "n_moments": n,
        "embedding_step": h,
        "taylor_epsilon": eps,
        "cdf_grid": grid,
        "cme_coefficients": CME,
    }


CME = cme_coefficients(21)


def cases() -> tuple[list[dict], list[dict], list[dict]]:
    g_mid = _grid(12.0, 0.5)
    public = [
        _sir(2.4, 1.0, [1], 21, 0.1, 1e-10, _grid(8.0, 0.5)),
        _seir(1.6, 2.5, 2.5, [1, 0], 30, 1.0, 1e-6, g_mid),
        _chain({"e12": 0.5, "e23": 0.5, "iback": 0.7, "irem": 0.35}, [1, 0, 0], 25, 1.0, 1e-6, g_mid),
    ]
    hidden_specs = [
        ("SIR analytic single founder", _sir(5.0, 0.6, [1], 21, 0.1, 1e-10, _grid(6.0, 0.4))),
        ("near-critical growth", _seir(1.2, 2.0, 3.0, [1, 0], 30, 1.0, 1e-6, g_mid)),
        ("quadratic high extinction", _sir(1.3, 1.0, [1], 25, 0.2, 1e-10, _grid(14.0, 0.5))),
        (
            "strong type asymmetry",
            _chain({"e12": 0.15, "e23": 1.5, "iback": 0.9, "irem": 0.3}, [2, 1, 0], 25, 1.0, 1e-6, g_mid),
        ),
        ("low moment count", _seir(1.7, 2.0, 3.0, [1, 0], 3, 1.0, 1e-6, _grid(7.0, 0.5))),
        ("low moment count near-critical", _seir(1.2, 2.0, 3.0, [1, 0], 4, 1.0, 1e-6, g_mid)),
        ("large embedding step", _seir(1.7, 2.0, 3.0, [1, 0], 30, 5.0, 1e-6, g_mid)),
        ("multi-founder SEIR", _seir(2.2, 1.8, 2.2, [4, 3], 25, 1.0, 1e-6, g_mid)),
    ]
    hidden = [c for _, c in hidden_specs]
    designs = [
        {"case_id": f"case_{i:02d}", "hazard": label}
        for i, (label, _) in enumerate(hidden_specs, 1)
    ]
    return public, hidden, designs


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "task_id", "entrypoint"],
    "properties": {
        "schema_version": {"const": 4},
        "task_id": {"const": TASK_ID},
        "entrypoint": {
            "oneOf": [
                {"type": "string", "minLength": 1},
                {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
            ]
        },
    },
}


def _diag(case: dict, output: dict) -> dict:
    cdf = np.array(output["w_cdf"])
    return {
        "q_star": float(output["q_star"]),
        "lambda": float(output["lambda"]),
        "cdf_min_increment": float(np.min(np.diff(cdf))) if cdf.size > 1 else None,
        "cdf_tail": float(cdf[-1]),
        "mean_moment": float(output["w_moments"][0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-overwrite", action="store_true")
    args = parser.parse_args()
    destination = ROOT / TASK_ID

    public, hidden, designs = cases()
    flat = [(s, i, c) for s, rows in (("public", public), ("hidden", hidden)) for i, c in enumerate(rows, 1)]

    with tempfile.TemporaryDirectory(prefix="build_0023_core_", dir=ROOT) as tmp:
        stage = Path(tmp)
        task = stage / TASK_ID
        evidence = stage / "official_runs"

        official_hashes = []
        outputs: list[dict] = []
        for run in (1, 2):
            run_values = []
            for split, index, case in flat:
                value = official_solve(case)
                validate_output(value, case)
                write(evidence / f"run_{run}/{split}_case_{index:02d}.json", value)
                run_values.append(value)
            official_hashes.append(canonical(run_values))
            if run == 1:
                outputs = run_values
        if official_hashes[0] != official_hashes[1]:
            raise RuntimeError("two official (port) runs are not byte-equivalent")

        field_max = {"w_cdf": 0.0, "w_moments": 0.0, "q_star": 0.0, "lambda": 0.0}
        field_rel = {"w_cdf": 0.0, "w_moments": 0.0, "q_star": 0.0, "lambda": 0.0}
        max_abs = max_rel = 0.0
        per_case_worst = []
        for (split, index, case), official in zip(flat, outputs):
            audit = independent_solve(case)
            validate_output(audit, case)
            write(evidence / f"independent/{split}_case_{index:02d}.json", audit)
            worst = {"case": f"{split}_case_{index:02d}"}
            for field in field_max:
                left = np.atleast_1d(np.array(official[field], dtype=float))
                right = np.atleast_1d(np.array(audit[field], dtype=float))
                diff = np.abs(left - right)
                rel = diff / np.maximum(np.abs(left), 1e-8)
                field_max[field] = max(field_max[field], float(diff.max(initial=0.0)))
                field_rel[field] = max(field_rel[field], float(rel.max(initial=0.0)))
                max_abs = max(max_abs, float(diff.max(initial=0.0)))
                max_rel = max(max_rel, float(rel.max(initial=0.0)))
                worst[field] = [float(diff.max(initial=0.0)), float(rel.max(initial=0.0))]
            per_case_worst.append(worst)

        # Tolerance policy (see 0023_core_cases_design.md "Tolerances"):
        # derived from the maximum fieldwise oracle-vs-independent discrepancy
        # (two implementations that share no source).  w_moments spans several
        # orders of magnitude (E[W^5] ~ hundreds), so it is gated relatively.
        # A modest atol floor keeps near-zero CDF grid points from demanding
        # unattainable absolute precision.
        tolerance = {
            "comparison": "fieldwise",
            "field_rules": {
                "w_cdf": {"atol": max(1e-9, 8 * field_max["w_cdf"]), "rtol": 1e-8},
                "w_moments": {"atol": max(1e-8, 8 * field_max["w_moments"]), "rtol": max(1e-8, 8 * field_rel["w_moments"])},
                "q_star": {"atol": max(1e-10, 8 * field_max["q_star"]), "rtol": 1e-9},
                "lambda": {"atol": max(1e-10, 8 * field_max["lambda"]), "rtol": 1e-9},
            },
        }
        caps = {"w_cdf": (1e-6, 1e-6), "w_moments": (1e-3, 1e-6), "q_star": (1e-7, 1e-7), "lambda": (1e-7, 1e-7)}
        for name, rule in tolerance["field_rules"].items():
            amax, rmax = caps[name]
            if rule["atol"] > amax or rule["rtol"] > rmax:
                print("per-case worst (abs, rel) by field:")
                for w in per_case_worst:
                    print(" ", w)
                raise RuntimeError(
                    f"oracle-vs-independent disagreement on {name} exceeds cap: "
                    f"atol={rule['atol']:.2e} rtol={rule['rtol']:.2e}"
                )

        records = []
        for (split, index, case), official in zip(flat, outputs):
            root = task / split / "cases" / f"case_{index:02d}"
            write(root / "input.json", case)
            write(root / "output.json", official)
            records.append(
                {
                    "split": split,
                    "case_id": f"case_{index:02d}",
                    "input_sha256": sha(root / "input.json"),
                    "output_sha256": sha(root / "output.json"),
                    "diagnostics": _diag(case, official),
                }
            )

        (task / "public").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "curation_tools/rts_paper.pdf", task / "public/paper.pdf")
        (task / "public/task.md").write_text("solution.py\n", encoding="utf-8")
        write(task / "public/interface.schema.json", SCHEMA)
        write(task / "hidden/tolerances.json", tolerance)

        adapter = ROOT / "curation_tools/rts_core_adapter.py"
        common = ROOT / "curation_tools/rts_core_common.py"
        independent = ROOT / "curation_tools/rts_core_scientific.py"
        reference = ROOT / "curation_tools/fixtures/0023_core_reference_solution.py"
        port_prov = ROOT / "curation_tools/rts_core_port_provenance.json"

        provenance = {
            "schema_version": 4,
            "task_id": TASK_ID,
            "lifecycle": "candidate_ready",
            "gold_source": "python_port_oracle",
            "g8_status": "waiver",
            "g8_waiver_reason": "official implementation is Julia (RandomTimeShifts.jl); "
            "repo has no Julia toolchain. Oracle is a pinned Python port, cross-checked "
            "against an independent Python implementation and the SIR closed form.",
            "paper_version": PAPER_VERSION,
            "paper_sha256": sha(task / "public/paper.pdf"),
            "repository": REPOSITORY,
            "commit": _PORT_COMMIT,
            "port_provenance_sha256": sha(port_prov),
            "cme_table_sha256": sha(_CME_TABLE),
            "official_adapter_sha256": sha(adapter),
            "common_module_sha256": sha(common),
            "independent_implementation_sha256": sha(independent),
            "curator_reference_sha256": sha(reference),
            "construction_script_sha256": sha(Path(__file__)),
            "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0023-core-environment.yml"),
            "runner_sha256": sha(ROOT / "run_submission.py"),
            "cases_bundle_sha256": canonical([c for _, _, c in flat]),
            "outputs_bundle_sha256": official_hashes[0],
            "environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "platform": platform.platform(),
            },
            "tolerances": tolerance,
            "case_design": designs,
            "cases": records,
            "official_reproduction": {
                "two_clean_runs_byte_identical": True,
                "run_hashes": official_hashes,
                "adapter_sha256": sha(adapter),
                "environment_lock_sha256": sha(ROOT / "curation_tools/environments/0023-core-environment.yml"),
                "raw_and_normalized_outputs": "curation_reports/official_runs/0023_core",
                "note": "'official' here means the pinned Python port; see g8_status.",
            },
            "independent_audit": {
                "status": "passed",
                "maximum_absolute_discrepancy": max_abs,
                "maximum_relative_discrepancy": max_rel,
                "derived_tolerances": tolerance,
            },
        }
        write(task / "hidden/provenance.json", provenance)

        report = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "status": "oracle_cross_checked",
            "G8": "WAIVER",
            "two_clean_official_runs_match": True,
            "maximum_absolute_discrepancy": max_abs,
            "maximum_relative_discrepancy": max_rel,
            "tolerances": tolerance,
            "provenance": provenance,
        }
        write(stage / "report.json", report)

        if destination.exists():
            if not args.allow_overwrite:
                raise RuntimeError("destination exists; pass --allow-overwrite to replace")
            shutil.rmtree(destination)
        os.replace(task, destination)

        target_evidence = ROOT / "curation_reports/official_runs/0023_core"
        target_evidence.parent.mkdir(parents=True, exist_ok=True)
        if target_evidence.exists():
            shutil.rmtree(target_evidence)
        os.replace(evidence, target_evidence)
        os.replace(stage / "report.json", ROOT / "curation_reports/0023_core_oracle.json")

    print(f"built {destination}")
    print(f"  max abs discrepancy (oracle vs independent): {max_abs:.3e}")
    print(f"  max rel discrepancy: {max_rel:.3e}")
    print(f"  tolerances: {json.dumps(tolerance['field_rules'])}")


if __name__ == "__main__":
    main()
