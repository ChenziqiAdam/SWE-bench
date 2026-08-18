#!/usr/bin/env python3
"""Curator-only adapter for task 0017: invokes pinned sobiEquity::b2sfca()/c2sfca()
verbatim via Rscript against an official checkout. Follows the same CLI contract as
official_adapter.py (--task/--checkout/--input/--output/--raw-output) so it slots
into promote_official.py unchanged; the underlying computation runs in R because
the official implementation is an R package, not a Python module.
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

TASK_SUFFIX = "0017"

DRIVER_PATH = Path(__file__).resolve().parent / "sobiEquity_driver.R"

B2SFCA_SHA256 = "ea13f116f03a607e2d7b403df3f9fb5da64d6484e88b320b68c025a46a21a6f9"
C2SFCA_SHA256 = "2a65bf7d2b42bd79052f3cb5e26e698e203338a3ca4233c40ddbadf73d2bae3f"

LAST_RAW: dict[str, Any] | None = None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_rscript() -> str:
    override = os.environ.get("SOBIEQUITY_RSCRIPT")
    if override:
        if not Path(override).is_file():
            raise RuntimeError(f"SOBIEQUITY_RSCRIPT does not point to a file: {override}")
        return override
    sibling = Path(sys.executable).resolve().parent / "Rscript"
    if sibling.is_file():
        return str(sibling)
    conda_base = os.environ.get("CONDA_BASE") or subprocess.check_output(
        ["conda", "info", "--base"], text=True
    ).strip()
    candidate = Path(conda_base) / "envs/sobiequity-audit/bin/Rscript"
    if not candidate.is_file():
        raise RuntimeError(
            "no R interpreter found; set SOBIEQUITY_RSCRIPT to the pinned "
            "curation_tools/environments/0017-r-environment.yml Rscript path"
        )
    return str(candidate)


def validate_case(case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise ValueError("case must be a JSON object")
    required = {"method", "threshold", "hub_filter"}
    if set(case) != required:
        raise ValueError(f"case must have exactly the fields {sorted(required)}")
    if case["method"] not in {"b2sfca", "c2sfca"}:
        raise ValueError("method must be b2sfca or c2sfca")
    threshold = case["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be numeric")
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold must be finite and positive")
    if case["hub_filter"] not in {"conventional_active", "all_active"}:
        raise ValueError("hub_filter must be conventional_active or all_active")
    return case


def verify_pinned_source(checkout: Path) -> None:
    b2sfca_path = checkout / "sobiEquity/R/b2sfca.R"
    c2sfca_path = checkout / "sobiEquity/R/c2sfca.R"
    if not b2sfca_path.is_file() or not c2sfca_path.is_file():
        raise RuntimeError("pinned sobiEquity R sources are missing from checkout")
    if digest(b2sfca_path) != B2SFCA_SHA256:
        raise RuntimeError("pinned official b2sfca.R changed since pinning")
    if digest(c2sfca_path) != C2SFCA_SHA256:
        raise RuntimeError("pinned official c2sfca.R changed since pinning")


def install_package(checkout: Path, rscript: str) -> None:
    tarball = checkout / "sobiEquity_0.1.0.tar.gz"
    if not tarball.is_file():
        raise RuntimeError("sobiEquity_0.1.0.tar.gz is missing from checkout")
    env = dict(os.environ, RENV_CONFIG_AUTOLOADER_ENABLED="FALSE")
    subprocess.run(
        [rscript, "--vanilla", "-e",
         f'install.packages("{tarball}", repos=NULL, type="source", quiet=TRUE)'],
        check=True, cwd=str(checkout), env=env, capture_output=True, text=True,
    )


def solve(case: dict[str, Any], checkout: Path) -> dict[str, Any]:
    global LAST_RAW
    clean = validate_case(case)
    verify_pinned_source(checkout)
    rscript = resolve_rscript()
    install_package(checkout, rscript)

    input_path = checkout / "_sobiEquity_adapter_case.json"
    input_path.write_text(json.dumps(clean), encoding="utf-8")
    env = dict(os.environ, RENV_CONFIG_AUTOLOADER_ENABLED="FALSE")
    try:
        completed = subprocess.run(
            [rscript, "--vanilla", str(DRIVER_PATH), str(input_path)],
            check=True, cwd=str(checkout), env=env, capture_output=True, text=True,
        )
    finally:
        input_path.unlink(missing_ok=True)

    raw = json.loads(completed.stdout)
    LAST_RAW = raw

    los = raw["los"]
    accessibility = raw["accessibility"]
    result = {
        "hub": [int(value) for value in los["hub"]],
        "level_of_service": [float(value) for value in los["los"]],
        "population_unit": [int(value) for value in accessibility["UID"]],
        "accessibility": [float(value) for value in accessibility["accessibility"]],
    }
    for key in ("level_of_service", "accessibility"):
        if not all(math.isfinite(value) for value in result[key]):
            raise ValueError(f"non-finite value in {key}")
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
