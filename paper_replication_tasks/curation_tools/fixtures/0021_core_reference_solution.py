#!/usr/bin/env python3
"""Curator reference independently implementing paper Algorithm 2.1."""

import argparse
import json
from pathlib import Path

import numpy as np

p = argparse.ArgumentParser(); p.add_argument("--input", required=True); p.add_argument("--output", required=True); a = p.parse_args()
v = json.loads(Path(a.input).read_text())
D = np.asarray(v["dictionary"], float); F = np.asarray(v["targets"], float); Q = np.asarray(v["query_dictionary"], float)
xs = [int(np.argmax(np.abs(D[:, v["initial_dictionary_index"]])))]
bs = [v["initial_dictionary_index"]]
for _ in range(1, v["order"]):
    G = D[np.ix_(xs, bs)]
    residuals = D - D[:, bs] @ np.linalg.solve(G, D[xs, :])
    bs.append(int(np.argmax(np.max(np.abs(residuals), axis=0))))
    xs.append(int(np.argmax(np.abs(residuals[:, bs[-1]]))))
G = D[np.ix_(xs, bs)]
C = np.linalg.solve(G, F[xs, :])
result = {"sample_indices": xs, "dictionary_indices": bs, "interpolation_matrix": G.tolist(), "coefficients": C.tolist(), "predictions": (Q[:, bs] @ C).tolist()}
out = Path(a.output); out.mkdir(parents=True, exist_ok=True); (out / "output.json").write_text(json.dumps(result, allow_nan=False))

