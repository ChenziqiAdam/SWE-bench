"""FastAPI server for the SWE-bench LLM eval viewer."""
from __future__ import annotations

import csv
import json
from glob import glob
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from swebench.eval_pipeline.prompt_builder import (
    build_level1_prompt,
    build_level2_prompt,
    build_level3_prompt,
)

app = FastAPI(title="SWE-bench Eval Viewer")

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"
FRONTEND_DIR = Path(__file__).parent


# ── data loaders ──────────────────────────────────────────────────────────────

def _load_instances(run_dir: Path) -> dict[str, dict]:
    path = run_dir / "instances.jsonl"
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    inst = json.loads(line)
                except json.JSONDecodeError:
                    # A killed ingest can leave one partial trailing JSONL row.
                    continue
                result[inst["instance_id"]] = inst
    return result


def _load_predictions(run_dir: Path, level: int) -> dict[str, dict]:
    path = run_dir / f"level{level}_predictions.jsonl"
    if not path.exists():
        return {}
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                pred = json.loads(line)
                result[pred["instance_id"]] = pred
    return result


def _load_agent_predictions(run_dir: Path) -> dict[str, dict]:
    """Load the selected single-patch format used by test-generation runs."""
    for name in ("agent_predictions.selected.jsonl", "agent_predictions.jsonl"):
        path = run_dir / name
        if not path.exists():
            continue
        result = {}
        with open(path) as f:
            for line in f:
                try:
                    pred = json.loads(line)
                except json.JSONDecodeError:
                    continue
                result[pred["instance_id"]] = pred
        return result
    return {}


def _load_eval_results(run_dir: Path) -> dict[str, dict]:
    csvs = glob(str(run_dir / "*.csv"))
    if not csvs:
        return {}
    with open(csvs[0], newline="") as f:
        reader = csv.DictReader(f)
        return {row["instance_id"]: row for row in reader}


def _run_dir(run: str) -> Path:
    d = OUTPUTS_DIR / run
    if not d.is_dir() or not (d / "instances.jsonl").exists():
        raise HTTPException(status_code=404, detail=f"Run '{run}' not found")
    return d


SCIENCE_CASES = {
    "openmm__openmm-4907": {
        "domain": "Molecular simulation · electrostatics",
        "challenge": "A numerical tuning parameter must not change physical energy.",
        "agent_miss": "The generated oracle compares two PME energies with a 5 kJ/mol tolerance. It is too loose to expose the missing neutralizing-plasma correction, and covers fewer methods and state-update paths than the PR test.",
        "gold_strength": "The PR test checks Ewald, PME, and LJPME; parameter offsets; charge updates; and alpha changes induced through cutoff distance, all at 1e-4 tolerance.",
        "science_reason": "A plausible test requires knowing that alpha is non-physical, the analytic correction depends on total charge and volume, and charged periodic systems need a uniform background convention.",
    },
    "openmm__openmm-1837": {
        "domain": "Molecular simulation · metadynamics",
        "challenge": "Test derivatives of collective variables, not merely interpolation calculus.",
        "agent_miss": "The generated tests focus on derivatives of tabulated functions. They fail after the gold patch because their expected derivative semantics do not match the scientific feature exercised by the PR.",
        "gold_strength": "The PR tests the collective-variable force and energy-parameter derivative pathway needed by metadynamics.",
        "science_reason": "The hard part is selecting the physically meaningful observable—biasing-force derivatives through a collective variable—rather than a nearby API behavior.",
    },
    "openmm__openmm-5278": {
        "domain": "Molecular simulation · pressure coupling",
        "challenge": "Validate atom-wise box scaling and finite-difference pressure behavior.",
        "agent_miss": "The generated patch mostly checks getters and serialization, and does not construct a molecular system whose coordinates distinguish rigid-molecule scaling from independent particle scaling.",
        "gold_strength": "The PR's behavioral tests exercise coordinate scaling and the numerical pressure estimator, where epsilon affects a finite-difference calculation.",
        "science_reason": "API round trips cannot establish that a barostat preserves the intended molecular geometry or thermodynamic calculation.",
    },
    "openmm__openmm-2105": {
        "domain": "Molecular simulation · alchemical interactions",
        "challenge": "Express context-parameter modulation with the existing nonbonded-force model.",
        "agent_miss": "The generated test invents a NonbondedBlockForce class, so it cannot compile against the base revision and never reaches the scientific oracle.",
        "gold_strength": "The PR test uses NonbondedForce parameter offsets and context parameters to verify energy/force changes through the supported API.",
        "science_reason": "The feature is a CHARMM BLOCK-like scientific workflow implemented through an existing abstraction; recognizing that mapping is necessary before writing a test.",
    },
}


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/runs")
def list_runs() -> list[str]:
    """Return names of available run directories."""
    return sorted(
        d.name
        for d in OUTPUTS_DIR.iterdir()
        if d.is_dir() and (d / "instances.jsonl").exists()
    )


@app.get("/api/runs/{run}/overview")
def overview(run: str) -> list[dict]:
    """Return one summary row per instance in the run."""
    run_dir = _run_dir(run)
    instances = _load_instances(run_dir)
    eval_results = _load_eval_results(run_dir)
    agent_predictions = _load_agent_predictions(run_dir)

    preds_by_level = {
        level: _load_predictions(run_dir, level)
        for level in (1, 2, 3)
    }

    rows = []
    for iid, inst in instances.items():
        ev = eval_results.get(iid, {})
        pred = agent_predictions.get(iid, {})
        science = SCIENCE_CASES.get(iid)
        rows.append({
            "instance_id": iid,
            "repo": inst.get("repo", ""),
            "pull_number": inst.get("pull_number"),
            "pr_title": inst.get("pr_title", ""),
            "category": inst.get("category", ""),
            "algorithm_name": inst.get("algorithm_name", ""),
            "buildable": ev.get("buildable", ""),
            "level1_resolved": ev.get("level1_resolved", ""),
            "level2_resolved": ev.get("level2_resolved", ""),
            "level3_resolved": ev.get("level3_resolved", ""),
            "has_level1": bool(preds_by_level[1].get(iid, {}).get("model_patch") or preds_by_level[1].get(iid, {}).get("full_output")),
            "has_level2": bool(preds_by_level[2].get(iid, {}).get("model_patch") or preds_by_level[2].get(iid, {}).get("full_output")),
            "has_level3": bool(preds_by_level[3].get(iid, {}).get("model_patch") or preds_by_level[3].get(iid, {}).get("full_output")),
            "skipped_level1": bool(preds_by_level[1].get(iid, {}).get("skipped")),
            "skipped_level2": bool(preds_by_level[2].get(iid, {}).get("skipped")),
            "skipped_level3": bool(preds_by_level[3].get(iid, {}).get("skipped")),
            "status": ev.get("status", ""),
            "failure_reason": ev.get("failure_reason", ""),
            "has_agent_test": bool(pred.get("model_patch")),
            "is_science_case": science is not None,
            "science_domain": science["domain"] if science else "",
            "science_challenge": science["challenge"] if science else "",
        })
    return rows


@app.get("/api/runs/{run}/instance/{instance_id}")
def instance_detail(run: str, instance_id: str) -> dict:
    """Return full detail for one instance including reconstructed prompts."""
    run_dir = _run_dir(run)
    instances = _load_instances(run_dir)

    if instance_id not in instances:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    inst = instances[instance_id]
    eval_results = _load_eval_results(run_dir)
    ev = eval_results.get(instance_id, {})
    agent_pred = _load_agent_predictions(run_dir).get(instance_id, {})

    # Build prompts using the existing prompt_builder functions
    prompts = {
        1: build_level1_prompt(inst),
        2: build_level2_prompt(inst),
        3: build_level3_prompt(inst),
    }

    # Load predictions for all levels
    levels = {}
    for level in (1, 2, 3):
        preds = _load_predictions(run_dir, level)
        pred = preds.get(instance_id, {})
        resolved_key = f"level{level}_resolved"
        levels[str(level)] = {
            "prompt": prompts[level],
            "full_output": pred.get("full_output"),
            "model_patch": pred.get("model_patch"),
            "model_name_or_path": pred.get("model_name_or_path"),
            "resolved": ev.get(resolved_key, ""),
            "skipped": pred.get("skipped", False),
        }

    # Strip file_contents from the instance before returning (large, embedded in prompts)
    inst_out = {k: v for k, v in inst.items() if k != "file_contents"}

    return {
        "instance": inst_out,
        "levels": levels,
        "comparison": {
            "agent_test_patch": agent_pred.get("model_patch", ""),
            "gold_test_patch": inst.get("test_patch", ""),
            "model_name": agent_pred.get("model_name_or_path", ""),
            "eval_mode": agent_pred.get("eval_mode", ""),
            "status": ev.get("status", ""),
            "failure_reason": ev.get("failure_reason", ""),
            "base_failed_tests": ev.get("base_failed_tests", ""),
            "gold_passed_tests": ev.get("gold_passed_tests", ""),
        },
        "science_analysis": SCIENCE_CASES.get(instance_id),
    }


# ── static files (serves index.html at /) ────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
