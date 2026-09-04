#!/usr/bin/env python3
"""Compute balanced floating-catchment accessibility for the public matrix."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd


def find_matrix() -> Path:
    """Locate the case-local public data, with a local-bundle fallback."""
    candidates: list[Path] = []
    public_dir = os.environ.get("SCIBENCH_PUBLIC_DATA_DIR")
    if public_dir:
        base = Path(public_dir)
        candidates.extend(
            [
                base / "travel_time_matrix.csv",
                base / "data" / "travel_time_matrix.csv",
                base / "public" / "data" / "travel_time_matrix.csv",
            ]
        )

    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here / "public" / "data" / "travel_time_matrix.csv",
            here / "data" / "travel_time_matrix.csv",
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Could not locate travel_time_matrix.csv")


def calculate(parameters: dict, matrix_path: Path) -> dict:
    threshold = float(parameters["threshold"])
    hub_filter = parameters["hub_filter"]

    matrix = pd.read_csv(matrix_path)
    keep = matrix["hub_status"].eq("Active") & matrix["travel_time"].le(threshold)
    if hub_filter == "conventional_active":
        keep &= matrix["hub_type"].eq("Conventional")
    elif hub_filter != "all_active":
        raise ValueError(f"Unsupported hub_filter: {hub_filter!r}")

    reachable = matrix.loc[keep].copy()
    if reachable.empty:
        return {
            "accessibility": [],
            "hub": [],
            "level_of_service": [],
            "population_unit": [],
        }

    # BFCA step 1: each population cell is divided equally among all hubs in
    # its binary travel-time catchment, preventing demand from being counted
    # more than once.
    hubs_per_population = reachable.groupby("UID")["hub"].transform("size")
    reachable["allocated_population"] = reachable["population"] / hubs_per_population
    population_at_hub = reachable.groupby("hub", sort=True)["allocated_population"].sum()
    racks_at_hub = reachable.groupby("hub", sort=True)["racks"].first()
    level_of_service = racks_at_hub / population_at_hub

    # BFCA step 2: divide each hub's level of service equally among every
    # reachable population cell, preventing supply from being counted twice.
    populations_per_hub = reachable.groupby("hub")["UID"].transform("size")
    reachable["allocated_service"] = (
        reachable["hub"].map(level_of_service) / populations_per_hub
    )
    accessibility = reachable.groupby("UID", sort=True)["allocated_service"].sum()

    return {
        "accessibility": [float(value) for value in accessibility.to_numpy()],
        "hub": [int(value) for value in level_of_service.index.to_numpy()],
        "level_of_service": [float(value) for value in level_of_service.to_numpy()],
        "population_unit": [int(value) for value in accessibility.index.to_numpy()],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as stream:
        parameters = json.load(stream)

    result = calculate(parameters, find_matrix())
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "output.json").open("w", encoding="utf-8") as stream:
        json.dump(result, stream, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
