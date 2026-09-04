#!/usr/bin/env python3
"""Execute the pinned notebook kernel with only its Gaussian draw injected."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from fixed_sparsity_core_common import validate_case

COMMIT = "6da600d95dbcf8a2f6f8424432601e31a243ba5e"
NOTEBOOK_SHA256 = "2b89484a821498766daed105a29ca09ceebd137c661d1c284f4568e162c3cd99"
ORIGINAL = "def sparse_recovery(A,S,m):"
PATCHED = "def sparse_recovery(A,S,m,G):"
DRAW_ORIGINAL = "    G = np.random.randn(d,m)"
DRAW_PATCHED = "    G = np.asarray(G, dtype=float)"
ADAPTER_PATCH = f"{ORIGINAL}\n{DRAW_ORIGINAL}\n=>\n{PATCHED}\n{DRAW_PATCHED}\n"
PATCH_SHA256 = hashlib.sha256(ADAPTER_PATCH.encode()).hexdigest()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def notebook_kernel(checkout: Path):
    if subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip() != COMMIT:
        raise ValueError("checkout commit mismatch")
    if subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip():
        raise ValueError("checkout is dirty")
    notebook_path = checkout / "sparse_recovery.ipynb"
    if digest(notebook_path) != NOTEBOOK_SHA256:
        raise ValueError("notebook hash mismatch")
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    source = next(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code" and ORIGINAL in "".join(cell.get("source", []))
    )
    if source.count(ORIGINAL) != 1 or source.count(DRAW_ORIGINAL) != 1:
        raise ValueError("official kernel no longer matches the audited patch")
    source = source.replace(ORIGINAL, PATCHED).replace(DRAW_ORIGINAL, DRAW_PATCHED)
    namespace = {"np": np}
    exec(compile(source, "sparse_recovery.ipynb", "exec"), namespace)
    return namespace["sparse_recovery"]


def solve(value, checkout: Path):
    matrix, mask, sketch = validate_case(value)
    result = notebook_kernel(checkout)(matrix, mask, sketch.shape[1], sketch)
    if result.shape != matrix.shape or not np.isfinite(result).all():
        raise ValueError("official kernel returned invalid output")
    return {"A_tilde": result.tolist()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["0015_core"], required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    result = solve(value, args.checkout)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "output.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
