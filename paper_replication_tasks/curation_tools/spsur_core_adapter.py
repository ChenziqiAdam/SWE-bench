#!/usr/bin/env python3
"""Curator adapter invoking pinned spsur 1.0.1.3 through numeric interfaces."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

try:
    from .spsur_core_common import validate_case, validate_output
except ImportError:  # direct curator-script execution
    from spsur_core_common import validate_case, validate_output

TASK_SUFFIX = "0020_core"
DRIVER = Path(__file__).with_name("spsur_core_driver.R")


def rscript() -> str:
    override = os.environ.get("SPSUR_CORE_RSCRIPT")
    candidates = [override, "/opt/anaconda3/envs/scibench-replication-0020/bin/Rscript"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("the pinned 0020 R environment is unavailable")


def solve(case: dict[str, Any]) -> dict[str, Any]:
    validate_case(case)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="spsur_core_") as temporary:
        input_path = Path(temporary) / "input.json"
        input_path.write_text(json.dumps(case, allow_nan=False))
        subprocess.run(
            [rscript(), "--vanilla", "-e", 'stopifnot(as.character(packageVersion("spsur")) == "1.0.1.3")'],
            check=True, capture_output=True, text=True,
        )
        completed = subprocess.run(
            [rscript(), "--vanilla", str(DRIVER), str(input_path)],
            capture_output=True, text=True,
        )
        if completed.returncode:
            raise RuntimeError(f"spsur driver failed: {completed.stdout}\n{completed.stderr}")
    start = completed.stdout.find("{")
    if start < 0:
        raise RuntimeError(f"spsur driver produced no JSON: {completed.stdout}")
    result = json.loads(completed.stdout[start:])
    validate_output(result, case)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--checkout")  # retained for the common curator CLI
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    if args.task != TASK_SUFFIX:
        parser.error("unsupported task")
    case = json.loads(args.input.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    result = solve(case)
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(payload)
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True); args.raw_output.write_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
