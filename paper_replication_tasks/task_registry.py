"""Authoritative v4 task lifecycle and pinned official sources."""

from __future__ import annotations

TASK_REGISTRY = {
    "scibench_replication_0010": {"status": "retired", "reason": "reserved identifier retired during prior curation"},
    "scibench_replication_0011": {"status": "validated", "repository": "https://github.com/arm61/msd-errors", "commit": "9141e4edcddc386cdf10a9201d70aba1abaeb66c", "environment_file": "environment.yml", "official_adapter": "walk(), get_disp3d(), and glswlsols.py regression block with JSON sizes/seeds", "functional_target": "generate seeded lattice random walks and estimate ensemble MSD and diffusion"},
    "scibench_replication_0014": {"status": "validated", "repository": "https://github.com/LinkaiMa/SMW", "commit": "05c0aeff63094a1acc356ec8ebc320d826900040", "environment_file": None, "curator_environment_file": "curation_tools/environments/0014-environment.yml", "adapter_path": "curation_tools/smw_adapter.py", "official_adapter": "verbatim forward/backward compute_SMW notebook functions with controlled float64 MT19937 noise injection", "functional_target": "compute SMW approximate-inverse forward/backward errors and the paper's full and simplified bounds"},
    "scibench_replication_0017_core": {"status": "validated", "repository": "https://github.com/paezha/Accessibility-Sobi-Hamilton", "commit": "80b6516acb0936a4c3e75d15fc3885f1d398021f", "environment_file": None, "curator_environment_file": "curation_tools/environments/0017-r-environment.yml", "adapter_path": "curation_tools/sobiEquity_core_adapter.py", "adapter_task_arg": "0017_core", "official_checkout_key": "0017_core", "official_adapter": "verbatim pinned sobiEquity::b2sfca() over the archived Hamilton travel-time matrix", "functional_target": "balanced floating catchment area accessibility and level of service under threshold and active-station configuration inputs"},
    "scibench_replication_0015_core": {"status": "validated", "repository": "https://github.com/tchen-research/fixed_sparsity_matrix_approximation", "commit": "6da600d95dbcf8a2f6f8424432601e31a243ba5e", "environment_file": None, "curator_environment_file": "curation_tools/environments/0015-core-environment.yml", "adapter_path": "curation_tools/fixed_sparsity_core_adapter.py", "adapter_task_arg": "0015_core", "adapter_output_is_directory": True, "official_checkout_key": "0015_core", "official_adapter": "verbatim pinned-notebook sparse_recovery kernel with only the realized Gaussian G injected from numeric input", "functional_target": "paper Section 2 core fixed-sparse-matrix approximation: shared Gaussian sketch and row-restricted least-squares recovery"},
    "scibench_replication_0019": {"status": "validated", "repository": "https://github.com/RalfZimmermannSDU/StiefelCurvatureSIMAX", "commit": "1dad75cf55f0f688d59b61e0d9a58b61779efe9f", "environment_file": None, "curator_environment_file": "curation_tools/environments/0019-octave-environment.yml", "adapter_path": "curation_tools/stiefelcurv_adapter.py", "official_adapter": "verbatim pinned seccurv_Stiefel_canon/seccurv_Stiefel_euclid/seccurv_Grassmann/seccurv_SOn MATLAB functions executed under GNU Octave on curator-constructed tangent-vector matrices", "functional_target": "sectional curvature of the Grassmann, Stiefel (canonical and Euclidean metrics), and SO(n) manifolds for a given pair of tangent-vector coordinate matrices"},
    "scibench_replication_0020": {"status": "validated", "repository": "https://github.com/paezha/covid19-environmental-correlates", "commit": "6e84cf31ef7012daa08168bcdc8315f8ca3ec7c6", "environment_file": None, "curator_environment_file": "curation_tools/environments/0020-r-environment.yml", "adapter_path": "curation_tools/covid19env_adapter.py", "official_adapter": "verbatim pinned spsur::spsurtime() panel spatial-SUR-SLM 3SLS estimation plus spsur::impactspsur() marginal-effects decomposition on the archived covid19_spain_1/provinces_spain data for the three environmental-lag specifications", "functional_target": "spatial-SUR-SLM 3SLS coefficients, spatial autoregressive parameters, equation-level/pooled R2, and LeSage-Pace direct/indirect/total marginal effects for COVID-19 incidence in coterminous Spanish provinces across three climatic-lag specifications, with and without the paper's cross-equation equality restrictions"},
    "scibench_replication_0018": {"status": "validated", "repository": "https://github.com/ahilbers/a_posteriori_tsa_storage", "commit": "c162068f61bafbe640bbd40ee4a47312498ed153", "environment_file": None, "curator_environment_file": None, "adapter_path": "curation_tools/energy_tsa_adapter.py", "official_adapter": "verbatim pinned Calliope/CBC get_design_estimate + get_operate_variables workflow (main.py) across the paper's six a priori/a posteriori time-series-aggregation methods (A-F)", "functional_target": "six-region energy-system design capacities and unserved energy under methods A-F of a-priori and storage-aware a-posteriori time series aggregation, for a given MT19937-resampled seed/year triple"},
    "scibench_replication_0021": {"status": "validated", "repository": "https://github.com/yuwenli925/REIM", "commit": "9760b18408f17d226124a93755294a95f15230f8", "environment_file": None, "curator_environment_file": "curation_tools/environments/0021-octave-environment.yml", "adapter_path": "curation_tools/reim_adapter.py", "official_adapter": "verbatim pinned REIM.m (patched only for an Octave char==string dispatch incompatibility, curation_tools/patches/0021-reim-strcmp.patch) and FEM/*.m functions executed under GNU Octave, spanning rEIM rational approximation, fractional-Laplacian P1-FEM solves, and adaptive-step BDF2 fractional-heat integration", "functional_target": "rational empirical interpolation method (rEIM) approximation of parametrized function families (power/time/exp/precon), fractional-Laplacian FEM solution error on uniform/graded meshes, and adaptive BDF2 fractional-heat-equation trajectories, spanning all seven figures and Table 1 of the paper"},
}

CANDIDATE_REGISTRY = {
    "scibench_replication_0018_core": {"status": "revise", "repository": "https://github.com/ahilbers/a_posteriori_tsa_storage", "commit": "c162068f61bafbe640bbd40ee4a47312498ed153", "environment_file": None, "curator_environment_file": None, "adapter_path": "curation_tools/energy_tsa_core_adapter.py", "official_adapter": "pinned six-region Calliope workflow generalized only by injection of x/n/p/q", "functional_target": "two-stage storage-aware a-posteriori representative-day aggregation and final capacity redesign", "promotion_blockers": ["G6", "G7"]},
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
