#!/usr/bin/env python3
"""Official-oracle adapter for the pinned sketch-and-select pinv block."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from ssarnoldi_core_common import validate_case, validate_output

COMMIT = "6e145837e4696bd9e26b3d6160b37f97e4188e10"
SOURCE_NAME = "paper_ssa_final_test1a.m"
SOURCE_SHA256 = "8d16f9492dac4ed4273e52f1ab25dce151378cf455bc3f89ef9f2f1ae5087c2a"
DRIVER = Path(__file__).with_name("ssarnoldi_core_driver.m")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(source: Path) -> None:
    candidate = source / SOURCE_NAME if source.is_dir() else source
    if not candidate.is_file() or sha(candidate) != SOURCE_SHA256:
        raise RuntimeError("official MATLAB source is absent or does not match the pinned commit")


def octave_command() -> list[str]:
    override = os.environ.get("SSARNOLDI_OCTAVE")
    if override: return override.split()
    return ["conda", "run", "--no-capture-output", "--name", "scibench-replication-0022", "octave-cli"]


def solve(value: dict, source: Path) -> dict:
    validate_case(value); verify_source(source)
    with tempfile.TemporaryDirectory(prefix="ssarnoldi_core_") as temporary:
        case_path = Path(temporary) / "input.json"
        case_path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
        completed = subprocess.run([*octave_command(), str(DRIVER), str(case_path)], check=True,
                                   capture_output=True, text=True, timeout=120)
    raw = json.loads(completed.stdout, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    return validate_output(raw, value)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--source", type=Path); parser.add_argument("--checkout", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    source = args.source or args.checkout
    if source is None: parser.error("--source or --checkout is required")
    if args.task is not None and args.task != "0022": parser.error("unsupported task")
    result = solve(value, source)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "output.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__": main()
