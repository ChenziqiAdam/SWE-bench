"""Authoritative v4 task lifecycle and pinned official sources."""

from __future__ import annotations

TASK_REGISTRY = {
    "scibench_replication_0010": {"status": "retired", "reason": "reserved identifier retired during prior curation"},
    "scibench_replication_0011": {"status": "validated", "repository": "https://github.com/arm61/msd-errors", "commit": "9141e4edcddc386cdf10a9201d70aba1abaeb66c", "environment_file": "environment.yml", "official_adapter": "walk(), get_disp3d(), and glswlsols.py regression block with JSON sizes/seeds", "functional_target": "generate seeded lattice random walks and estimate ensemble MSD and diffusion"},
    "scibench_replication_0014": {"status": "validated", "repository": "https://github.com/LinkaiMa/SMW", "commit": "05c0aeff63094a1acc356ec8ebc320d826900040", "environment_file": None, "curator_environment_file": "curation_tools/environments/0014-environment.yml", "adapter_path": "curation_tools/smw_adapter.py", "official_adapter": "verbatim forward/backward compute_SMW notebook functions with controlled float64 MT19937 noise injection", "functional_target": "compute SMW approximate-inverse forward/backward errors and the paper's full and simplified bounds"},
}

CANDIDATE_REGISTRY = {
    "fixed_sparsity_matrix_approximation": {
        "status": "deferred_runtime_budget",
        "repository": "https://github.com/tchen-research/fixed_sparsity_matrix_approximation",
        "commit": "6da600d95dbcf8a2f6f8424432601e31a243ba5e",
        "proposed_resources": {"case_timeout_seconds": 14400, "total_timeout_seconds": 43200, "cpus": 4, "memory_gb": 8},
        "report": "curation_reports/fixed_sparsity.json",
    },
    "a_posteriori_tsa_storage": {
        "status": "deferred_runtime_and_independent_audit",
        "repository": "https://github.com/ahilbers/a_posteriori_tsa_storage",
        "commit": "c162068f61bafbe640bbd40ee4a47312498ed153",
        "proposed_resources": {"case_timeout_seconds": 43200, "total_timeout_seconds": 259200, "cpus": 8, "memory_gb": 16},
        "report": "curation_reports/a_posteriori_tsa_storage.json",
    },
}


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
