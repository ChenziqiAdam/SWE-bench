#!/usr/bin/env python3
"""Replay all 0021_core cases through two clean pinned official checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0021_core"
ADAPTER = ROOT / "curation_tools/reim_core_adapter.py"
COMMIT = "9760b18408f17d226124a93755294a95f15230f8"


def canonical(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--checkout-1", type=Path, required=True); parser.add_argument("--checkout-2", type=Path, required=True); args = parser.parse_args()
    rows, run_bundles = [], []
    with tempfile.TemporaryDirectory(prefix="scibench_0021_core_g8_") as temporary:
        temporary = Path(temporary)
        for run, checkout in enumerate((args.checkout_1, args.checkout_2), 1):
            commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
            if commit != COMMIT or dirty: raise RuntimeError("checkout is not clean and pinned")
            outputs = []
            for split in ("public", "hidden"):
                for case in sorted((TASK / split / "cases").iterdir()):
                    root = temporary / f"run_{run}_{split}_{case.name}"
                    subprocess.run([sys.executable, str(ADAPTER), "--task", "0021_core", "--checkout", str(checkout), "--input", str(case / "input.json"), "--output", str(root)], check=True, timeout=120)
                    actual = json.loads((root / "output.json").read_text()); expected = json.loads((case / "output.json").read_text())
                    if canonical(actual) != canonical(expected): raise RuntimeError(f"official replay mismatch: run {run} {split}/{case.name}")
                    outputs.append(actual); rows.append({"run": run, "split": split, "case_id": case.name, "canonical_output_sha256": canonical(actual)})
            run_bundles.append(canonical(outputs))
    independent = ROOT / "curation_tools/reim_core_scientific.py"; curator = ROOT / "curation_tools/fixtures/0021_core_reference_solution.py"
    blind = ROOT / "core_algorithm_audits/0021_core_g7_submission/solution.py"
    report = {"schema_version": 1, "task_id": TASK.name, "G8": "PASS", "commit": COMMIT, "source_sha256": sha(args.checkout_1 / "REIM.m"), "two_clean_checkouts_match": run_bundles[0] == run_bundles[1], "official_output_bundle_sha256": run_bundles[0], "runs": rows,
        "provenance": {"official_adapter_sha256": sha(ADAPTER), "input_injection_patch_sha256": sha(ROOT / "curation_tools/patches/0021-reim-core-input.patch"), "independent_implementation_sha256": sha(independent), "curator_reference_sha256": sha(curator), "blind_submission_sha256": sha(blind) if blind.is_file() else None},
        "fidelity_mapping": {"REIM.m:gm/gset": "adapter gset/dictionary", "REIM.m:L loop and max": "adapter residual_norms loop and np.argmax", "REIM.m:rm and max": "adapter residual and np.argmax", "REIM.m:G update": "adapter indexed interpolation matrix", "online interpolation": "solve G C at all target columns and evaluate selected query columns"}}
    if not report["two_clean_checkouts_match"]: raise RuntimeError("clean checkout bundles differ")
    (ROOT / "curation_reports/0021_core_oracle.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"G8": "PASS", "cases": len(rows) // 2, "bundle": run_bundles[0]}, indent=2))


if __name__ == "__main__": main()
