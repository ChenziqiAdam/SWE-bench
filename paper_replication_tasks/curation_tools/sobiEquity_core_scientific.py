"""Independent BFCA implementation from Paez, Higgins & Vivona (2019)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from sobiEquity_core_common import filtered_data, validate_case, validate_output


def solve(case: dict[str, Any]) -> dict[str, Any]:
    clean = validate_case(case)
    data = filtered_data(clean["hub_filter"])
    data["reachable"] = data["travel_time"].le(clean["threshold"]).astype(float)
    origin_denominator = data.groupby("UID", sort=False)["reachable"].transform("sum")
    hub_denominator = data.groupby("hub", sort=False)["reachable"].transform("sum")
    data = data[(origin_denominator > 0) & (hub_denominator > 0)].copy()
    data["origin_weight"] = data["reachable"] / origin_denominator[data.index]
    data["hub_weight"] = data["reachable"] / hub_denominator[data.index]

    demand = (data["population"] * data["origin_weight"]).groupby(data["hub"]).sum()
    racks = data.groupby("hub")["racks"].first()
    los = (racks / demand).sort_index()
    joined_los = data["hub"].map(los)
    accessibility = (joined_los * data["hub_weight"]).groupby(data["UID"]).sum().sort_index()
    result = {
        "hub": [int(item) for item in los.index],
        "level_of_service": [float(item) for item in los.to_numpy()],
        "population_unit": [int(item) for item in accessibility.index],
        "accessibility": [float(item) for item in accessibility.to_numpy()],
    }
    return validate_output(result)


def scientific_metrics(case: dict[str, Any]) -> dict[str, Any]:
    """Measure topology and conservation independently of serialized gold."""
    clean = validate_case(case)
    data = filtered_data(clean["hub_filter"])
    reachable = data[data["travel_time"].le(clean["threshold"])].copy()
    origin_degree = reachable.groupby("UID")["hub"].nunique()
    hub_degree = reachable.groupby("hub")["UID"].nunique()
    ow = 1.0 / reachable.groupby("UID")["hub"].transform("size")
    hw = 1.0 / reachable.groupby("hub")["UID"].transform("size")
    population_allocated = float((reachable["population"] * ow).sum())
    population_reachable = float(reachable.groupby("UID")["population"].first().sum())
    demand = (reachable["population"] * ow).groupby(reachable["hub"]).sum()
    racks = reachable.groupby("hub")["racks"].first()
    los = racks / demand
    accessibility_sum = float((reachable["hub"].map(los) * hw).sum())
    return {
        "reachable_rows": int(len(reachable)),
        "reachable_origins": int(reachable["UID"].nunique()),
        "reachable_hubs": int(reachable["hub"].nunique()),
        "max_origin_degree": int(origin_degree.max()),
        "max_hub_degree": int(hub_degree.max()),
        "overlap_rate": float(origin_degree.gt(1).mean()),
        "filtered_rows": int(len(load_all()) - len(data)),
        "filtered_hubs": int(load_all()["hub"].nunique() - data["hub"].nunique()),
        "unreachable_origins": int(data["UID"].nunique() - reachable["UID"].nunique()),
        "unreachable_hubs": int(data["hub"].nunique() - reachable["hub"].nunique()),
        "origin_weight_max_error": float(np.abs(reachable.assign(w=ow).groupby("UID")["w"].sum() - 1).max()),
        "hub_weight_max_error": float(np.abs(reachable.assign(w=hw).groupby("hub")["w"].sum() - 1).max()),
        "population_conservation_error": abs(population_allocated - population_reachable),
        "service_conservation_error": abs(accessibility_sum - float(los.sum())),
    }


def load_all() -> pd.DataFrame:
    from sobiEquity_core_common import load_fixture
    return load_fixture()
