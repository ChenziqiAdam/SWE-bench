#!/usr/bin/env python3
"""Compute bike-share accessibility with the balanced FCA method."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd


DATA_FILE = "travel_time_matrix.csv"


def find_data_file() -> Path:
    """Locate the case's public travel-time matrix."""
    public_dir = os.environ.get("SCIBENCH_PUBLIC_DATA_DIR")
    candidates: list[Path] = []
    if public_dir:
        root = Path(public_dir)
        candidates.extend((root / DATA_FILE, root / "data" / DATA_FILE))

    # These fallbacks make the program directly runnable from the public bundle.
    here = Path(__file__).resolve().parent
    candidates.extend((here / "public" / "data" / DATA_FILE, here / "data" / DATA_FILE))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Could not find {DATA_FILE} in the public data directory")


def select_hubs(matrix: pd.DataFrame, hub_filter: str) -> pd.Series:
    """Translate the input's hub selection into a row mask."""
    if hub_filter == "conventional_active":
        return (matrix["hub_type"] == "Conventional") & (
            matrix["hub_status"] == "Active"
        )
    if hub_filter == "all_active":
        return matrix["hub_status"] == "Active"
    raise ValueError(f"Unsupported hub_filter: {hub_filter!r}")


def balanced_accessibility(matrix: pd.DataFrame, hub_filter: str, threshold: float) -> list[float]:
    """Apply equations (4), (5), and (8) of the bundled paper.

    The binary impedance matrix is represented by the retained rows rather than
    materialized as a dense cell-by-hub matrix.
    """
    catchment = matrix.loc[
        select_hubs(matrix, hub_filter) & (matrix["travel_time"] <= threshold)
    ].copy()
    if catchment.empty:
        return []

    # First balancing: each cell's population is divided proportionally among
    # all hubs in its catchment (w^i in the paper).
    hubs_per_cell = catchment.groupby("UID", sort=False)["hub"].transform("size")
    allocated_population = catchment["population"] / hubs_per_cell
    demand_at_hub = allocated_population.groupby(catchment["hub"], sort=False).sum()

    # Second balancing: each hub's supply is divided proportionally among all
    # cells in its catchment (w^j), then divided by that hub's balanced demand.
    cells_per_hub = catchment.groupby("hub", sort=False)["UID"].transform("size")
    contributions = (
        catchment["racks"]
        / cells_per_hub
        / catchment["hub"].map(demand_at_hub)
    )

    # sort=False retains the order of first appearance of serviced UIDs in the
    # supplied matrix, which is the public data's population-cell order.
    accessibility = contributions.groupby(catchment["UID"], sort=False).sum()
    return [float(value) for value in accessibility.to_numpy()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as input_file:
        request = json.load(input_file)

    matrix = pd.read_csv(find_data_file())
    result = {
        "accessibility": balanced_accessibility(
            matrix,
            str(request["hub_filter"]),
            float(request["threshold"]),
        )
    }

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "output.json").open("w", encoding="utf-8") as output_file:
        json.dump(result, output_file, indent=2, allow_nan=False)
        output_file.write("\n")


if __name__ == "__main__":
    main()
