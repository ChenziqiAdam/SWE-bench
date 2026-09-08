#!/usr/bin/env python3
"""Curator reference submission; separate from oracle and scientific audit."""

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    x = json.loads(Path(args.input).read_text())
    A = np.array(x["matrix"], float); q = np.array(x["start_vector"], float)
    S = np.array(x["sketch_matrix"], float); m = x["iterations"]; k = x["selection_budget"]
    V = np.zeros((A.shape[0], m + 1)); Y = np.zeros((S.shape[0], m + 1))
    H = np.zeros((m + 1, m)); P = np.zeros((S.shape[0], m))
    y = S @ q; scale = np.linalg.norm(y); V[:, 0] = q / scale; Y[:, 0] = y / scale
    for j in range(m):
        w = A @ V[:, j]; z = S @ w; P[:, j] = z
        c = np.linalg.pinv(Y[:, :j + 1]) @ z
        order = sorted(range(j + 1), key=lambda i: (-abs(c[i]), i))[:min(j + 1, k)]
        H[order, j] = c[order]; w -= V[:, order] @ c[order]; z -= Y[:, order] @ c[order]
        scale = np.linalg.norm(z); H[j + 1, j] = scale
        V[:, j + 1] = w / scale; Y[:, j + 1] = z / scale
    output = {"basis": V.tolist(), "hessenberg": H.tolist(), "sketched_basis": Y.tolist(), "sketched_products": P.tolist()}
    destination = Path(args.output); destination.mkdir(parents=True, exist_ok=True)
    (destination / "output.json").write_text(json.dumps(output, allow_nan=False) + "\n")


if __name__ == "__main__": main()
