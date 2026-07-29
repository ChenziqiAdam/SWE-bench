#!/usr/bin/env python3
"""Validate public/private separation and frozen replication references."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from task_registry import CANDIDATE_REGISTRY, TASK_REGISTRY, validated_task_ids

ROOT = Path(__file__).resolve().parent
TASK_IDS = set(validated_task_ids())
PUBLIC_NAMES = {"task.md", "input.json", "submission_schema.json", "masked_paper.pdf"}
FORBIDDEN_PUBLIC_KEYS = {
    "repository",
    "commit",
    "official_entrypoint",
    "gold",
    "gold_output",
    "tolerances",
    "reference",
}
FORBIDDEN_PUBLIC_TEXT = (
    "github.com",
    "use the official repository",
    "fixed commit",
    "gold_output",
    "arxiv",
    "doi.org",
    "corresponding author",
    "university of washington",
    "lawrence livermore",
    "european spallation source",
    "is there still a place for linearization in the chemistry curriculum",
    "numerical simulations of a spin dynamics model based on a path integral approach",
    "bilinear dynamic mode decomposition for quantum control",
    "andrew r. mccluskey",
    "thomas nussle",
    "stam nicolis",
    "joseph barker",
    "andy goldschmidt",
    "s. l. brunton",
    "j. n. kutz",
    "path integral spin dynamics for quantum paramagnets",
    "piqsd-singlespinanisotropy",
    "thomas nussle",
    "pascal thibaudeau",
)
TASK_RESULT_LEAKS = {
    "scibench_replication_0007": (
        "1.05",
        "0.95",
        "0.76",
        "1.55",
        "0.85",
        "lin_mean_ols",
    ),
    "scibench_replication_0008": (
        "linearization-issues",
        "piqsd-singlespinbz",
        "zenodo.7692092",
    ),
    "scibench_replication_0009": (
        "1.008059",
        "0.920713",
        "0.384790",
        "0.039844",
        "0.095302",
        "bidmd-for-quantum",
        "later_model_eigenvalues",
    ),
    "scibench_replication_0011": (
        "msd-errors",
        "capturing time correlations",
        "9141e4edcddc386cdf10a9201d70aba1abaeb66c",
    ),
    "scibench_replication_0012": (
        "2404.19539",
        "11072984",
        "12638435",
        "ba6f6cbbc665ea55e48f852b2205fda07f0f760e",
        "piqsd",
    ),
}
TASKS_PROTOCOL_FIELDS = {task_id: () for task_id in TASK_IDS}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(walk_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(walk_keys(item) for item in value), set())
    return set()


def valid_pdf(path: Path) -> bool:
    data = path.read_bytes()
    return len(data) >= 64 and data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]


def main() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    masking = json.loads(
        (ROOT / "masked_paper_sources/masking_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(masking["manual_review"]["reviewed_task_ids"]) == {
        task_id.rsplit("_", 1)[-1] for task_id in TASK_IDS
    }
    assert masking["deidentification"]["document_type"] == (
        "manually_rewritten_replication_dossier"
    )
    assert manifest["schema_version"] == 3
    assert {row["task_id"] for row in manifest["tasks"]} == TASK_IDS
    for row in manifest["tasks"]:
        task_id = row["task_id"]
        task_dir = ROOT / task_id
        public = task_dir / "public"
        hidden = task_dir / "hidden"
        assert public.is_dir() and hidden.is_dir()
        assert {path.name for path in public.iterdir() if path.is_file()} == PUBLIC_NAMES
        assert not any(
            (task_dir / name).exists()
            for name in (
                "input.json",
                "gold_output.json",
                "provenance.json",
                "run_record.json",
                "task.md",
            )
        ), f"legacy mixed bundle remains in {task_id}"
        task_input = json.loads((public / "input.json").read_text(encoding="utf-8"))
        schema = json.loads(
            (public / "submission_schema.json").read_text(encoding="utf-8")
        )
        gold = json.loads((hidden / "gold_output.json").read_text(encoding="utf-8"))
        provenance = json.loads(
            (hidden / "provenance.json").read_text(encoding="utf-8")
        )
        assert task_input["schema_version"] == 3
        assert task_input["task_id"] == gold["task_id"] == provenance["task_id"] == task_id
        assert "protocol" not in task_input, (
            f"paper protocol must not be duplicated in public input for {task_id}"
        )
        assert set(task_input) <= {
            "schema_version",
            "task_id",
            "resources",
            "submission",
            "benchmark_constraints",
        }
        assert task_input["resources"] == [
            {
                "id": "masked_paper",
                "path": "masked_paper.pdf",
                "media_type": "application/pdf",
            }
        ]
        assert task_input["submission"]["protocol_fields"] == list(
            TASKS_PROTOCOL_FIELDS[task_id]
        )
        declared_artifacts = {
            item["id"]: item["media_type"]
            for item in task_input["submission"]["required_artifacts"]
        }
        assert declared_artifacts == gold["required_artifacts"]
        if task_id.endswith("0011"):
            assert set(task_input["benchmark_constraints"]) == {
                "random_number_generator",
                "seed_rule",
            }
        else:
            assert "benchmark_constraints" not in task_input
        assert schema["properties"]["task_id"]["const"] == task_id
        assert gold["scoring"] == {
            "scientific": 0.90,
            "artifacts": 0.10,
        }
        assert all(
            media_type != "application/pdf"
            for media_type in gold["required_artifacts"].values()
        )
        assert (hidden / "evaluator.py").is_file()
        assert valid_pdf(public / "masked_paper.pdf")
        curated = ROOT / "masked_paper_sources" / f"{task_id}.txt"
        assert curated.is_file()
        curated_text = curated.read_text(encoding="utf-8").lower()
        assert len(curated_text.split()) >= 300
        assert "scibench anonymized replication dossier" in curated_text
        assert "not the original paper text" in curated_text
        assert "[masked:" in curated_text
        assert not re.search(
            r"^##\s+(abstract|introduction|references|acknowledgements?)\b",
            curated_text,
            flags=re.MULTILINE,
        )
        assert not re.search(r"\\(?:cite|citep|citet|bibliography)\b", curated_text)
        for leak in TASK_RESULT_LEAKS[task_id]:
            assert leak.lower() not in curated_text, (
                f"masked manuscript leaks {leak!r} in {task_id}"
            )
        suffix = task_id.rsplit("_", 1)[-1]
        source_record = masking["sources"][suffix]
        assert source_record["verbatim_12gram_overlap"] <= 0.005
        assert digest(curated) == source_record["curated_text_sha256"]
        assert (
            digest(public / "masked_paper.pdf")
            == source_record["masked_pdf_sha256"]
        )
        public_bytes = b"\n".join(
            path.read_bytes().lower() for path in public.iterdir() if path.is_file()
        )
        public_identity_text = curated_text + "\n" + "\n".join(
            path.read_text(encoding="utf-8", errors="ignore").lower()
            for path in public.iterdir()
            if path.suffix in {".md", ".json"}
        )
        public_identity_text = re.sub(r"\s+", " ", public_identity_text)
        for phrase in FORBIDDEN_PUBLIC_TEXT:
            assert phrase.encode() not in public_bytes, (
                f"public leak {phrase!r} in {task_id}"
            )
            assert phrase not in public_identity_text, (
                f"normalized public identity leak {phrase!r} in {task_id}"
            )
        public_keys = walk_keys(task_input) | walk_keys(schema)
        assert not (FORBIDDEN_PUBLIC_KEYS & public_keys), (
            f"forbidden public keys: {FORBIDDEN_PUBLIC_KEYS & public_keys}"
        )
        assert not re.search(rb"\b[0-9a-f]{40}\b", public_bytes), (
            f"commit-like hash leaked in {task_id}"
        )
        assert not re.search(
            rb"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", public_bytes
        ), f"email-like identity leaked in {task_id}"
        for name, expected in row["public_files"].items():
            assert digest(public / name) == expected
        assert digest(hidden / "gold_output.json") == row["gold_output_sha256"]
        if task_id.endswith("0008"):
            index = gold["artifact_index"]
            assert len(index) == 23
            assert [item["id"] for item in index] == [
                f"curve_{number:02d}" for number in range(1, 24)
            ]
            for item in index:
                reference = hidden / item["reference_path"]
                assert reference.is_file()
                assert digest(reference) == item["sha256"]
                values = np.loadtxt(reference, ndmin=2)
                assert values.shape[1] == 2
                assert np.isfinite(values).all()
                assert "qsd_" not in reference.name
                assert "terms13" not in reference.name
        if task_id.endswith("0009"):
            expected_shapes = {
                "floquet_eigenvalues": (3, 2),
                "prediction_times": (32,),
                "prediction_trajectory": (3, 32),
            }
            assert set(gold["artifact_index"]) == set(expected_shapes)
            generation_path = hidden / "gold_artifacts/reference_generation.json"
            generation = json.loads(generation_path.read_text(encoding="utf-8"))
            assert generation["experiment"] == "deterministic_floquet_dmd_example_2"
            assert provenance["reference_generation"] == {
                "path": "gold_artifacts/reference_generation.json",
                "sha256": digest(generation_path),
            }
            assert (
                generation["generator_sha256"]
                == digest(ROOT / "generate_reference_0009.py")
            )
            for artifact_id, expected_shape in expected_shapes.items():
                item = gold["artifact_index"][artifact_id]
                reference = hidden / item["reference_path"]
                assert digest(reference) == item["sha256"]
                values = np.load(reference, allow_pickle=False)
                assert values.shape == expected_shape
                assert np.isfinite(values).all()
        if task_id.endswith("0011"):
            expected_shapes = {
                "msd": (4096, 127),
                "covariance": (127, 127),
                "diffusion_estimates": (3, 4096),
            }
            assert gold["method_order"] == ["OLS", "WLS", "GLS"]
            assert set(gold["artifact_index"]) == {*expected_shapes, "summary"}
            generation_path = hidden / "gold_artifacts/reference_generation.json"
            generation = json.loads(generation_path.read_text(encoding="utf-8"))
            assert generation["experiment"] == "figure_1_fixed_seed_random_walk"
            assert generation["source_commit"] == provenance["commit"]
            assert generation["generator_sha256"] == digest(
                ROOT / "generate_reference_0011.py"
            )
            assert generation["implementation_cross_check"]["checked_seeds"] == 4096
            assert provenance["reference_generation"] == {
                "path": "gold_artifacts/reference_generation.json",
                "sha256": digest(generation_path),
            }
            assert TASK_REGISTRY[task_id]["status"] == "validated"
            for artifact_id, shape in expected_shapes.items():
                item = gold["artifact_index"][artifact_id]
                reference = hidden / item["reference_path"]
                values = np.load(reference, mmap_mode="r", allow_pickle=False)
                assert values.shape == shape and np.isfinite(values).all()
                assert digest(reference) == item["sha256"]
            covariance = np.load(
                hidden / gold["artifact_index"]["covariance"]["reference_path"],
                allow_pickle=False,
            )
            assert np.allclose(covariance, covariance.T, rtol=0, atol=1e-12)
            assert np.linalg.eigvalsh(covariance).min() >= -1e-10
        if task_id.endswith("0012"):
            expected_shapes = {
                "temperature": (200,),
                "orientation": (201,),
                "figure2_hamiltonian": (4, 200, 201),
                "figure2_field": (4, 200, 201),
                "figure3_hamiltonian": (4, 200, 201),
                "figure3_field": (4, 200, 201),
            }
            assert set(gold["artifact_index"]) == set(expected_shapes)
            assert gold["curve_order"]["figure2_spins"] == [0.5, 1.0, 1.5, 2.0]
            assert gold["curve_order"]["figure3_anisotropy_ratios"] == [
                10.0,
                0.0,
                -1.0,
                -10.0,
            ]
            generation_path = hidden / "gold_artifacts/reference_generation.json"
            generation = json.loads(generation_path.read_text(encoding="utf-8"))
            assert generation["experiment"] == (
                "deterministic_effective_hamiltonian_core_method"
            )
            assert generation["scope"] == (
                "core_method_not_full_stochastic_asd_replication"
            )
            assert generation["source_commit"] == provenance["commit"]
            assert generation["generator_sha256"] == digest(
                ROOT / "generate_reference_0012.py"
            )
            assert provenance["reference_generation"] == {
                "path": "gold_artifacts/reference_generation.json",
                "sha256": digest(generation_path),
            }
            for artifact_id, shape in expected_shapes.items():
                item = gold["artifact_index"][artifact_id]
                reference = hidden / item["reference_path"]
                values = np.load(reference, mmap_mode="r", allow_pickle=False)
                assert values.shape == shape
                assert values.dtype == np.dtype("<f8")
                assert np.isfinite(values).all()
                assert digest(reference) == item["sha256"]
    expected_candidates = {
        "Ariel-Norambuena/Quantum-Dynamics-in-MATLAB":
            "deferred_pending_official_reproduction",
        "baddoo/piDMD": "blocked_missing_paper_experiments",
        "bio-phys/DiffusionGLS": "blocked_missing_paper_data",
    }
    for candidate, expected_status in expected_candidates.items():
        record = CANDIDATE_REGISTRY[candidate]
        assert record["status"] == expected_status
        report_path = ROOT / record["report"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["candidate"] == candidate
        assert report["commit"] == record["commit"]
        assert report["conclusion"]["status"] == expected_status
        assert report["conclusion"]["formal_task_created"] is False
        assert "task_id" not in record
        assert not any(row["task_id"] == candidate for row in manifest["tasks"])
    print(
        f"Validated {len(TASK_IDS)} separated replication bundles, hidden references, "
        "and manually rewritten anonymized dossiers."
    )


if __name__ == "__main__":
    main()
