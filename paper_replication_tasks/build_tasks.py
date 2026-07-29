#!/usr/bin/env python3
"""Build separated public and hidden SciBench replication bundles."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from task_registry import select_validated

ROOT = Path(__file__).resolve().parent

TASKS: dict[str, dict[str, Any]] = {
    "scibench_replication_0007": {
        "title": "Is There Still a Place for Linearization in the Chemistry Curriculum?",
        "objective": "Reproduce the OLS and WLS regression summaries from scratch.",
        "method": (
            "Generate noisy first-order kinetic data, compare linearized least-squares "
            "estimates with nonlinear estimates, and reproduce all reported summaries."
        ),
        "protocol": {},
        "artifacts": {
            **{
                f"metric_{name}": "text/plain"
                for name in (
                    "lin_mean_ols",
                    "non_mean_ols",
                    "lin_ci_ols",
                    "non_ci_ols",
                    "lin_mean_wls",
                    "non_mean_wls",
                )
            }
        },
        "gold": {
            "reference": {
                "lin_mean_ols": 1.05,
                "non_mean_ols": 1.00,
                "lin_ci_ols": [0.76, 1.55],
                "non_ci_ols": [0.85, 1.15],
                "lin_mean_wls": 0.95,
                "non_mean_wls": 1.00,
            },
            "tolerances": {"scalar_absolute": 0.005},
        },
        "provenance": {
            "repository": "https://github.com/arm61/linearization-issues",
            "commit": "eb4dd97c3b4d04f43d8e5c9a402aa63a9e532406",
            "official_entrypoint": (
                "python src/scripts/ols.py; python src/scripts/wls.py; "
                "python src/scripts/distributions.py"
            ),
        },
    },
    "scibench_replication_0008": {
        "title": "Numerical Simulations of a Spin Dynamics Model Based on a Path Integral Approach",
        "objective": "Reproduce 23 finite deterministic curves from five prescribed analytical groups.",
        "method": (
            "Implement the analytical spin expectation curves and path-integral quantum "
            "spin-dynamics approximations described in the manuscript."
        ),
        "protocol": {},
        "artifacts": {},
        "gold": {
            "tolerances": {
                "max_abs": 1e-5,
                "rmse": 2e-6,
            },
        },
        "provenance": {
            "repository": "https://github.com/stonerlab/PIQSD-SingleSpinBz",
            "commit": "5697c290660572012c59c579ca4b99feafd159b8",
            "official_entrypoint": "make clean && make",
        },
    },
    "scibench_replication_0009": {
        "title": "Bilinear Dynamic Mode Decomposition for Quantum Control",
        "objective": "Reproduce the deterministic Floquet-DMD experiment and its extrapolation.",
        "method": (
            "Implement Floquet dynamic mode decomposition for the paper's deterministic "
            "stroboscopic two-level-system example."
        ),
        "protocol": {},
        "artifacts": {
            "floquet_eigenvalues": "application/x-npy",
            "prediction_times": "application/x-npy",
            "prediction_trajectory": "application/x-npy",
        },
        "gold": {
            "protocol": {
                "intrinsic_period": 1.0,
                "drive_frequency": 1.1,
                "measurements_per_drive_period": 4,
                "training_periods": 4,
                "initialization_periods": 1,
                "prediction_periods": 8,
                "dmd_rank": 3,
            },
            "tolerances": {
                "eigenvalue_max_abs": 1e-5,
                "time_max_abs": 1e-12,
                "trajectory_max_abs": 2e-3,
                "trajectory_rmse": 5e-4,
            },
        },
        "provenance": {
            "repository": "https://github.com/andgoldschmidt/biDMD-for-quantum",
            "commit": "8678a7ae99b66554654e13ec5ec0075607c2f44b",
            "official_entrypoint": "Examples.ipynb, deterministic Floquet-DMD Example 2",
        },
    },
    "scibench_replication_0011": {
        "title": "Capturing Time Correlations in Mean-Squared-Displacement Regression",
        "objective": (
            "Reproduce the fixed-seed random-walk MSD ensemble and its OLS, WLS, "
            "and GLS diffusion estimates."
        ),
        "method": (
            "Generate independent three-dimensional lattice random walks, calculate "
            "time-origin-averaged MSD curves, and compare correlated linear estimators."
        ),
        "protocol": {},
        "benchmark_constraints": {
            "random_number_generator": "numpy.random.RandomState",
            "seed_rule": "one independent generator initialized with each integer seed 0..4095",
        },
        "artifacts": {
            "msd": "application/x-npy",
            "covariance": "application/x-npy",
            "diffusion_estimates": "application/x-npy",
            "summary": "application/json",
        },
        "gold": {},
        "provenance": {
            "repository": "https://github.com/arm61/msd-errors",
            "release": "1.0.0",
            "commit": "9141e4edcddc386cdf10a9201d70aba1abaeb66c",
            "official_entrypoint": (
                "showyourwork Figure 1 workflow: numerical_rw.py, "
                "glswlsols.py, and src/scripts/glswlsols.py"
            ),
        },
    },
    "scibench_replication_0012": {
        "title": "Path Integral Spin Dynamics for Quantum Paramagnets",
        "objective": (
            "Reproduce the deterministic effective Hamiltonian and effective field "
            "used by the paper's anisotropic single-spin dynamics method."
        ),
        "method": (
            "Evaluate the exact coherent-state logarithmic Hamiltonian and its "
            "orientation derivative over the prescribed paper-aligned parameter groups."
        ),
        "protocol": {},
        "artifacts": {
            "temperature": "application/x-npy",
            "orientation": "application/x-npy",
            "figure2_hamiltonian": "application/x-npy",
            "figure2_field": "application/x-npy",
            "figure3_hamiltonian": "application/x-npy",
            "figure3_field": "application/x-npy",
        },
        "gold": {},
        "provenance": {
            "repository": "https://github.com/stonerlab/PIQSD-SingleSpinAnisotropy",
            "release": "Zenodo v1.0.8",
            "commit": "ba6f6cbbc665ea55e48f852b2205fda07f0f760e",
            "paper_source": "arXiv:2404.19539v2, main1.tex",
            "official_entrypoint": (
                "python/analytic.py exact logarithmic Hamiltonian/effective-field "
                "functions mapped to python/figure2_*.py and python/figure3_*.py"
            ),
        },
    },
}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def submission_schema(task_id: str, artifacts: dict[str, str]) -> dict[str, Any]:
    artifact_variants = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "path", "media_type"],
            "properties": {
                "id": {"const": artifact_id},
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$)).+$",
                },
                "media_type": {"const": media_type},
            },
        }
        for artifact_id, media_type in artifacts.items()
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"SciBench submission for {task_id}",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "task_id",
            "entrypoint",
            "protocol",
            "checkpoints",
            "artifacts",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "task_id": {"const": task_id},
            "entrypoint": {"type": "string", "minLength": 1},
            "protocol": {"type": "object"},
            "checkpoints": {"type": "object"},
            "artifacts": {
                "type": "array",
                "minItems": len(artifacts),
                "maxItems": len(artifacts),
                "items": {"oneOf": artifact_variants},
                "allOf": [
                    {
                        "contains": {
                            "type": "object",
                            "required": ["id"],
                            "properties": {"id": {"const": artifact_id}},
                        },
                        "minContains": 1,
                        "maxContains": 1,
                    }
                    for artifact_id in artifacts
                ],
            },
        },
    }


def task_markdown(task_id: str, task: dict[str, Any]) -> str:
    artifacts = "\n".join(
        f"- `{artifact}` (`{media_type}`)"
        for artifact, media_type in task["artifacts"].items()
    )
    return (
        f"# {task_id}\n\n"
        f"{task['objective']}\n\n"
        "Implement the scientific method from scratch in the offline workspace. "
        "Recover the scientific parameters and experiment definition from the "
        "anonymized replication dossier; they are intentionally not repeated in "
        "`input.json`. "
        "You may use equivalent numerical algorithms and "
        "locally available scientific libraries.\n\n"
        "Run your implementation and write `results.json` at the submission root. "
        "Set `entrypoint` to the command used to run your implementation. "
        "The `protocol` and `checkpoints` objects may be empty; scientific values are "
        "read directly from the required artifacts. "
        "All artifact paths must be relative to that root and must not traverse through "
        "a symlink or `..`.\n\n"
        "## Required logical artifacts\n\n"
        f"{artifacts}\n"
    )


def configure_0008(task: dict[str, Any], hidden: Path) -> None:
    reference_root = hidden / "gold_artifacts"
    files = sorted(reference_root.glob("figure*_data/*.tsv"))
    if len(files) != 23:
        raise RuntimeError(
            "task 0008 requires 23 curated deterministic TSV files under "
            "hidden/gold_artifacts"
        )
    index = []
    artifacts = {}
    selected = files
    if len(selected) != 23:
        raise RuntimeError("task 0008 requires 23 finite deterministic references")
    for curve_number, path in enumerate(selected, 1):
        relative = path.relative_to(reference_root)
        logical_id = f"curve_{curve_number:02d}"
        match = re.match(r"figure(\d+)_data/", relative.as_posix())
        figure = int(match.group(1)) if match else 0
        index.append(
            {
                "id": logical_id,
                "reference_path": f"gold_artifacts/{relative.as_posix()}",
                "figure": figure,
                "sha256": sha256(path),
            }
        )
        artifacts[logical_id] = "text/tab-separated-values"
    task["artifacts"] = artifacts
    task["gold"]["artifact_index"] = index


def configure_0009(task: dict[str, Any], hidden: Path) -> None:
    shapes = {
        "floquet_eigenvalues": [3, 2],
        "prediction_times": [32],
        "prediction_trajectory": [3, 32],
    }
    index = {}
    for artifact_id, shape in shapes.items():
        relative = f"gold_artifacts/{artifact_id}.npy"
        path = hidden / relative
        if not path.is_file():
            raise RuntimeError(
                "task 0009 reference artifacts are missing; run "
                "generate_reference_0009.py first"
            )
        index[artifact_id] = {
            "reference_path": relative,
            "shape": shape,
            "sha256": sha256(path),
        }
    task["gold"]["artifact_index"] = index


def configure_0011(task: dict[str, Any], hidden: Path) -> None:
    reference_root = hidden / "gold_artifacts"
    generation_path = reference_root / "reference_generation.json"
    if not generation_path.is_file():
        raise RuntimeError(
            "task 0011 reference artifacts are missing; run "
            "generate_reference_0011.py first"
        )
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    shapes = {
        "msd": [4096, 127],
        "covariance": [127, 127],
        "diffusion_estimates": [3, 4096],
    }
    index = {}
    for artifact_id, shape in shapes.items():
        relative = f"gold_artifacts/{artifact_id}.npy"
        path = hidden / relative
        values = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(values.shape) != shape:
            raise RuntimeError(f"task 0011 {artifact_id} has wrong shape")
        index[artifact_id] = {
            "reference_path": relative,
            "shape": shape,
            "sha256": sha256(path),
        }
    summary_path = reference_root / "summary.json"
    index["summary"] = {
        "reference_path": "gold_artifacts/summary.json",
        "sha256": sha256(summary_path),
    }
    task["gold"]["artifact_index"] = index
    task["gold"]["tolerances"] = generation["tolerances"]
    task["gold"]["method_order"] = ["OLS", "WLS", "GLS"]
    task["gold"]["experiment"] = generation["parameters"]


def configure_0012(task: dict[str, Any], hidden: Path) -> None:
    reference_root = hidden / "gold_artifacts"
    generation_path = reference_root / "reference_generation.json"
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    shapes = {
        "temperature": [200],
        "orientation": [201],
        "figure2_hamiltonian": [4, 200, 201],
        "figure2_field": [4, 200, 201],
        "figure3_hamiltonian": [4, 200, 201],
        "figure3_field": [4, 200, 201],
    }
    index = {}
    for artifact_id, shape in shapes.items():
        relative = f"gold_artifacts/{artifact_id}.npy"
        path = hidden / relative
        values = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(values.shape) != shape or values.dtype != np.dtype("<f8"):
            raise RuntimeError(f"task 0012 {artifact_id} has wrong shape or dtype")
        if not np.isfinite(values).all():
            raise RuntimeError(f"task 0012 {artifact_id} contains non-finite values")
        index[artifact_id] = {
            "reference_path": relative,
            "shape": shape,
            "dtype": "float64",
            "sha256": sha256(path),
        }
    task["gold"]["artifact_index"] = index
    task["gold"]["tolerances"] = generation["tolerances"]
    task["gold"]["curve_order"] = generation["curve_order"]
    task["gold"]["experiment"] = {
        "a1_over_kb_kelvin": generation["parameters"]["a1_over_kb_kelvin"]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        help="build only this validated task ID (repeatable)",
    )
    args = parser.parse_args()
    task_ids = select_validated(args.tasks)
    missing_definitions = set(task_ids) - set(TASKS)
    if missing_definitions:
        raise RuntimeError(f"missing builder definitions: {sorted(missing_definitions)}")
    manifest = {"schema_version": 3, "tasks": []}
    existing_manifest = ROOT / "manifest.json"
    if args.tasks and existing_manifest.is_file():
        current = json.loads(existing_manifest.read_text(encoding="utf-8"))
        manifest["tasks"] = [
            row for row in current["tasks"] if row["task_id"] not in task_ids
        ]
    for task_id in task_ids:
        task = copy.deepcopy(TASKS[task_id])
        task_dir = ROOT / task_id
        public = task_dir / "public"
        hidden = task_dir / "hidden"
        public.mkdir(parents=True, exist_ok=True)
        hidden.mkdir(parents=True, exist_ok=True)
        if task_id.endswith("0008"):
            configure_0008(task, hidden)
        if task_id.endswith("0009"):
            configure_0009(task, hidden)
        if task_id.endswith("0011"):
            configure_0011(task, hidden)
        if task_id.endswith("0012"):
            configure_0012(task, hidden)
        submission = {
            "path": "results.json",
            "schema": "submission_schema.json",
            "protocol_fields": list(task["protocol"]),
            "required_artifacts": [
                {"id": key, "media_type": value}
                for key, value in task["artifacts"].items()
            ],
        }
        input_value = {
            "schema_version": 3,
            "task_id": task_id,
            "resources": [
                {
                    "id": "masked_paper",
                    "path": "masked_paper.pdf",
                    "media_type": "application/pdf",
                }
            ],
            "submission": submission,
        }
        if task.get("benchmark_constraints"):
            input_value["benchmark_constraints"] = task["benchmark_constraints"]
        write_json(public / "input.json", input_value)
        write_json(
            public / "submission_schema.json",
            submission_schema(task_id, task["artifacts"]),
        )
        (public / "task.md").write_text(task_markdown(task_id, task), encoding="utf-8")
        curated_source = ROOT / "masked_paper_sources" / f"{task_id}.txt"
        if not curated_source.is_file() or not (public / "masked_paper.pdf").is_file():
            raise RuntimeError(
                "anonymized replication dossier is missing; run prepare_masked_papers.py "
                "against the reviewed authoritative source package"
            )

        gold = {
            "schema_version": 3,
            "task_id": task_id,
            "required_artifact_ids": list(task["artifacts"]),
            "required_artifacts": task["artifacts"],
            "scoring": {
                "scientific": 0.90,
                "artifacts": 0.10,
            },
            **task["gold"],
        }
        write_json(hidden / "gold_output.json", gold)
        provenance = {
            "schema_version": 1,
            "task_id": task_id,
            "paper": task["title"],
            **task["provenance"],
        }
        if (
            task_id.endswith("0009")
            or task_id.endswith("0011")
            or task_id.endswith("0012")
        ):
            generation = hidden / "gold_artifacts/reference_generation.json"
            provenance["reference_generation"] = {
                "path": "gold_artifacts/reference_generation.json",
                "sha256": sha256(generation),
            }
        write_json(hidden / "provenance.json", provenance)
        wrapper = (
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import sys\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))\n"
            "from evaluation.cli import run_for_task\n"
            f"raise SystemExit(run_for_task({task_id!r}))\n"
        )
        (hidden / "evaluator.py").write_text(wrapper, encoding="utf-8")
        manifest["tasks"].append(
            {
                "task_id": task_id,
                "public_files": {
                    name: sha256(public / name)
                    for name in (
                        "task.md",
                        "input.json",
                        "submission_schema.json",
                        "masked_paper.pdf",
                    )
                },
                "gold_output_sha256": sha256(hidden / "gold_output.json"),
            }
        )
        for legacy in (
            "task.md",
            "input.json",
            "gold_output.json",
            "provenance.json",
            "run_record.json",
            "status.json",
        ):
            (task_dir / legacy).unlink(missing_ok=True)
    manifest["tasks"].sort(key=lambda row: row["task_id"])
    write_json(ROOT / "manifest.json", manifest)


if __name__ == "__main__":
    main()
