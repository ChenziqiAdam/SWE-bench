#!/usr/bin/env python3
"""Exact DMD replication for scibench_replication_0009.

Implements the paper's generalized exact-DMD core method:
  1. Pair adjacent snapshot columns within every block and concatenate those
     pairs across blocks to form the snapshot matrices X1 and X2.
  2. Fit an exact DMD model truncated to `dmd_rank` via the projected
     (reduced) operator Atilde = U^T X2 V S^{-1}.
  3. Return the projected DMD eigenvalues as unordered [real, imaginary] pairs.
  4. Extrapolate from the final snapshot of the final block at discrete times
     1..prediction_steps, returning a finite real array of shape
     state_dimension x prediction_steps.
"""
import argparse
import json
import os

import numpy as np


def exact_dmd(snapshot_blocks, dmd_rank, prediction_steps):
    """Run rank-truncated exact DMD and return (eigenvalues, prediction)."""

    # ------------------------------------------------------------------
    # Build X1 and X2: for every block, pair adjacent columns and
    # concatenate those pairs across blocks.
    # ------------------------------------------------------------------
    x1_parts = []
    x2_parts = []
    for block in snapshot_blocks:
        b = np.asarray(block, dtype=float)
        if b.shape[1] < 2:
            # A block with fewer than two snapshots contributes no pairs.
            continue
        x1_parts.append(b[:, :-1])   # columns 1 .. S-1
        x2_parts.append(b[:, 1:])    # columns 2 .. S

    if not x1_parts:
        raise ValueError("snapshot_blocks contain no adjacent snapshot pairs")

    x1 = np.hstack(x1_parts)
    x2 = np.hstack(x2_parts)

    # ------------------------------------------------------------------
    # Rank-truncated exact DMD.
    # ------------------------------------------------------------------
    rank = int(min(dmd_rank, min(x1.shape)))
    if rank < 1:
        raise ValueError("dmd_rank must be at least 1")

    u, s, vt = np.linalg.svd(x1, full_matrices=False)
    ur = u[:, :rank]
    sr = s[:rank]
    vr = vt[:rank].T

    # Projected (reduced) operator: Atilde = U^T X2 V S^{-1}.
    atilde = (ur.T @ x2) @ (vr @ np.diag(1.0 / sr))

    # Eigendecomposition of the projected operator.
    lam, w = np.linalg.eig(atilde)

    # Exact DMD modes in the original state space.
    phi = x2 @ vr @ np.diag(1.0 / sr) @ w

    # ------------------------------------------------------------------
    # Extrapolation from the final snapshot of the final block.
    # ------------------------------------------------------------------
    x0 = np.asarray(snapshot_blocks[-1], dtype=float)[:, -1]

    # Amplitudes of the initial condition in the DMD-mode basis.
    b = np.linalg.lstsq(phi, x0, rcond=None)[0]

    n_state = x0.shape[0]
    pred = np.zeros((n_state, prediction_steps))
    for k in range(prediction_steps):
        # Time index k+1 (the first predicted point is one step past x0).
        pred[:, k] = (phi @ np.diag(lam ** (k + 1)) @ b).real

    # ------------------------------------------------------------------
    # Projected eigenvalues as unordered [real, imaginary] pairs.
    # Sorted deterministically (by real then imaginary part) for a stable
    # serialized ordering.
    # ------------------------------------------------------------------
    eigenvalues = [
        [float(lam[i].real), float(lam[i].imag)] for i in range(rank)
    ]
    eigenvalues.sort(key=lambda z: (z[0], z[1]))

    return eigenvalues, pred.tolist()


def main():
    parser = argparse.ArgumentParser(
        description="scibench_replication_0009: exact DMD core method"
    )
    parser.add_argument("--input", required=True,
                        help="path to input.json")
    parser.add_argument("--output", required=True,
                        help="directory to write output.json into")
    args = parser.parse_args()

    with open(args.input, "r") as f:
        data = json.load(f)

    eigenvalues, prediction = exact_dmd(
        data["snapshot_blocks"],
        data["dmd_rank"],
        data["prediction_steps"],
    )

    result = {
        "eigenvalues": eigenvalues,
        "prediction": prediction,
    }

    os.makedirs(args.output, exist_ok=True)
    with open(os.path.join(args.output, "output.json"), "w") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
