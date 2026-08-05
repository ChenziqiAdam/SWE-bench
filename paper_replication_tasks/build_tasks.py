#!/usr/bin/env python3
"""Legacy candidate-case builder.

This module may define inputs, but it must never create or bless official gold.  Gold
finalization is intentionally fail-closed until a pinned official adapter has staged
raw and normalized outputs with complete provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from scientific import solve
from task_registry import TASK_REGISTRY

ROOT = Path(__file__).resolve().parent


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linear_blocks(seed: int, dimension: int = 3, blocks: int = 2, samples: int = 8) -> list[list[list[float]]]:
    rng = np.random.default_rng(seed)
    eigenvalues = np.linspace(0.72, 0.96, dimension)
    basis, _ = np.linalg.qr(rng.normal(size=(dimension, dimension)))
    operator = basis @ np.diag(eigenvalues) @ basis.T
    result = []
    for _ in range(blocks):
        state = rng.normal(size=dimension)
        snapshots = [state]
        for _ in range(samples - 1):
            state = operator @ state
            snapshots.append(state)
        result.append(np.asarray(snapshots).T.tolist())
    return result


PUBLIC: dict[str, list[dict[str, Any]]] = {
    "scibench_replication_0007": [
        {"rate_constant": 0.15, "initial_concentration": 7.5, "time_grid": list(range(2, 22, 2)), "noise_std": 0.3, "replicates": 256, "rng": "numpy.random.Generator.PCG64", "seed": 1},
    ],
    "scibench_replication_0008": [
        {"spin": spin, "temperature_grid": np.linspace(low, high, 31).tolist(), "field_scale_kelvin": 1.343427, "approximations": approximations}
        for spin, low, high, approximations in (
            (0.5, .5, 8, ["quantum"]), (0.5, .5, 8, ["classical"]), (0.5, .5, 8, ["quantum", "classical"]),
            (1.0, .5, 8, ["quantum"]), (1.0, .5, 8, ["classical"]), (1.0, .5, 8, ["quantum", "classical"]),
            (1.5, .5, 8, ["quantum"]), (1.5, .5, 8, ["classical"]), (1.5, .5, 8, ["quantum", "classical"]),
            (2.0, .5, 8, ["quantum"]), (2.0, .5, 8, ["classical"]), (2.0, .5, 8, ["quantum", "classical"]),
            (2.5, 1, 10, ["quantum"]), (2.5, 1, 10, ["classical"]), (2.5, 1, 10, ["quantum", "classical"]),
            (3.0, 1, 10, ["quantum"]), (3.0, 1, 10, ["classical"]), (3.0, 1, 10, ["quantum", "classical"]),
            (4.0, 1, 12, ["quantum"]), (4.0, 1, 12, ["classical"]), (4.0, 1, 12, ["quantum", "classical"]),
            (5.0, 1, 12, ["quantum"]), (5.0, 1, 12, ["quantum", "classical"]),
        )
    ],
    "scibench_replication_0009": [
        {"snapshot_blocks": linear_blocks(90), "dmd_rank": 3, "prediction_steps": 10},
    ],
    "scibench_replication_0011": [
        {"atoms": 32, "steps": 32, "jump_size": 1.0, "seed_range": [0, 16], "rng": "numpy.random.RandomState"},
    ],
    "scibench_replication_0012": [
        {"spin": spin, "anisotropy_ratio": ratio, "temperature_grid": [0.75, 1.5, 3.0], "orientation_grid": np.linspace(-0.9, .9, 25).tolist()}
        for spin, ratio in ((.5, 0.0), (1., 0.0), (1.5, 0.0), (2., 0.0), (1., -1.), (1., 1.), (1., -10.), (1., 10.))
    ],
}

HIDDEN: dict[str, list[dict[str, Any]]] = {
    "scibench_replication_0007": [
        {"rate_constant": rate, "initial_concentration": initial, "time_grid": times, "noise_std": noise, "replicates": 128, "rng": "numpy.random.Generator.PCG64", "seed": seed}
        for rate, initial, times, noise, seed in (
            (.08, 4., [1, 2, 4, 7, 11, 16], .12, 101), (.22, 9., [1, 3, 5, 8, 12], .25, 202), (.12, 6., [2, 5, 9, 14, 20], .4, 303), (.3, 12., [1, 2, 3, 5, 7], .18, 404), (.05, 3.5, [2, 6, 12, 20, 30], .09, 505),
        )
    ],
    "scibench_replication_0008": [
        {"spin": spin, "temperature_grid": grid, "field_scale_kelvin": field, "approximations": approx}
        for spin, grid, field, approx in (
            (.5, [.35, .7, 1.4, 2.8, 5.6], 1.2, ["quantum", "classical"]),
            (1.5, [.6, 1.1, 2.3, 4.7], 1.5, ["quantum"]),
            (2.5, [.8, 1.7, 3.5, 7.], 1.1, ["classical"]),
            (3.5, [.9, 1.8, 3.6, 7.2], 1.4, ["quantum", "classical"]),
            (5., [1.2, 2.4, 4.8, 9.6], 1.3, ["quantum"]),
        )
    ],
    "scibench_replication_0009": [
        {"snapshot_blocks": linear_blocks(900 + index, dimension=dimension, blocks=blocks), "dmd_rank": dimension, "prediction_steps": 6 + index}
        for index, (dimension, blocks) in enumerate(((2, 2), (3, 3), (4, 2), (3, 2), (4, 3)))
    ],
    "scibench_replication_0011": [
        {"atoms": atoms, "steps": steps, "jump_size": jump, "seed_range": seeds, "rng": "numpy.random.RandomState"}
        for atoms, steps, jump, seeds in ((8, 20, .5, [101, 109]), (16, 24, 1., [211, 223]), (24, 36, 1.5, [307, 315]), (40, 28, .75, [401, 413]), (12, 48, 2., [503, 511]))
    ],
    "scibench_replication_0012": [
        {"spin": spin, "anisotropy_ratio": ratio, "temperature_grid": temp, "orientation_grid": orient}
        for spin, ratio, temp, orient in (
            (.5, .4, [.6, 1.2, 2.4], [-.8, -.3, .2, .7]), (1., -2.5, [.8, 1.6, 3.2], [-.75, -.25, .25, .75]), (1.5, 3., [.7, 1.4, 2.8], [-.9, -.45, 0., .45, .9]), (2., -4., [1., 2., 4.], [-.6, -.2, .2, .6]), (2.5, 1.25, [.9, 1.8, 3.6], [-.85, -.4, .1, .55, .85]),
        )
    ],
}

TOLERANCES = {
    "scibench_replication_0007": {"max_abs": 2e-6, "rmse": 5e-7},
    "scibench_replication_0008": {"max_abs": 1e-10, "rmse": 2e-11},
    "scibench_replication_0009": {"max_abs": 1e-10, "rmse": 1e-11},
    "scibench_replication_0011": {"max_abs": 1e-10, "rmse": 2e-11},
    "scibench_replication_0012": {"max_abs": 1e-11, "rmse": 1e-12},
}


def schema(task_id: str) -> dict[str, Any]:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "required": ["schema_version", "task_id", "entrypoint"], "properties": {"schema_version": {"const": 4}, "task_id": {"const": task_id}, "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}}}


def task_text(task_id: str) -> str:
    focus = TASK_REGISTRY[task_id]["functional_target"]
    return f"""# {task_id}\n\nImplement the paper's core method as a general command-line program: {focus}.\n\nThe runner invokes the declared entrypoint once per case as:\n\n```text\n<entrypoint> --input <case/input.json> --output <case-output-dir>\n```\n\nWrite one finite JSON object to `<case-output-dir>/output.json`. Public cases and expected outputs are under `cases/`; five additional cases are hidden. Submit `submission.json` matching `interface.schema.json`. Random inputs explicitly declare their RNG and seed protocol.\n"""


def build(task_id: str, papers: Path) -> dict[str, Any]:
    raise RuntimeError(
        "official gold cannot be generated by build_tasks.py/scientific.py; "
        "use validate_tasks.py --reproduce-official with curator adapters"
    )
    # The code below is retained temporarily only as a readable record of the
    # candidate inputs. It is unreachable by design.
    root = ROOT / task_id
    if root.exists():
        shutil.rmtree(root)
    (root / "public/cases").mkdir(parents=True)
    (root / "hidden/cases").mkdir(parents=True)
    shutil.copyfile(papers / f"{task_id[-4:]}.pdf", root / "public/paper.pdf")
    (root / "public/task.md").write_text(task_text(task_id), encoding="utf-8")
    write_json(root / "public/interface.schema.json", schema(task_id))
    hashes = []
    for split, cases in (("public", PUBLIC[task_id]), ("hidden", HIDDEN[task_id])):
        for index, case in enumerate(cases, 1):
            case_id = f"case_{index:02d}"
            case_root = root / split / "cases" / case_id
            write_json(case_root / "input.json", case)
            write_json(case_root / "output.json", solve(task_id, case))
            hashes.append({"split": split, "case_id": case_id, "input_sha256": digest(case_root / "input.json"), "output_sha256": digest(case_root / "output.json")})
    write_json(root / "hidden/tolerances.json", TOLERANCES[task_id])
    registry = TASK_REGISTRY[task_id]
    provenance = {
        "schema_version": 4, "task_id": task_id,
        "repository": registry["repository"], "commit": registry["commit"],
        "environment": {"python": "3.12", "numpy": np.__version__, "rng_protocol_in_input": True},
        "official_adapter": registry["official_adapter"],
        "generation_command": f"python build_tasks.py --task {task_id} --papers <trusted-paper-dir>",
        "parameter_patch": "parameters are injected only through the documented JSON adapter; equations and numerical kernels follow the pinned source",
        "independent_audit": {"implementation": "scientific.py clean-room vectorized formulation", "status": "not_run_against_official_gold"},
        "cases": hashes,
    }
    write_json(root / "hidden/provenance.json", provenance)
    public_files = {path.relative_to(root / "public").as_posix(): digest(path) for path in sorted((root / "public").rglob("*")) if path.is_file()}
    hidden_files = {path.relative_to(root / "hidden").as_posix(): digest(path) for path in sorted((root / "hidden").rglob("*")) if path.is_file()}
    return {"task_id": task_id, "public_files": public_files, "hidden_files": hidden_files}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", action="append")
    parser.add_argument("--papers", type=Path, required=True)
    args = parser.parse_args()
    selected = args.task or []
    if not selected:
        parser.error("--task is required; candidate bulk regeneration is disabled")
    unknown = set(selected) - set(TASK_REGISTRY)
    if unknown:
        parser.error(f"unknown task IDs: {sorted(unknown)}")
    rows = [build(task_id, args.papers) for task_id in selected]
    write_json(ROOT / "manifest.json", {"schema_version": 4, "scoring": {"public_weight": .4, "hidden_weight": .6}, "tasks": rows})


if __name__ == "__main__":
    main()
