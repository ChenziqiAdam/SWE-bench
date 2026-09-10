"""Authoritative v4 task lifecycle and pinned official sources."""

from __future__ import annotations

TASK_REGISTRY = {
    "scibench_replication_0011_core": {"status": "validated", "repository": "https://github.com/bjmorgan/kinisi", "commit": "54f3bc4f7167d18d2f4af1008880e5bb29d99797", "environment_file": None, "curator_environment_file": "curation_tools/environments/0011-core-environment.yml", "adapter_path": "curation_tools/kinisi_core_adapter.py", "official_checkout_key": "0011_core", "official_adapter": "thin JSON adapter over pinned kinisi 1.1.0 MSDBootstrap.diffusion", "functional_target": "approximate Bayesian MSD regression with covariance reconditioning and a nonnegative diffusion posterior", "validation_waivers": ["G7_blind_implementation"]},
    "scibench_replication_0017_core": {"status": "validated", "repository": "https://github.com/paezha/Accessibility-Sobi-Hamilton", "commit": "80b6516acb0936a4c3e75d15fc3885f1d398021f", "environment_file": None, "curator_environment_file": "curation_tools/environments/0017-r-environment.yml", "adapter_path": "curation_tools/sobiEquity_core_adapter.py", "adapter_task_arg": "0017_core", "official_checkout_key": "0017_core", "official_adapter": "verbatim pinned sobiEquity::b2sfca() over the archived Hamilton travel-time matrix", "functional_target": "balanced floating catchment area accessibility and level of service under threshold and active-station configuration inputs"},
    "scibench_replication_0015_core": {"status": "validated", "repository": "https://github.com/tchen-research/fixed_sparsity_matrix_approximation", "commit": "6da600d95dbcf8a2f6f8424432601e31a243ba5e", "environment_file": None, "curator_environment_file": "curation_tools/environments/0015-core-environment.yml", "adapter_path": "curation_tools/fixed_sparsity_core_adapter.py", "adapter_task_arg": "0015_core", "adapter_output_is_directory": True, "official_checkout_key": "0015_core", "official_adapter": "verbatim pinned-notebook sparse_recovery kernel with only the realized Gaussian G injected from numeric input", "functional_target": "paper Section 2 core fixed-sparse-matrix approximation: shared Gaussian sketch and row-restricted least-squares recovery"},
    "scibench_replication_0018_core": {"status": "validated", "repository": "https://github.com/ahilbers/a_posteriori_tsa_storage", "commit": "c162068f61bafbe640bbd40ee4a47312498ed153", "environment_file": None, "curator_environment_file": None, "adapter_path": "curation_tools/energy_tsa_core_adapter.py", "official_adapter": "pinned six-region Calliope workflow generalized only by injection of x/n/p/q", "functional_target": "two-stage storage-aware a-posteriori representative-day aggregation and final capacity redesign", "validation_waivers": ["G7_blind_implementation"]},
    "scibench_replication_0021_core": {"status": "validated", "repository": "https://github.com/yuwenli925/REIM", "commit": "9760b18408f17d226124a93755294a95f15230f8", "environment_file": None, "curator_environment_file": "curation_tools/environments/0021-octave-environment.yml", "adapter_path": "curation_tools/reim_core_adapter.py", "adapter_task_arg": "0021_core", "adapter_output_is_directory": True, "official_adapter": "pinned REIM.m Algorithm 2.1 recurrence with only the sampled numerical dictionary and legal first-column tie breaker injected", "functional_target": "rEIM greedy shared-basis construction and multi-target rational interpolation"},
    "scibench_replication_0022_core": {"status": "validated", "repository": "https://github.com/simunec/sketch-select-arnoldi", "commit": "6e145837e4696bd9e26b3d6160b37f97e4188e10", "environment_file": None, "curator_environment_file": "curation_tools/environments/0022-octave-environment.yml", "adapter_path": "curation_tools/ssarnoldi_core_adapter.py", "adapter_output_is_directory": True, "official_adapter": "pinned paper_ssa_final_test1a.m sketch-and-select pinv recurrence adapted only for explicit dense numeric inputs", "functional_target": "canonical pseudoinverse sketch-and-select Arnoldi basis construction with sparse coefficient support and sketch-norm normalization"},
    "scibench_replication_0023_core": {"status": "validated", "repository": "https://github.com/djmorris7/RandomTimeShifts.jl", "commit": "baf6da64fce7489503d709a9d1bc99080c5a5aa7", "environment_file": None, "curator_environment_file": "curation_tools/environments/0023-core-environment.yml", "adapter_path": "curation_tools/rts_core_adapter.py", "adapter_output_is_directory": True, "official_adapter": "Python port of RandomTimeShifts.jl (pinned commit) used as oracle under a recorded G8 waiver", "functional_target": "random time-shift distribution of a supercritical multi-type branching process: moment engine + bounded-error Taylor LST + recursive embedded-GF contraction + concentrated-matrix-exponential inversion + multinomial moment aggregation", "validation_waivers": ["G8_oracle_validity"]},
}

CANDIDATE_REGISTRY = {}


def validated_task_ids() -> tuple[str, ...]:
    return tuple(task_id for task_id, row in TASK_REGISTRY.items() if row["status"] == "validated")


def active_task_ids() -> tuple[str, ...]:
    """Return tasks eligible for current benchmark execution."""
    return tuple(task_id for task_id, row in TASK_REGISTRY.items() if row["status"] == "validated")


def select_validated(task_ids: list[str] | None = None) -> tuple[str, ...]:
    selected = validated_task_ids() if task_ids is None else tuple(task_ids)
    unknown = set(selected) - set(TASK_REGISTRY)
    invalid = [task_id for task_id in selected if task_id in TASK_REGISTRY and TASK_REGISTRY[task_id]["status"] != "validated"]
    if unknown:
        raise ValueError(f"unknown task IDs: {sorted(unknown)}")
    if invalid:
        raise ValueError(f"tasks are not validated: {invalid}")
    return selected
