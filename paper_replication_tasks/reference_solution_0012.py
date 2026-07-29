#!/usr/bin/env python3
"""Independent public-only solution for replication task 0012."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy import constants, special


TASK_ID = "scibench_replication_0012"
TEMPERATURE = np.linspace(0.02, 10.0, 200, dtype=np.float64)
ORIENTATION = np.linspace(-0.98, 0.98, 201, dtype=np.float64)
A1_OVER_KB = (
    abs(constants.value("electron g factor"))
    * constants.value("Bohr magneton")
    / constants.k
)


def calculate(spin: float, ratio: float) -> tuple[np.ndarray, np.ndarray]:
    two_s = int(round(2 * spin))
    p = np.arange(two_s + 1, dtype=np.float64)
    m = spin - p
    u = ORIENTATION
    log_probability = np.asarray(
        [
            math.log(math.comb(two_s, index))
            + index * np.log((1.0 - u) / 2.0)
            + (two_s - index) * np.log((1.0 + u) / 2.0)
            for index in range(two_s + 1)
        ]
    )
    derivative = np.asarray(
        [
            (two_s - index) / (1.0 + u) - index / (1.0 - u)
            for index in range(two_s + 1)
        ]
    )
    reference = spin + ratio * spin * spin
    h = np.empty((200, 201), dtype=np.float64)
    b = np.empty_like(h)
    for index, temperature in enumerate(TEMPERATURE):
        tau = A1_OVER_KB / temperature
        terms = log_probability + tau * (
            m + ratio * m * m - reference
        )[:, None]
        log_q = special.logsumexp(terms, axis=0)
        weight = np.exp(terms - log_q[None, :])
        h[index] = -log_q / tau
        b[index] = np.sum(weight * derivative, axis=0) / (spin * tau)
    return h, b


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    values = {"temperature": TEMPERATURE, "orientation": ORIENTATION}
    for prefix, specifications in (
        ("figure2", [(s, -2.0) for s in (0.5, 1.0, 1.5, 2.0)]),
        ("figure3", [(1.0, r) for r in (10.0, 0.0, -1.0, -10.0)]),
    ):
        rows = [calculate(*specification) for specification in specifications]
        values[f"{prefix}_hamiltonian"] = np.asarray([row[0] for row in rows])
        values[f"{prefix}_field"] = np.asarray([row[1] for row in rows])
    artifacts = []
    for artifact_id, array in values.items():
        path = output / f"{artifact_id}.npy"
        np.save(path, array, allow_pickle=False)
        artifacts.append(
            {
                "id": artifact_id,
                "path": path.name,
                "media_type": "application/x-npy",
            }
        )
    (output / "results.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": TASK_ID,
                "entrypoint": "python reference_solution_0012.py --output-dir .",
                "protocol": {},
                "checkpoints": {},
                "artifacts": artifacts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
