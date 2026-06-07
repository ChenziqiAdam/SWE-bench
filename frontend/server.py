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
                inst = json.loads(line)
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

    preds_by_level = {
        level: _load_predictions(run_dir, level)
        for level in (1, 2, 3)
    }

    rows = []
    for iid, inst in instances.items():
        ev = eval_results.get(iid, {})
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

    return {"instance": inst_out, "levels": levels}


# ── static files (serves index.html at /) ────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
