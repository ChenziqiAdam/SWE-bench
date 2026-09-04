#!/usr/bin/env python3
"""Curator-only adapter for task 0022: invokes the pinned
paper_ssa_final_test1a.m/test1b.m sketch-and-select Arnoldi algorithm
(verbatim inner recurrences, ported into ssarnoldi_driver.m) against an
official checkout of simunec/sketch-select-arnoldi, run under GNU Octave.
Follows the same CLI contract as reim_adapter.py (--task/--checkout/
--input/--output/--raw-output).
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
from ssarnoldi_common import validate_case, validate_spec

TASK_SUFFIX = "0022"

DRIVER_PATH = Path(__file__).resolve().parent / "ssarnoldi_driver.m"
COMPAT_DIR = Path(__file__).resolve().parent / "ssarnoldi_octave_compat"
MATRICES_DIR = Path(__file__).resolve().parent / "ssarnoldi_matrices"
EXTRACT_RANDOMNESS_PATH = Path(__file__).resolve().parent / "ssarnoldi_extract_randomness.m"

# sha256 of the two verbatim official scripts as pinned at commit
# 6e145837e4696bd9e26b3d6160b37f97e4188e10. Both are read for reference by
# curators; the driver ports their (identical except `t`) inner recurrences.
PINNED_SOURCE_SHA256 = {
    "paper_ssa_final_test1a.m": "8d16f9492dac4ed4273e52f1ab25dce151378cf455bc3f89ef9f2f1ae5087c2a",
    "paper_ssa_final_test1b.m": "49794437b40a617536dd182385010924eadba09ec23a694bc44102cc68305897",
}

# sha256 of the frozen Octave-compat shims -- these are NOT modified by this
# adapter; pinning them here just detects accidental drift.
COMPAT_SHA256 = {
    "maxk.m": "32daa9fe6e50cdb53424b30ecd31e812465127eff0f50d8b1d01fc76aa864469",
    "srht.m": "2a7b83d670b0afeffdff727782f3f1c002d0a3214342fb645d7f758ce05b6bd6",
}

MATRIX_SHA256 = {
    "torso3.mat": "8f4088bf23831ab0334a33139722688c4590b638d43ddb7e4d2c3518dba11e2f",
    "cryg10000.mat": "4b839d24a5b3fb0818e1e210d1f8434ee64f3e9a1c323c38874859db58a222f7",
    "torso1.mat": "bc3acb89a2c081b789f751b1d02fa213a18470c95ff15c0aee4a68a55e282f56",
}

LAST_RAW: dict[str, Any] | None = None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pinned_source(checkout: Path) -> None:
    for name, expected in PINNED_SOURCE_SHA256.items():
        path = checkout / name
        if not path.is_file():
            raise RuntimeError(f"pinned official source is missing from checkout: {name}")
        if digest(path) != expected:
            raise RuntimeError(f"pinned official source changed since pinning: {name}")
    for name, expected in COMPAT_SHA256.items():
        path = COMPAT_DIR / name
        if not path.is_file():
            raise RuntimeError(f"frozen Octave-compat shim is missing: {name}")
        if digest(path) != expected:
            raise RuntimeError(f"frozen Octave-compat shim changed since pinning: {name}")
    for name, expected in MATRIX_SHA256.items():
        path = MATRICES_DIR / name
        if not path.is_file():
            raise RuntimeError(f"pinned matrix file is missing: {name}")
        if digest(path) != expected:
            raise RuntimeError(f"pinned matrix file changed since pinning: {name}")


def resolve_octave_command() -> list[str]:
    """See reim_adapter.py's resolve_octave_command for the documented
    conda-run-is-required-on-this-machine quirk; identical logic here with
    this task's own conda env name."""
    override = os.environ.get("SSARNOLDI_OCTAVE")
    if override:
        return override.split()
    sibling = Path(sys.executable).resolve().parent / "octave-cli"
    if sibling.is_file():
        return [str(sibling)]
    return ["conda", "run", "--no-capture-output", "--name", "scibench-replication-0022", "octave-cli"]


def solve(case: dict[str, Any], checkout: Path) -> dict[str, Any]:
    global LAST_RAW
    clean = validate_case(case)
    verify_pinned_source(checkout)
    octave_cmd = resolve_octave_command()

    import tempfile
    with tempfile.TemporaryDirectory(prefix="ssarnoldi_adapter_work_") as tmp:
        input_path = Path(tmp) / "_ssarnoldi_adapter_case.json"
        input_path.write_text(json.dumps(clean), encoding="utf-8")
        completed = subprocess.run(
            [*octave_cmd, "--path", str(Path(__file__).resolve().parent),
             str(DRIVER_PATH), str(input_path)],
            check=True, capture_output=True, text=True,
        )
        raw = json.loads(completed.stdout)

    LAST_RAW = raw
    result = _postprocess(raw)
    return result


def extract_randomness(spec: dict[str, Any]) -> dict[str, Any]:
    """Curator-only helper for build_ssarnoldi_task.py: given a partial case
    spec (case_type/matrix/p/s/t/condbound, WITHOUT v0/D/perm -- those are
    what this generates), returns realized v0/D/perm via a real Octave
    rng('default') + randn/randi/randperm draw, using
    ssarnoldi_extract_randomness.m (which replicates srht.m's exact draw
    sequence without touching the frozen file -- see that file's header).
    perm is returned 1-INDEXED (Octave/MATLAB-native), matching the
    convention stored in case JSON / used directly by ssarnoldi_driver.m;
    consumers needing 0-indexed access (e.g. ssarnoldi_scientific.py's
    make_srht, NumPy convention) must subtract 1 themselves. Called once per
    case when a case is first constructed (build_ssarnoldi_task.py); the
    resulting v0/D/perm are then baked into that case's input.json
    permanently -- see ssarnoldi_common.py's module docstring for why."""
    clean = validate_spec(spec)
    octave_cmd = resolve_octave_command()
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ssarnoldi_extract_work_") as tmp:
        input_path = Path(tmp) / "_ssarnoldi_extract_case.json"
        input_path.write_text(json.dumps(clean), encoding="utf-8")
        output_path = Path(tmp) / "_ssarnoldi_extract_output.json"
        subprocess.run(
            [*octave_cmd, EXTRACT_RANDOMNESS_PATH.name, str(input_path), str(output_path)],
            check=True, capture_output=True, text=True, cwd=str(EXTRACT_RANDOMNESS_PATH.parent),
        )
        raw = json.loads(output_path.read_text(encoding="utf-8"))
    return {"v0": raw["v0"], "D": raw["D"], "perm": raw["perm"]}


def _normalize_numeric_or_sentinel(value: Any, label: str) -> Any:
    """Validates a driver-emitted scalar that is either a finite number or
    one of the driver's own non-finite string sentinels ("Inf"/"-Inf"/
    "NaN" -- see ssarnoldi_driver.m's comment: Octave's jsonencode silently
    maps non-finite doubles to JSON null, so the driver pre-encodes them as
    literal strings). The sentinel strings are passed through UNCHANGED
    (not decoded to a Python float) because this adapter writes its final
    output with allow_nan=False, matching reim_adapter.py's precedent --
    float('inf')/float('nan') cannot be JSON-encoded under that setting, so
    "Inf"/"-Inf"/"NaN" remain the on-disk representation of non-finite
    condition numbers / basis sizes throughout (driver output AND adapter
    output), and downstream comparison code must treat these three strings
    as the non-finite sentinels rather than as ordinary strings."""
    if isinstance(value, str):
        if value in ("Inf", "-Inf", "NaN"):
            return value
        raise ValueError(f"unexpected string in numeric field {label}: {value!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid numeric field {label}")
    if not math.isfinite(value):
        raise ValueError(f"unexpected raw non-finite float (should be a sentinel string) in {label}")
    return float(value)


_COND_FIELDS = [
    "cond_truncated", "cond_sketch_truncate", "cond_select_pinv", "cond_select_pinv_recomp",
    "cond_select_corr", "cond_select_corr_pinv", "cond_select_omp", "cond_select_sp", "cond_select_greedy",
]
_SIZE_FIELDS = [
    "truncated", "sketch_truncate", "select_pinv", "select_pinv_recomp",
    "select_corr", "select_corr_pinv", "select_omp", "select_sp", "select_greedy",
]


def _postprocess(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("case_type") != "arnoldi_cond_growth":
        raise ValueError(f"unsupported case_type: {raw.get('case_type')!r}")
    result: dict[str, Any] = {"case_type": "arnoldi_cond_growth"}
    for field in _COND_FIELDS:
        curve = raw[field]
        if not isinstance(curve, list):
            raise ValueError(f"{field} is not a list")
        result[field] = [_normalize_numeric_or_sentinel(x, field) for x in curve]
    basis_size = raw["basis_size"]
    result["basis_size"] = {
        name: _normalize_numeric_or_sentinel(basis_size[name], f"basis_size.{name}") for name in _SIZE_FIELDS
    }
    return result


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
