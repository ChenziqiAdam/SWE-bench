"""Independent scientific implementations for retained v4 task auditing."""

from __future__ import annotations

from typing import Any

import numpy as np


def _finite(values: np.ndarray) -> list[float]:
    if not np.isfinite(values).all():
        raise ValueError("scientific calculation produced non-finite values")
    return values.astype(float).tolist()


def kinisi_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.kinisi_core_scientific import solve as solve_kinisi_core
    return solve_kinisi_core(case)


def fixed_sparsity_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.fixed_sparsity_core_scientific import solve as solve_fixed_sparsity_core
    return solve_fixed_sparsity_core(case)


def sobi_equity_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.sobiEquity_core_scientific import solve as solve_sobi_equity_core
    return solve_sobi_equity_core(case)


def energy_tsa_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.energy_tsa_core_scientific import solve as solve_energy_tsa_core
    return solve_energy_tsa_core(case)


def random_time_shift_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.rts_core_scientific import solve as solve_random_time_shift_core
    return solve_random_time_shift_core(case)


SOLVERS = {
    "scibench_replication_0011_core": kinisi_core,
    "scibench_replication_0015_core": fixed_sparsity_core,
    "scibench_replication_0017_core": sobi_equity_core,
    "scibench_replication_0018_core": energy_tsa_core,
    "scibench_replication_0023_core": random_time_shift_core,
}


def solve(task_id: str, value: dict[str, Any]) -> dict[str, Any]:
    return SOLVERS[task_id](value)
