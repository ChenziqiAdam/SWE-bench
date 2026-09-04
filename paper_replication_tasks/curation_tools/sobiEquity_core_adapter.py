#!/usr/bin/env python3
"""Official sobiEquity::b2sfca adapter for the BFCA-only 0017 core task."""

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

from sobiEquity_core_common import validate_case, validate_output

TASK_SUFFIX = "0017_core"
COMMIT = "80b6516acb0936a4c3e75d15fc3885f1d398021f"
B2SFCA_SHA256 = "ea13f116f03a607e2d7b403df3f9fb5da64d6484e88b320b68c025a46a21a6f9"
DRIVER_PATH = Path(__file__).resolve().parent / "sobiEquity_core_driver.R"
LAST_RAW: dict[str, Any] | None = None
_INSTALLED: set[Path] = set()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_rscript() -> str:
    override = os.environ.get("SOBIEQUITY_RSCRIPT")
    if override and Path(override).is_file():
        return override
    sibling = Path(sys.executable).resolve().parent / "Rscript"
    if sibling.is_file():
        return str(sibling)
    base = os.environ.get("CONDA_BASE") or subprocess.check_output(["conda", "info", "--base"], text=True).strip()
    candidate = Path(base) / "envs/scibench-replication-0017/bin/Rscript"
    if not candidate.is_file():
        raise RuntimeError("set SOBIEQUITY_RSCRIPT to the pinned R environment")
    return str(candidate)


def verify_checkout(checkout: Path) -> None:
    if subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip() != COMMIT:
        raise RuntimeError("official checkout is not at the pinned commit")
    source = checkout / "sobiEquity/R/b2sfca.R"
    if not source.is_file() or digest(source) != B2SFCA_SHA256:
        raise RuntimeError("pinned b2sfca.R is missing or changed")
    if not (checkout / "sobiEquity_0.1.0.tar.gz").is_file():
        raise RuntimeError("official package artifact is missing")


def install(checkout: Path, rscript: str) -> None:
    checkout = checkout.resolve()
    if checkout in _INSTALLED:
        return
    env = dict(os.environ, RENV_CONFIG_AUTOLOADER_ENABLED="FALSE")
    subprocess.run([rscript, "--vanilla", "-e", f'install.packages("{checkout / "sobiEquity_0.1.0.tar.gz"}", repos=NULL, type="source", quiet=TRUE)'],
                   check=True, cwd=checkout, env=env, capture_output=True, text=True)
    _INSTALLED.add(checkout)


def solve(case: dict[str, Any], checkout: Path) -> dict[str, Any]:
    global LAST_RAW
    clean = validate_case(case)
    checkout = checkout.resolve()
    verify_checkout(checkout)
    rscript = resolve_rscript()
    install(checkout, rscript)
    input_path = checkout / "_sobiEquity_core_case.json"
    input_path.write_text(json.dumps(clean), encoding="utf-8")
    try:
        completed = subprocess.run([rscript, "--vanilla", str(DRIVER_PATH), str(input_path)], check=True,
                                   cwd=checkout, env=dict(os.environ, RENV_CONFIG_AUTOLOADER_ENABLED="FALSE"),
                                   capture_output=True, text=True)
    finally:
        input_path.unlink(missing_ok=True)
    raw = json.loads(completed.stdout)
    LAST_RAW = raw
    result = {
        "hub": [int(item) for item in raw["los"]["hub"]],
        "level_of_service": [float(item) for item in raw["los"]["los"]],
        "population_unit": [int(item) for item in raw["accessibility"]["UID"]],
        "accessibility": [float(item) for item in raw["accessibility"]["accessibility"]],
    }
    return validate_output(result)


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
    case = json.loads(args.input.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    result = solve(case, args.checkout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(LAST_RAW, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
