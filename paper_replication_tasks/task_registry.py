"""Authoritative v4 task lifecycle and pinned official sources."""

from __future__ import annotations

TASK_REGISTRY = {
    "scibench_replication_0007": {"status": "validated", "repository": "https://github.com/arm61/linearization-issues", "commit": "eb4dd97c3b4d04f43d8e5c9a402aa63a9e532406", "environment_file": "environment.yml", "official_adapter": "parameterized src/scripts/ols.py and wls.py with plotting disabled", "functional_target": "simulate first-order kinetics and compare linear OLS, transformed WLS, and nonlinear fits"},
    "scibench_replication_0008": {"status": "validated", "repository": "https://github.com/stonerlab/PIQSD-SingleSpinBz", "commit": "5697c290660572012c59c579ca4b99feafd159b8", "environment_file": "environment.yml", "official_adapter": "python/analytic.py functions with JSON temperature/spin injection", "functional_target": "evaluate quantum and classical finite-temperature spin expectation curves"},
    "scibench_replication_0009": {"status": "validated", "repository": "https://github.com/andgoldschmidt/biDMD-for-quantum", "commit": "8678a7ae99b66554654e13ec5ec0075607c2f44b", "environment_file": None, "curator_environment_file": "curation_tools/environments/0009-environment.yml", "dependency_artifact_sha256": "f39934ba350284aa2850e90922debcba6eca62c30526fd6af5e54800c0167875", "adapter_path": "curation_tools/core_method_adapter.py", "official_adapter": "dmdlab 0.1.1 exact-DMD kernel with generalized JSON snapshot blocks", "functional_target": "fit a truncated exact-DMD operator to snapshot blocks and extrapolate"},
    "scibench_replication_0010": {"status": "retired", "reason": "reserved identifier retired during prior curation"},
    "scibench_replication_0011": {"status": "validated", "repository": "https://github.com/arm61/msd-errors", "commit": "9141e4edcddc386cdf10a9201d70aba1abaeb66c", "environment_file": "environment.yml", "official_adapter": "walk(), get_disp3d(), and glswlsols.py regression block with JSON sizes/seeds", "functional_target": "generate seeded lattice random walks and estimate ensemble MSD and diffusion"},
    "scibench_replication_0012": {"status": "validated", "repository": "https://github.com/stonerlab/PIQSD-SingleSpinAnisotropy", "commit": "ba6f6cbbc665ea55e48f852b2205fda07f0f760e", "environment_file": "environment.yml", "adapter_path": "curation_tools/core_method_adapter.py", "official_adapter": "python/analytic.py exact Hamiltonian and field functions with dimensionless JSON grids", "functional_target": "evaluate the exact anisotropic coherent-state effective Hamiltonian and field"},
    "scibench_replication_0013": {"status": "validated", "repository": "https://github.com/zechnerlab/conditional-moment-generation", "commit": "87927c5d532b962cb4c633325ececabde9e63543", "environment_file": "requirements.txt", "curator_environment_file": "curation_tools/environments/0013-environment.yml", "adapter_path": "curation_tools/conditional_moment_adapter.py", "compatibility_patch_path": "curation_tools/patches/0013-sympy-integer.patch", "official_adapter": "patched official symbolic kernel with canonical Laurent JSON normalization and fixed-event DOP853 integration", "functional_target": "generate closed conditional moment equations and integrate them along a fixed selected-reaction trajectory"},
    "scibench_replication_0014": {"status": "validated", "repository": "https://github.com/LinkaiMa/SMW", "commit": "05c0aeff63094a1acc356ec8ebc320d826900040", "environment_file": None, "curator_environment_file": "curation_tools/environments/0014-environment.yml", "adapter_path": "curation_tools/smw_adapter.py", "official_adapter": "verbatim forward/backward compute_SMW notebook functions with controlled float64 MT19937 noise injection", "functional_target": "compute SMW approximate-inverse forward/backward errors and the paper's full and simplified bounds"},
}

CANDIDATE_REGISTRY = {}


def validated_task_ids() -> tuple[str, ...]:
    return tuple(task_id for task_id, row in TASK_REGISTRY.items() if row["status"] == "validated")


def active_task_ids() -> tuple[str, ...]:
    """Return non-retired tasks, including candidates awaiting official regeneration."""
    return tuple(task_id for task_id, row in TASK_REGISTRY.items() if row["status"] != "retired")


def select_validated(task_ids: list[str] | None = None) -> tuple[str, ...]:
    selected = validated_task_ids() if task_ids is None else tuple(task_ids)
    unknown = set(selected) - set(TASK_REGISTRY)
    invalid = [task_id for task_id in selected if task_id in TASK_REGISTRY and TASK_REGISTRY[task_id]["status"] != "validated"]
    if unknown:
        raise ValueError(f"unknown task IDs: {sorted(unknown)}")
    if invalid:
        raise ValueError(f"tasks are not validated: {invalid}")
    return selected
