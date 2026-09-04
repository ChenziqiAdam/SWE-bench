"""Independent SciPy implementation of the paper's two-stage six-region framework."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

try:
    from .energy_tsa_core_common import aggregate, validate_case
except ImportError:
    from energy_tsa_core_common import aggregate, validate_case

# Regions are zero based. Input columns are demand at 2/4/5, then wind at 2/5/6.
THERMAL_NODES = np.array([0, 2, 5, 0, 2, 5])
WIND_NODES = np.array([1, 4, 5])
STORAGE_NODES = np.array([1, 4, 5])
DEMAND_NODES = np.array([1, 3, 4])
EDGES = ((0, 1), (0, 4), (0, 5), (1, 2), (2, 3), (3, 4), (4, 5))
CAP_COST = np.array([
    300.1, 300.3, 300.6, 100.1, 100.3, 100.6,
    100.2, 100.5, 100.6, 1.002, 1.005, 1.006,
    100.12, 150.15, 100.16, 100.23, 100.34, 100.45, 100.56,
])
GEN_COST = np.array([.005001, .005003, .005006, .035001, .035003, .035006,
                     .000002, .000005, .000006])
EFF = np.array([.95002, .95005, .95006])
LOSS = .99999
CAP_COUNT = 19
HOUR_VARS = 28  # thermal 6, wind 3, charge 3, discharge 3, soc 3, flow 7, unmet 3


@dataclass
class Dispatch:
    capacities: np.ndarray
    unmet: np.ndarray
    generation_cost: np.ndarray
    storage_net: np.ndarray


def _solve_lp(
    series: np.ndarray,
    fixed: np.ndarray | None = None,
    labels: np.ndarray | None = None,
) -> Dispatch:
    clustered = labels is not None
    if clustered:
        labels = np.asarray(labels, dtype=int)
        if fixed is not None or labels.shape != (series.shape[0],):
            raise ValueError("cluster labels differ")
        first = np.asarray([np.flatnonzero(labels == i)[0] for i in range(labels.max() + 1)])
        model_series = series[first]
        hour_weights = np.repeat(np.bincount(labels), 24)
    else:
        model_series = series
        hour_weights = np.ones(model_series.shape[0] * 24)
    hours = model_series.reshape(-1, 6)
    t_count = hours.shape[0]
    day_count = series.shape[0] if clustered else 0
    inter_base = CAP_COUNT + HOUR_VARS * t_count
    size = inter_base + 3 * day_count
    c = np.zeros(size)
    if fixed is None:
        # Calliope annualises investment cost to the fraction of a model year
        # represented by the weighted timesteps. Variable costs retain their
        # timestep weights, so both terms cover the same modeled duration.
        c[:CAP_COUNT] = CAP_COST * (float(hour_weights.sum()) / 8760.0)
    rows_eq: list[int] = []; cols_eq: list[int] = []; data_eq: list[float] = []; b_eq: list[float] = []
    rows_ub: list[int] = []; cols_ub: list[int] = []; data_ub: list[float] = []; b_ub: list[float] = []
    bounds: list[tuple[float | None, float | None]] = [(0, None)] * size
    if fixed is not None:
        for j, value in enumerate(fixed): bounds[j] = (float(value), float(value))

    def v(t: int, offset: int) -> int: return CAP_COUNT + HOUR_VARS * t + offset
    def inter(day: int, store: int) -> int: return inter_base + 3 * day + store
    def eq(items: list[tuple[int, float]], rhs: float) -> None:
        row = len(b_eq); b_eq.append(float(rhs))
        for col, value in items: rows_eq.append(row); cols_eq.append(col); data_eq.append(value)
    def ub(items: list[tuple[int, float]], rhs: float) -> None:
        row = len(b_ub); b_ub.append(float(rhs))
        for col, value in items: rows_ub.append(row); cols_ub.append(col); data_ub.append(value)

    for t, raw in enumerate(hours):
        demand, wind = raw[:3], raw[3:]
        # Generation and unmet operating costs. Unmet is disabled in planning.
        c[[v(t, j) for j in range(9)]] = GEN_COST * hour_weights[t]
        c[[v(t, 25 + j) for j in range(3)]] = (
            6.000002 + np.arange(3) * .000001
        ) * hour_weights[t]
        for j in range(6): ub([(v(t, j), 1), (j, -1)], 0)
        for j in range(3): ub([(v(t, 6 + j), 1), (6 + j, -float(wind[j]))], 0)
        for j in range(3):
            bounds[v(t, 9 + j)] = (0, 100.0)
            bounds[v(t, 12 + j)] = (0, 100.0)
            if clustered:
                bounds[v(t, 15 + j)] = (None, None)
                prior = [] if t % 24 == 0 else [(v(t - 1, 15 + j), -LOSS)]
            else:
                ub([(v(t, 15 + j), 1), (9 + j, -1)], 0)
                prior = [] if t == 0 else [(v(t - 1, 15 + j), -LOSS)]
            eq([(v(t, 15 + j), 1), *prior, (v(t, 9 + j), -EFF[j]),
                (v(t, 12 + j), 1 / EFF[j])], 0)
        for e in range(7):
            bounds[v(t, 18 + e)] = (None, None)
            ub([(v(t, 18 + e), 1), (12 + e, -1)], 0)
            ub([(v(t, 18 + e), -1), (12 + e, -1)], 0)
        for node in range(6):
            items: list[tuple[int, float]] = []
            for j in np.flatnonzero(THERMAL_NODES == node): items.append((v(t, int(j)), 1))
            for j in np.flatnonzero(WIND_NODES == node): items.append((v(t, 6 + int(j)), 1))
            for j in np.flatnonzero(STORAGE_NODES == node):
                items.extend(((v(t, 12 + int(j)), 1), (v(t, 9 + int(j)), -1)))
            for e, (left, right) in enumerate(EDGES):
                if node == left: items.append((v(t, 18 + e), -1))
                elif node == right: items.append((v(t, 18 + e), 1))
            rhs = 0.0
            where = np.flatnonzero(DEMAND_NODES == node)
            if where.size:
                j = int(where[0]); rhs = float(demand[j]); items.append((v(t, 25 + j), 1))
                if fixed is None: bounds[v(t, 25 + j)] = (0, 0)
            else:
                # There is no unmet technology at non-demand nodes.
                pass
            eq(items, rhs)

    if clustered:
        decay_day = LOSS ** 24
        for day in range(day_count):
            cluster = int(labels[day])
            for j in range(3):
                if day == 0:
                    eq([(inter(day, j), 1)], 0)
                else:
                    previous_cluster = int(labels[day - 1])
                    previous_last_hour = 24 * previous_cluster + 23
                    eq([
                        (inter(day, j), 1),
                        (inter(day - 1, j), -decay_day),
                        (v(previous_last_hour, 15 + j), -1),
                    ], 0)
                for hour in range(24):
                    intra = v(24 * cluster + hour, 15 + j)
                    ub([(inter(day, j), 1), (intra, 1), (9 + j, -1)], 0)
                    ub([(inter(day, j), -decay_day), (intra, -1)], 0)

    A_eq = coo_matrix((data_eq, (rows_eq, cols_eq)), shape=(len(b_eq), size)).tocsr()
    A_ub = coo_matrix((data_ub, (rows_ub, cols_ub)), shape=(len(b_ub), size)).tocsr()
    result = linprog(c, A_ub=A_ub, b_ub=np.asarray(b_ub), A_eq=A_eq, b_eq=np.asarray(b_eq),
                     bounds=bounds, method="highs", options={"presolve": True})
    if not result.success:
        raise RuntimeError(f"energy optimization failed: {result.message}")
    solution = result.x
    unmet = np.column_stack([[solution[v(t, 25 + j)] for t in range(t_count)] for j in range(3)])
    generation = np.column_stack([[solution[v(t, j)] for t in range(t_count)] for j in range(9)])
    storage = np.column_stack([[solution[v(t, 12 + j)] - solution[v(t, 9 + j)]
                                for t in range(t_count)] for j in range(3)])
    generation_cost = generation @ GEN_COST + unmet @ (6.000002 + np.arange(3) * .000001)
    return Dispatch(solution[:CAP_COUNT], unmet, generation_cost, storage)


def solve(case: dict[str, Any], diagnostics: bool = False) -> dict[str, Any]:
    x, n, p, q = validate_case(case)
    preliminary_series, preliminary_labels, preliminary_reps, preliminary_weights = aggregate(x, n)
    preliminary = _solve_lp(preliminary_series, labels=preliminary_labels)
    fixed_capacities = np.round(preliminary.capacities, 6)
    fixed_capacities[fixed_capacities < .0001] = .0001
    operation = _solve_lp(x, fixed_capacities)
    operation_unmet = np.round(operation.unmet, 3)
    operation_generation_cost = np.round(operation.generation_cost, 3)
    operation_storage = np.round(operation.storage_net, 3)
    if q == 0:
        importance = operation_unmet.sum(axis=1).reshape(x.shape[0], 24).sum(axis=1)
        storage_features = None
    else:
        importance = operation_generation_cost.reshape(x.shape[0], 24).sum(axis=1)
        storage_features = operation_storage.reshape(x.shape[0], 24, 3) if q == 2 else None
    final_series, labels, reps, weights = aggregate(x, n, importance, p, storage_features)
    final = _solve_lp(final_series, labels=labels)
    capacities = final.capacities
    y = [capacities[:3].sum(), capacities[3:6].sum(), capacities[6:9].sum(),
         capacities[9:12].sum(), capacities[12:19].sum()]
    values = np.asarray(y, dtype=float)
    if not np.isfinite(values).all(): raise RuntimeError("non-finite result")
    result = {"y": values.tolist(), "z": labels.tolist(), "r": reps.tolist(), "w": weights.tolist()}
    if diagnostics:
        preliminary_capacities = preliminary.capacities
        result["diagnostics"] = {
            "preliminary": {
                "z": preliminary_labels.tolist(),
                "r": preliminary_reps.tolist(),
                "w": preliminary_weights.tolist(),
                "capacities": preliminary_capacities.tolist(),
                "totals": [
                    float(preliminary_capacities[:3].sum()),
                    float(preliminary_capacities[3:6].sum()),
                    float(preliminary_capacities[6:9].sum()),
                    float(preliminary_capacities[9:12].sum()),
                    float(preliminary_capacities[12:19].sum()),
                ],
            },
            "operation": {
                "unmet_daily": operation_unmet.sum(axis=1).reshape(x.shape[0], 24).sum(axis=1).tolist(),
                "generation_cost_daily": operation_generation_cost.reshape(x.shape[0], 24).sum(axis=1).tolist(),
                "storage_net": operation_storage.tolist(),
            },
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    result = solve(json.loads(args.input.read_text()), diagnostics=args.diagnostics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
