#!/usr/bin/env python3
"""Curator-only adapter for task 0021: invokes the pinned REIM.m/FEM/*.m
Octave functions against an official checkout. Follows the same CLI contract
as official_adapter.py (--task/--checkout/--input/--output/--raw-output) so it
slots into promote_official.py unchanged; the underlying computation runs in
Octave because the official implementation is MATLAB source, not a Python
module (see curation_reports/reim.json for the full Octave-compatibility
audit: FEM/*.m is core-language MATLAB verbatim; REIM.m requires one
Octave-only compatibility patch, see PINNED_SOURCE_SHA256 below and
curation_tools/patches/0021-reim-strcmp.patch).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reim_common import validate_case

TASK_SUFFIX = "0021"

DRIVER_PATH = Path(__file__).resolve().parent / "reim_driver.m"
U_EXACT_PATH = Path(__file__).resolve().parent / "reim_u_exact.m"
PATCHED_REIM_PATH = Path(__file__).resolve().parent / "reim_patched" / "REIM.m"

# sha256 of REIM.m as pinned at commit 9760b18408f17d226124a93755294a95f15230f8,
# BEFORE the Octave char==string compatibility patch (verbatim official source).
ORIGINAL_REIM_SHA256 = "f27dea36e57994569963d35e50b3cdc6fff4fdd872ee68018949cbd0ef97e033"
# sha256 of the same file AFTER curation_tools/patches/0021-reim-strcmp.patch
# is applied (== -> strcmp on the 5 family-dispatch comparisons only; verified
# byte-identical output to the unpatched original for f='power', the only
# family that runs unpatched under Octave at all -- see curation_reports/reim.json).
PATCHED_REIM_SHA256 = "e6b3b228b72a203c77d48abcaebcc81520ed929be0be19fb1763e2fb8a1c3aab"

PINNED_SOURCE_SHA256 = {
    "FEM/bisect.m": "1f0d1f2d32065777f1ff5680a2c0c1f1ae54a0c0b20bfbc591df08383ce0cd31",
    "FEM/gradbasis.m": "0e8c6ae5b5c0b48871a924d6d1e316accaab8b65b88335502c8e4428e1e86e4d",
    "FEM/myauxstructure.m": "82448a304ee09a64d1a8ef911f84b0def6ff3cd8b86e59b091df1e91b0c5b035",
    "FEM/P1mat2d.m": "c890daae28d29ee9b95239678ca7c972bae2a3f8da965c25e64fd80285708b3a",
    "FEM/P1rhs2d.m": "a92a443946515dc8535f4ca123ad4f0f2b842e01e58ba977062158ba149b5b11",
    "FEM/squaremesh.m": "3c8cf006fc4376d1030bab2cadfa8128c5f11e0981c6120b96260e433d6c3945",
    "FEM/uniformrefine.m": "1b7311a3889369452aced127dfc4dc823df8257a6a387db1dda1492c4c853227",
}

LAST_RAW: dict[str, Any] | None = None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pinned_source(checkout: Path) -> None:
    reim_path = checkout / "REIM.m"
    if not reim_path.is_file():
        raise RuntimeError("pinned official source is missing from checkout: REIM.m")
    if digest(reim_path) != ORIGINAL_REIM_SHA256:
        raise RuntimeError("pinned official source changed since pinning: REIM.m")
    for name, expected in PINNED_SOURCE_SHA256.items():
        path = checkout / name
        if not path.is_file():
            raise RuntimeError(f"pinned official source is missing from checkout: {name}")
        if digest(path) != expected:
            raise RuntimeError(f"pinned official source changed since pinning: {name}")


def prepare_patched_checkout(checkout: Path, work_dir: Path) -> Path:
    """Return a work tree with REIM.m's Octave char==string dispatch patch
    applied (curation_tools/patches/0021-reim-strcmp.patch), FEM/ copied
    verbatim, and the driver + reim_u_exact.m in place."""
    import shutil

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    shutil.copytree(checkout / "FEM", work_dir / "FEM")

    patched_reim = work_dir / "REIM.m"
    if PATCHED_REIM_PATH.is_file():
        shutil.copyfile(PATCHED_REIM_PATH, patched_reim)
    else:
        patch_file = Path(__file__).resolve().parent / "patches" / "0021-reim-strcmp.patch"
        shutil.copyfile(checkout / "REIM.m", patched_reim)
        subprocess.run(
            ["patch", "-p1", str(patched_reim)],
            input=patch_file.read_text(encoding="utf-8"), text=True, check=True,
            cwd=str(work_dir),
        )
    if digest(patched_reim) != PATCHED_REIM_SHA256:
        raise RuntimeError("patched REIM.m does not match the pinned patched-source hash")

    shutil.copyfile(DRIVER_PATH, work_dir / "reim_driver.m")
    shutil.copyfile(U_EXACT_PATH, work_dir / "reim_u_exact.m")
    return work_dir


def resolve_octave_command() -> list[str]:
    """Return the argv prefix used to invoke octave. On this platform, the
    octave/octave-cli binaries under a conda env's bin/ crash (garbled
    self-located path, or SIGSEGV on any code execution) unless invoked
    through `conda run`, which sets up DYLD/library search paths the
    binaries need at runtime; a bare absolute-path subprocess call to either
    binary does not carry that environment. `conda run --no-capture-output
    --name <env> octave-cli` is therefore the reliable invocation form."""
    override = os.environ.get("REIM_OCTAVE")
    if override:
        return override.split()
    sibling = Path(sys.executable).resolve().parent / "octave-cli"
    if sibling.is_file():
        return [str(sibling)]
    return ["conda", "run", "--no-capture-output", "--name", "scibench-replication-0021", "octave-cli"]


def solve(case: dict[str, Any], checkout: Path) -> dict[str, Any]:
    global LAST_RAW
    clean = validate_case(case)
    verify_pinned_source(checkout)
    octave_cmd = resolve_octave_command()

    import tempfile
    with tempfile.TemporaryDirectory(prefix="reim_adapter_work_") as tmp:
        work_dir = prepare_patched_checkout(checkout, Path(tmp) / "work")
        input_path = work_dir / "_reim_adapter_case.json"
        input_path.write_text(json.dumps(clean), encoding="utf-8")
        completed = subprocess.run(
            [*octave_cmd, "--path", str(work_dir),
             str(work_dir / "reim_driver.m"), str(input_path)],
            check=True, capture_output=True, text=True,
        )
        raw = json.loads(completed.stdout)

    LAST_RAW = raw
    result = _postprocess(clean["case_type"], raw)
    return result


def _finite_or_raise(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"non-finite {label}")
    return float(value)


def _postprocess(case_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    if case_type in ("rational_approx", "time_family_approx", "exp_family_approx", "precon_family_approx"):
        xm = raw["xm"] if isinstance(raw["xm"], list) else [raw["xm"]]
        bm = raw["bm"] if isinstance(raw["bm"], list) else [raw["bm"]]
        G = raw["G"]
        if not isinstance(G, list) or not G or not isinstance(G[0], list):
            G = [[float(x)] for x in G] if isinstance(G, list) else [[float(G)]]
        return {
            "case_type": case_type,
            "xm": [_finite_or_raise(x, "xm entry") for x in xm],
            "bm": [_finite_or_raise(x, "bm entry") for x in bm],
            "G": [[_finite_or_raise(x, "G entry") for x in row] for row in G],
            "Linf_error": _finite_or_raise(raw["Linf_error"], "Linf_error"),
        }
    if case_type == "fractional_fem":
        return {
            "case_type": "fractional_fem",
            "s": _finite_or_raise(raw["s"], "s"),
            "mesh_type": raw["mesh_type"],
            "N": int(raw["N"]),
            "L2_error": _finite_or_raise(raw["L2_error"], "L2_error"),
        }
    if case_type == "bdf2_fractional_heat":
        def as_list(value):
            return value if isinstance(value, list) else ([value] if value not in (None, []) else [])
        return {
            "case_type": "bdf2_fractional_heat",
            "s": _finite_or_raise(raw["s"], "s"),
            "T": [_finite_or_raise(x, "T entry") for x in as_list(raw["T"])],
            "err": [_finite_or_raise(x, "err entry") for x in as_list(raw["err"])],
            "tau": [_finite_or_raise(x, "tau entry") for x in as_list(raw["tau"])],
            "Tdel": [_finite_or_raise(x, "Tdel entry") for x in as_list(raw["Tdel"])],
            "taudel": [_finite_or_raise(x, "taudel entry") for x in as_list(raw["taudel"])],
        }
    raise ValueError(f"unsupported case_type: {case_type}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    if args.task != TASK_SUFFIX:
        parser.error("unsupported task")
    case = json.loads(args.input.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    result = solve(case, args.checkout.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if args.raw_output is not None:
        if LAST_RAW is None:
            raise RuntimeError("adapter did not expose raw official output")
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(LAST_RAW, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
