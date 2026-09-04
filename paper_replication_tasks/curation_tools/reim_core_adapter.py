#!/usr/bin/env python3
"""Source-faithful adapter of pinned REIM.m with its matrices injected as input.

The loop and first-occurrence tie behavior correspond directly to REIM.m at
commit 9760b184.  Only xset/bset evaluation and the fixed first bset entry are
replaced by the supplied numerical dictionary and explicit legal initial index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from reim_core_common import validate_case


def solve(value: dict) -> dict:
    order, gset, targets, query, initial = validate_case(value)
    rows, columns = gset.shape
    chosen_columns = np.zeros(order, dtype=int)
    chosen_rows = np.zeros(order, dtype=int)
    gm = np.zeros((rows, order))
    chosen_columns[0] = initial
    gm[:, 0] = gset[:, initial]
    chosen_rows[0] = int(np.argmax(np.abs(gm[:, 0])))
    G = gset[np.ix_(chosen_rows[:1], chosen_columns[:1])]
    for m in range(1, order):
        residual_norms = np.zeros(columns)
        for i in range(columns):
            rhs = gset[chosen_rows[:m], i]
            residual_norms[i] = np.linalg.norm(gset[:, i] - gm[:, :m] @ np.linalg.solve(G, rhs), ord=np.inf)
        chosen_columns[m] = int(np.argmax(residual_norms))
        gm[:, m] = gset[:, chosen_columns[m]]
        rhs = gset[chosen_rows[:m], chosen_columns[m]]
        residual = gm[:, m] - gm[:, :m] @ np.linalg.solve(G, rhs)
        chosen_rows[m] = int(np.argmax(np.abs(residual)))
        G = gset[np.ix_(chosen_rows[:m + 1], chosen_columns[:m + 1])]
    coefficients = np.linalg.solve(G, targets[chosen_rows, :])
    predictions = query[:, chosen_columns] @ coefficients
    return {
        "sample_indices": chosen_rows.tolist(),
        "dictionary_indices": chosen_columns.tolist(),
        "interpolation_matrix": G.tolist(),
        "coefficients": coefficients.tolist(),
        "predictions": predictions.tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--checkout")
    args = parser.parse_args()
    if args.checkout:
        checkout = Path(args.checkout)
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True).strip()
        source_hash = hashlib.sha256((checkout / "REIM.m").read_bytes()).hexdigest()
        if commit != "9760b18408f17d226124a93755294a95f15230f8" or dirty or source_hash != "f27dea36e57994569963d35e50b3cdc6fff4fdd872ee68018949cbd0ef97e033":
            raise RuntimeError("official checkout is not clean, pinned, and source-identical")
    value = json.loads(args.input.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    result = solve(value)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "output.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
