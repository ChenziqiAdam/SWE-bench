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


def fixed_sparsity(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.fixed_sparsity_scientific import solve as solve_fixed_sparsity
    return solve_fixed_sparsity(case)


def fixed_sparsity_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.fixed_sparsity_core_scientific import solve as solve_fixed_sparsity_core
    return solve_fixed_sparsity_core(case)


def sobi_equity_accessibility(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.sobiEquity_scientific import solve as solve_sobi_equity
    return solve_sobi_equity(case)


def sobi_equity_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.sobiEquity_core_scientific import solve as solve_sobi_equity_core
    return solve_sobi_equity_core(case)


def rational_approx_eim(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.reim_scientific import solve as solve_reim
    return solve_reim(case)


def sketch_select_arnoldi(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.ssarnoldi_scientific import solve as solve_ssarnoldi
    return solve_ssarnoldi(case)


def energy_tsa_core(case: dict[str, Any]) -> dict[str, Any]:
    from curation_tools.energy_tsa_core_scientific import solve as solve_energy_tsa_core
    return solve_energy_tsa_core(case)


SOLVERS = {
    "scibench_replication_0011_core": kinisi_core,
    "scibench_replication_0015": fixed_sparsity,
    "scibench_replication_0015_core": fixed_sparsity_core,
    "scibench_replication_0017": sobi_equity_accessibility,
    "scibench_replication_0017_core": sobi_equity_core,
    "scibench_replication_0021": rational_approx_eim,
    "scibench_replication_0022": sketch_select_arnoldi,
    "scibench_replication_0018_core": energy_tsa_core,
}


def solve(task_id: str, value: dict[str, Any]) -> dict[str, Any]:
    return SOLVERS[task_id](value)
