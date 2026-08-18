#!/usr/bin/env python3
"""Curator-only adapter for task 0019: invokes the pinned seccurv_* Octave
functions verbatim against an official checkout. Follows the same CLI contract
as official_adapter.py (--task/--checkout/--input/--output/--raw-output) so it
slots into promote_official.py unchanged; the underlying computation runs in
Octave because the official implementation is MATLAB source, not a Python
module. No MATLAB toolbox functions are used anywhere in the pinned files, so
GNU Octave reproduces MATLAB's own evaluation exactly (verified during
curation: core-language-only function calls, byte-identical results across
independent clean checkouts).
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
from stiefelcurv_common import validate_case

TASK_SUFFIX = "0019"

DRIVER_PATH = Path(__file__).resolve().parent / "stiefelcurv_driver.m"

PINNED_SOURCE_SHA256 = {
    "seccurv_Stiefel_canon.m": "bcf921bec55711ae21890e54e57efcaabceeeb708990c1a561d64d621cd30693",
    "seccurv_Stiefel_euclid.m": "6b00f2426f6762e570ed5b312ce79061b0f8fe40e8b598acdc467f5c2087db0c",
    "seccurv_Grassmann.m": "cc28a7de1cf68e718e3a9138ac99c1f3b4acdfc57062bf19dd186ae3256c278c",
    "seccurv_SOn.m": "8a9997320bde51645a7247c304bda4df3262037f9cce9735c879046303fe35cb",
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


def resolve_octave() -> str:
    override = os.environ.get("STIEFELCURV_OCTAVE")
    if override:
        if not Path(override).is_file():
            raise RuntimeError(f"STIEFELCURV_OCTAVE does not point to a file: {override}")
        return override
    sibling = Path(sys.executable).resolve().parent / "octave"
    if sibling.is_file():
        return str(sibling)
    conda_base = os.environ.get("CONDA_BASE") or subprocess.check_output(
        ["conda", "info", "--base"], text=True
    ).strip()
    candidate = Path(conda_base) / "envs/scibench-replication-0019/bin/octave"
    if not candidate.is_file():
        raise RuntimeError(
            "no Octave interpreter found; set STIEFELCURV_OCTAVE to the pinned "
            "curation_tools/environments/0019-octave-environment.yml octave path"
        )
    return str(candidate)


def solve(case: dict[str, Any], checkout: Path) -> dict[str, Any]:
    global LAST_RAW
    clean = validate_case(case)
    verify_pinned_source(checkout)
    octave = resolve_octave()

    input_path = checkout / "_stiefelcurv_adapter_case.json"
    input_path.write_text(json.dumps(clean), encoding="utf-8")
    try:
        completed = subprocess.run(
            [octave, "--no-gui", "--no-window-system", "--path", str(checkout),
             str(DRIVER_PATH), str(input_path)],
            check=True, capture_output=True, text=True,
        )
    finally:
        input_path.unlink(missing_ok=True)

    raw = json.loads(completed.stdout)
    LAST_RAW = raw

    seccurv = raw["seccurv"]
    if isinstance(seccurv, bool) or not isinstance(seccurv, (int, float)) or not math.isfinite(seccurv):
        raise ValueError("non-finite sectional curvature")
    result = {"metric": clean["metric"], "seccurv": float(seccurv)}
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
