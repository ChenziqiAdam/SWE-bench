"""Independent, solver-neutral audit of the a-posteriori (D-F) aggregation pipeline for
task 0016 (a_posteriori_tsa_storage). Reimplements the paper's deterministic
stratify -> normalize -> cluster -> representative-day pipeline (`aggregation.py` at commit
c162068f61bafbe640bbd40ee4a47312498ed153) from the base time series and the official operate
variables, and checks it reproduces the same day-to-representative-day cluster assignment that
Calliope's `get_design_estimate` solve actually used. This audits the paper's core algorithmic
contribution without re-solving the CBC MILP (solver-neutral).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn.cluster

TS_BASE_ROLL_DAYS = 184
TS_BASE_FIRST_YEAR = 1980
CLUSTERING_COLUMNS = [
    "demand_region2", "demand_region4", "demand_region5",
    "wind_region2", "wind_region5", "wind_region6",
]
STORAGE_CLUSTERING_COLUMNS = ["gen_storage_region2", "gen_storage_region5", "gen_storage_region6"]
NUM_DAYS = 30
TS_AGG_SPLIT_EXTREME = 0.5
TS_BASE_SPLIT_EXTREME = 0.05

# Method -> (stratification column or None, extra clustering columns, aggfunc)
METHOD_SPEC = {
    "A": {"stratify": None, "clustering_extra": [], "representative_day": "mean"},
    "B": {"stratify": None, "clustering_extra": [], "representative_day": "closest"},
    "C": {"stratify": "max_demand_min_wind", "clustering_extra": [], "representative_day": "closest"},
    "D": {"stratify": "gen_unmet_total", "clustering_extra": [], "representative_day": "closest"},
    "E": {"stratify": "generation_cost", "clustering_extra": [], "representative_day": "closest"},
    "F": {"stratify": "generation_cost", "clustering_extra": STORAGE_CLUSTERING_COLUMNS, "representative_day": "closest"},
}


def _base_time_series(raw_csv: Path, years: list[int]) -> pd.DataFrame:
    """Reconstruct the exact base 3-year resampled, rolled time series `get_base_time_series`
    builds from `data/demand_wind_solar.csv` for the given (already MT19937-resampled) years."""
    ts_data = pd.read_csv(raw_csv, index_col=0)
    ts_data = ts_data.clip(lower=0.0)
    ts_data.index = pd.to_datetime(ts_data.index)
    ts_data = ts_data.drop(columns=[column for column in ts_data.columns if "solar" in column])

    resampled = pd.concat([ts_data.loc[ts_data.index.year == year] for year in years])
    resampled.index = pd.date_range(start="2021-01-01", periods=resampled.shape[0], freq="h")

    rolled_values = np.roll(resampled.to_numpy(), 24 * TS_BASE_ROLL_DAYS, axis=0)
    rolled_index = (
        pd.date_range(start="2021-01-01", periods=resampled.shape[0], freq="h")
        - pd.Timedelta(TS_BASE_ROLL_DAYS, unit="d")
    )
    return pd.DataFrame(data=rolled_values, index=rolled_index, columns=resampled.columns)


def _daily_vectors(ts_hourly: pd.DataFrame) -> pd.DataFrame:
    if ts_hourly.shape[0] % 24 != 0:
        raise ValueError("time series must have 24 values per day")
    num_days = ts_hourly.shape[0] // 24
    daily_index = ts_hourly.resample("D").first().index
    daily_columns = [f"{column}_{hour:02d}" for column in ts_hourly.columns for hour in range(24)]
    daily = pd.DataFrame(index=daily_index, columns=daily_columns, dtype="float")
    for i, column in enumerate(ts_hourly.columns):
        daily.iloc[:, 24 * i:24 * (i + 1)] = ts_hourly[column].to_numpy().reshape(num_days, -1)
    return daily


def _normalize_z(ts_data: pd.DataFrame, exclude: list[str]) -> pd.DataFrame:
    ts_data = ts_data.copy()
    for column in [c for c in ts_data.columns if c not in exclude]:
        if ts_data[column].std() < 1e-5:
            ts_data[column] = 0.0
            continue
        mean, std = ts_data[column].mean(), ts_data[column].std()
        ts_data[column] = (ts_data[column] - mean) / std
    return ts_data


def _stratify_extreme_days(daily: pd.DataFrame, column: str | None) -> pd.Series:
    """Return the `is_extreme_day` Boolean series (index = daily) for a given stratification
    column, mirroring `aggregation.add_is_extreme_day_flag`."""
    if column is None:
        return pd.Series(False, index=daily.index)
    if column == "max_demand_min_wind":
        columns_max = ["demand_region2", "demand_region4", "demand_region5"]
        columns_min = ["wind_region2", "wind_region5", "wind_region6"]
        extreme_days = []
        for base_column in columns_max:
            extreme_days.append(daily.filter(regex=f"^{base_column}_\\d{{2}}", axis=1).max(axis=1).idxmax())
        for base_column in columns_min:
            extreme_days.append(daily.filter(regex=f"^{base_column}_\\d{{2}}", axis=1).min(axis=1).idxmin())
        extreme_days = sorted(set(extreme_days))
        return daily.index.isin(extreme_days)

    aggfunc = "sum"
    if f"{column}_00" not in daily.columns:
        raise ValueError(f"stratification column `{column}` not present in daily vectors")
    ranking = daily.filter(regex=f"^{column}_\\d{{2}}$", axis=1).apply(aggfunc, axis=1)
    ranks = ranking.rank(method="first", ascending=False).astype("int")
    num_extreme = round(TS_BASE_SPLIT_EXTREME * daily.shape[0])
    if column == "gen_unmet_total":
        has_unmet = ranking > 0.0
        num_extreme = min(num_extreme, int(has_unmet.sum()))
    return ranks <= num_extreme


def _cluster_stratified(vecs: pd.DataFrame, is_extreme: pd.Series, num_days_extreme: int, seed: int) -> pd.Series:
    num_days_regular = NUM_DAYS - num_days_extreme
    vecs_extreme = vecs.loc[is_extreme]
    vecs_regular = vecs.loc[~is_extreme]

    if num_days_extreme > 0:
        clusterer = sklearn.cluster.AgglomerativeClustering(n_clusters=num_days_extreme)
        labels_extreme = clusterer.fit(vecs_extreme).labels_
    else:
        labels_extreme = np.array([], dtype=int)
    clusters_extreme = pd.Series(labels_extreme, index=vecs_extreme.index)

    clusterer = sklearn.cluster.AgglomerativeClustering(n_clusters=num_days_regular)
    labels_regular = clusterer.fit(vecs_regular).labels_ + num_days_extreme
    clusters_regular = pd.Series(labels_regular, index=vecs_regular.index)

    return pd.concat([clusters_extreme, clusters_regular]).sort_index().astype("int")


def independent_cluster_assignment(
    base_csv: Path, years: list[int], method: str, operate_ts_csv: Path | None
) -> pd.Series:
    """Reproduce the day -> cluster-index mapping method `A`-`F` assigns, given the base time
    series and (for D/E/F) the prior method-B operate run's hourly outputs. Index is the daily
    (midnight) timestamp of each day in the 3-year resampled/rolled series; values are cluster
    indices `0..NUM_DAYS-1`, matching Calliope's own `lookup_datestep_cluster` numbering
    convention (extreme-day clusters first, then regular)."""
    spec = METHOD_SPEC[method]
    ts_hourly = _base_time_series(base_csv, years)

    clustering_columns = list(CLUSTERING_COLUMNS) + list(spec["clustering_extra"])
    stratify_column = spec["stratify"]
    columns_used = clustering_columns + ([stratify_column] if stratify_column and stratify_column != "max_demand_min_wind" else [])

    ts_used = ts_hourly[[c for c in ts_hourly.columns if c in columns_used]].copy()

    missing = [c for c in columns_used if c not in ts_used.columns]
    if missing:
        if operate_ts_csv is None:
            raise ValueError(f"columns {missing} require operate variables but none supplied")
        operate = pd.read_csv(operate_ts_csv, index_col=0)
        operate.index = pd.to_datetime(operate.index)
        if "gen_unmet_total" in missing:
            unmet_regions = operate.filter(regex=r"^gen_unmet_region\d$", axis=1)
            operate = operate.copy()
            operate["gen_unmet_total"] = unmet_regions.sum(axis=1)
        common = [c for c in ts_used.columns if c in operate.columns]
        if not common or not (operate.index[: len(ts_used)] == ts_used.index).all():
            raise ValueError("operate variable index does not align with base time series")
        for column in missing:
            if column not in operate.columns:
                raise ValueError(f"operate variables missing required column `{column}`")
            ts_used[column] = operate[column].to_numpy()[: len(ts_used)]

    exclude_from_normalize = [stratify_column] if stratify_column and stratify_column != "max_demand_min_wind" else []
    ts_used = _normalize_z(ts_used, exclude=exclude_from_normalize)

    daily = _daily_vectors(ts_used)
    is_extreme = _stratify_extreme_days(daily, stratify_column)
    is_extreme = pd.Series(np.asarray(is_extreme), index=daily.index)

    if stratify_column and stratify_column != "max_demand_min_wind" and stratify_column not in clustering_columns:
        daily = daily.drop(columns=[c for c in daily.columns if c.startswith(f"{stratify_column}_")])

    num_days_extreme = 6 if stratify_column == "max_demand_min_wind" else (
        round(TS_AGG_SPLIT_EXTREME * NUM_DAYS) if stratify_column else 0
    )
    num_days_extreme = min(num_days_extreme, int(is_extreme.sum())) if stratify_column else 0

    clusters = _cluster_stratified(daily, is_extreme, num_days_extreme, seed=0)
    return clusters


def compare_cluster_assignments(independent: pd.Series, official: pd.Series) -> dict[str, Any]:
    """Compare two day -> cluster-index Series up to a relabeling of cluster indices (cluster
    numbering is an implementation detail of `AgglomerativeClustering`'s internal tree traversal,
    not part of the paper's claims): two assignments are equivalent if they induce the same
    partition of days into groups. Returns whether they match and the adjusted Rand index."""
    from sklearn.metrics import adjusted_rand_score

    if list(independent.index) != list(official.index):
        raise ValueError("cluster assignment indices differ")
    independent_partition = [tuple(sorted(independent.index[independent.to_numpy() == label])) for label in sorted(set(independent))]
    official_partition = [tuple(sorted(official.index[official.to_numpy() == label])) for label in sorted(set(official))]
    exact_match = sorted(independent_partition) == sorted(official_partition)
    rand_index = float(adjusted_rand_score(official.to_numpy(), independent.to_numpy()))
    return {"exact_partition_match": exact_match, "adjusted_rand_index": rand_index}
