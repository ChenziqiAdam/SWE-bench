"""Single registry for formal, retired, blocked, and deferred replication work."""

from __future__ import annotations


TASK_REGISTRY = {
    "scibench_replication_0007": {
        "status": "validated",
        "builder_key": "0007",
        "mask_source": "0007/*/src/tex/ms.tex",
        "source_sha256": "9a10be4dab2d2a3d4de745886bace3a90dbea6e76cf20d5054b1f6486dd1ef91",
        "validator_key": "scalar_metrics",
    },
    "scibench_replication_0008": {
        "status": "validated",
        "builder_key": "0008",
        "mask_source": "0008/manuscript.tex",
        "source_sha256": "cfed2f68d1c12dbd624f3d1d3289e55c9c1f0785d88f07c0b3108ed90c9b7c44",
        "validator_key": "curve_bundle",
    },
    "scibench_replication_0009": {
        "status": "validated",
        "builder_key": "0009",
        "mask_source": "0009/main.tex",
        "source_sha256": "5603a3809229f9da63ae390bb5f1008420e62783b9a35bc08233da3b06cc460f",
        "validator_key": "floquet_arrays",
    },
    "scibench_replication_0010": {
        "status": "retired",
        "reason": "reserved identifier retired during prior curation",
    },
    "scibench_replication_0011": {
        "status": "validated",
        "builder_key": "0011",
        "mask_source": "0011/ms.tex",
        "source_sha256": "8f28c63e9cd1e32fbe938daee122baec19cc40cc34e817f49ad4bd827165735c",
        "validator_key": "msd_ensemble",
    },
    "scibench_replication_0012": {
        "status": "validated",
        "builder_key": "0012",
        "mask_source": "0012/main1.tex",
        "source_sha256": "a95e00bcabc25f3f9fb2220c783d8194079d2a78fc0cdf2c67277f9263e11b2d",
        "validator_key": "effective_hamiltonian_core",
    },
}


CANDIDATE_REGISTRY = {
    "Ariel-Norambuena/Quantum-Dynamics-in-MATLAB": {
        "status": "deferred_pending_official_reproduction",
        "commit": "f0b375a4962342c2c56eea2974e01f6e29d9bbb0",
        "paper": "1911.04906v2",
        "report": "curation_reports/quantum_dynamics_matlab.json",
    },
    "baddoo/piDMD": {
        "status": "blocked_missing_paper_experiments",
        "commit": "743d8cbc5267799ed9f32145e2b5854f07960a20",
        "report": "curation_reports/pidmd.json",
    },
    "bio-phys/DiffusionGLS": {
        "status": "blocked_missing_paper_data",
        "commit": "6b90359f698f6e7aa212587a984aa470f835d99e",
        "report": "curation_reports/diffusiongls.json",
    },
}


def validated_task_ids() -> tuple[str, ...]:
    return tuple(
        task_id
        for task_id, record in TASK_REGISTRY.items()
        if record["status"] == "validated"
    )


def select_validated(task_ids: list[str] | None = None) -> tuple[str, ...]:
    selected = validated_task_ids() if task_ids is None else tuple(task_ids)
    unknown = set(selected) - set(TASK_REGISTRY)
    if unknown:
        raise ValueError(f"unknown task IDs: {sorted(unknown)}")
    invalid = [
        task_id
        for task_id in selected
        if TASK_REGISTRY[task_id]["status"] != "validated"
    ]
    if invalid:
        raise ValueError(f"tasks are not validated: {invalid}")
    return selected
