"""Shared schema and archived-data checks for the BFCA-only 0017 core task."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import pandas as pd

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures/sobi_equity_ttm.csv"
FIXTURE_SHA256 = "b5ae188e25523f62d8bd2b064c7cdeeb207d023fb8b9b378143e980de96ec452"
FILTERS = {"conventional_active", "all_active"}


def validate_case(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"threshold", "hub_filter"}:
        raise ValueError("case must contain exactly threshold and hub_filter")
    threshold = value["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be numeric")
    if not math.isfinite(threshold) or threshold <= 0 or threshold > 30:
        raise ValueError("threshold must be finite and in (0, 30]")
    if value["hub_filter"] not in FILTERS:
        raise ValueError("unknown hub_filter")
    return {"threshold": float(threshold), "hub_filter": value["hub_filter"]}


def load_fixture() -> pd.DataFrame:
    if not FIXTURE_PATH.is_file() or hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError("archived travel-time matrix is missing or changed")
    return pd.read_csv(FIXTURE_PATH)


def filtered_data(hub_filter: str) -> pd.DataFrame:
    data = load_fixture()
    data = data[data["hub_status"].eq("Active")]
    if hub_filter == "conventional_active":
        data = data[data["hub_type"].eq("Conventional")]
    elif hub_filter != "all_active":
        raise ValueError("unknown hub_filter")
    return data.copy()


def validate_output(value: Any) -> dict[str, Any]:
    required = {"hub", "level_of_service", "population_unit", "accessibility"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("output fields do not match contract")
    if len(value["hub"]) != len(value["level_of_service"]):
        raise ValueError("hub output lengths differ")
    if len(value["population_unit"]) != len(value["accessibility"]):
        raise ValueError("population output lengths differ")
    if value["hub"] != sorted(value["hub"]) or value["population_unit"] != sorted(value["population_unit"]):
        raise ValueError("identifiers must be sorted")
    if len(set(value["hub"])) != len(value["hub"]) or len(set(value["population_unit"])) != len(value["population_unit"]):
        raise ValueError("identifiers must be unique")
    if any(isinstance(item, bool) or not isinstance(item, int) for key in ("hub", "population_unit") for item in value[key]):
        raise ValueError("identifiers must be integers")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
           for key in ("level_of_service", "accessibility") for item in value[key]):
        raise ValueError("numeric outputs must be finite")
    return value
