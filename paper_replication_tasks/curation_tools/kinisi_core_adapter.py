#!/usr/bin/env python3
"""Thin JSON adapter around pinned kinisi 1.1.0 MSDBootstrap.diffusion."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np

from kinisi_core_common import summarize, validate_case, validate_output

COMMIT = "54f3bc4f7167d18d2f4af1008880e5bb29d99797"
ANALYSIS_COMMIT = "9141e4edcddc386cdf10a9201d70aba1abaeb66c"
DIFFUSION_SHA256 = "606def108e43422b14953fd1ec4d75a1ea47110058f111ff0f1f84e3413944b7"


def _load(checkout: Path):
    checkout = checkout.resolve()
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != COMMIT:
        raise RuntimeError(f"kinisi checkout is {head}, expected {COMMIT}")
    source = checkout / "kinisi/diffusion.py"
    import hashlib
    if hashlib.sha256(source.read_bytes()).hexdigest() != DIFFUSION_SHA256:
        raise RuntimeError("pinned kinisi diffusion.py hash mismatch")
    spec = importlib.util.spec_from_file_location("_kinisi_1_1_0_diffusion", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned kinisi implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def solve(payload: dict, checkout: Path) -> dict:
    case = validate_case(payload)
    module = _load(checkout)
    dims = case["dimension"]
    dimension_name = "xyz"[:dims]
    displacements = []
    # This is a representation-only conversion: kinisi squares and sums the
    # vectors, recovering each JSON squared-displacement value exactly.
    for squared in case["samples"]:
        vector = np.zeros((1, squared.size, dims), dtype=float)
        vector[0, :, 0] = np.sqrt(squared)
        displacements.append(vector)
    rng = np.random.RandomState(case["mcmc_seed"])
    analysis = module.MSDBootstrap(
        case["lag_times"], displacements, case["counts"],
        dimension=dimension_name, random_state=rng, progress=False,
    )
    analysis.diffusion(
        case["fit_start"], cond_max=case["condition_limit"],
        random_state=rng, progress=False,
    )
    # kinisi's gradient has input squared-distance / input-time units. The
    # Einstein relation in d dimensions gives D = gradient/(2d).
    result = summarize(analysis.gradient.samples / (2 * dims))
    return validate_output(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = solve(payload, args.checkout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
