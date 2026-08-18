"""Independent balanced/conventional floating catchment area (BFCA/2SFCA)
implementation for task 0017, written from the paper's equations
(Desjardins, Higgins & Paez 2022, Transportation Research Part D 102:103091,
Sections 3-4) rather than by reading sobiEquity's R source. Used only to
cross-check official gold in promote_official.py; never a gold generator.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures/sobi_equity_ttm.csv"
FIXTURE_SHA256 = "b5ae188e25523f62d8bd2b064c7cdeeb207d023fb8b9b378143e980de96ec452"


def _load_ttm() -> pd.DataFrame:
    import hashlib
    if not FIXTURE_PATH.is_file():
        raise RuntimeError("archived travel-time-matrix fixture is missing")
    digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    if digest != FIXTURE_SHA256:
        raise RuntimeError("archived travel-time-matrix fixture hash mismatch")
    return pd.read_csv(FIXTURE_PATH)


def _prepared(hub_filter: str) -> pd.DataFrame:
    ttm = _load_ttm()
    if hub_filter == "conventional_active":
        ttm = ttm[(ttm["hub_type"] == "Conventional") & (ttm["hub_status"] == "Active")]
    elif hub_filter == "all_active":
        ttm = ttm[ttm["hub_status"] == "Active"]
    else:
        raise ValueError("hub_filter must be conventional_active or all_active")
    return ttm.copy()


def _b2sfca(ttm: pd.DataFrame, threshold: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    ttm = ttm.copy()
    ttm["w"] = (ttm["travel_time"] <= threshold).astype(float)

    balance_by_population = ttm.groupby("UID")["w"].sum().rename("sum_b1")
    balance_by_hub = ttm.groupby("hub")["w"].sum().rename("sum_b2")

    ttm = ttm.merge(balance_by_population, on="UID").merge(balance_by_hub, on="hub")
    ttm = ttm[(ttm["sum_b1"] > 0) & (ttm["sum_b2"] > 0)]

    ttm["balanced_w1"] = ttm["w"] / ttm["sum_b1"]
    ttm["balanced_w2"] = ttm["w"] / ttm["sum_b2"]

    racks_by_hub = ttm.groupby("hub")["racks"].first()
    demand_by_hub = (ttm["population"] * ttm["balanced_w1"]).groupby(ttm["hub"]).sum()
    los = (racks_by_hub / demand_by_hub).rename("los").reset_index()

    ttm = ttm.merge(los, on="hub")
    accessibility = (ttm["los"] * ttm["balanced_w2"]).groupby(ttm["UID"]).sum().rename("accessibility").reset_index()
    return los[["hub", "los"]], accessibility


def _c2sfca(ttm: pd.DataFrame, threshold: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    ttm = ttm.copy()
    ttm["w"] = (ttm["travel_time"] <= threshold).astype(float)
    ttm = ttm[ttm["w"] > 0]

    racks_by_hub = ttm.groupby("hub")["racks"].first()
    demand_by_hub = (ttm["population"] * ttm["w"]).groupby(ttm["hub"]).sum()
    los = (racks_by_hub / demand_by_hub).rename("los").reset_index()

    ttm = ttm.merge(los, on="hub")
    accessibility = (ttm["los"] * ttm["w"]).groupby(ttm["UID"]).sum().rename("accessibility").reset_index()
    return los[["hub", "los"]], accessibility


def solve(case: dict[str, Any]) -> dict[str, Any]:
    method = case["method"]
    threshold = float(case["threshold"])
    hub_filter = case["hub_filter"]
    if method not in {"b2sfca", "c2sfca"}:
        raise ValueError("method must be b2sfca or c2sfca")
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold must be finite and positive")

    ttm = _prepared(hub_filter)
    los, accessibility = (_b2sfca if method == "b2sfca" else _c2sfca)(ttm, threshold)

    los = los.sort_values("hub")
    accessibility = accessibility.sort_values("UID")

    result = {
        "hub": [int(v) for v in los["hub"]],
        "level_of_service": [float(v) for v in los["los"]],
        "population_unit": [int(v) for v in accessibility["UID"]],
        "accessibility": [float(v) for v in accessibility["accessibility"]],
    }
    for key in ("level_of_service", "accessibility"):
        if not all(math.isfinite(value) for value in result[key]):
            raise ValueError(f"non-finite value in {key}")
    return result
