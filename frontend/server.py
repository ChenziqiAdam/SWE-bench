"""FastAPI server for the SWE-bench LLM eval viewer."""
from __future__ import annotations

import csv
import json
from collections import Counter
from glob import glob
from pathlib import Path
from typing import Any

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
LOGS_DIR = Path(__file__).parent.parent / "logs" / "run_evaluation"
FRONTEND_DIR = Path(__file__).parent
TRAJECTORY_VALUE_LIMIT = 20_000


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
    preferred = run_dir / f"{run_dir.name}_results.csv"
    csvs = [str(preferred)] if preferred.is_file() else sorted(glob(str(run_dir / "*.csv")))
    if not csvs:
        return {}
    with open(csvs[0], newline="") as f:
        reader = csv.DictReader(f)
        return {row["instance_id"]: row for row in reader}


def _clip(value: Any, limit: int = TRAJECTORY_VALUE_LIMIT) -> tuple[Any, bool]:
    """Bound large tool payloads while preserving their JSON shape when possible."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value, False
        return value[:limit] + f"\n… truncated {len(value) - limit:,} characters", True
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) <= limit:
        return value, False
    return encoded[:limit] + f"\n… truncated {len(encoded) - limit:,} characters", True


def _trajectory_files(run_dir: Path, instance_id: str) -> list[Path]:
    log_dir = run_dir / "claude_code_logs"
    if not log_dir.is_dir():
        return []
    base = log_dir / f"{instance_id}.jsonl"
    attempts = sorted(log_dir.glob(f"{instance_id}.attempt-*.jsonl"))
    return ([base] if base.is_file() else []) + attempts


def _load_trajectory(path: Path) -> dict:
    """Normalize Claude Code JSONL into a compact, browser-friendly timeline."""
    events: list[dict] = []
    tool_events: dict[str, dict] = {}
    counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    ignored_thinking_tokens = 0
    malformed_lines = 0
    raw_line_count = 0
    init: dict = {}
    result: dict | None = None

    with path.open(errors="replace") as handle:
        for raw_line_count, line in enumerate(handle, 1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue

            event_type = raw.get("type", "unknown")
            subtype = raw.get("subtype")
            if event_type == "system" and subtype == "thinking_tokens":
                ignored_thinking_tokens += 1
                continue
            if event_type == "system" and subtype == "init":
                init = {
                    key: raw.get(key)
                    for key in ("session_id", "model", "cwd", "claude_code_version", "permissionMode")
                }
                events.append({"seq": raw_line_count, "kind": "system", "subtype": "init", "data": init})
                counts["system"] += 1
                continue
            if event_type == "assistant":
                for block in raw.get("message", {}).get("content", []):
                    kind = block.get("type", "assistant")
                    if kind in {"text", "thinking"}:
                        text, truncated = _clip(block.get(kind, ""))
                        events.append({
                            "seq": raw_line_count,
                            "kind": kind,
                            "text": text,
                            "truncated": truncated,
                        })
                        counts[kind] += 1
                    elif kind == "tool_use":
                        tool_id = block.get("id", "")
                        payload, truncated = _clip(block.get("input", {}))
                        event = {
                            "seq": raw_line_count,
                            "kind": "tool",
                            "tool_id": tool_id,
                            "name": block.get("name", "Tool"),
                            "input": payload,
                            "input_truncated": truncated,
                            "result": None,
                        }
                        events.append(event)
                        if tool_id:
                            tool_events[tool_id] = event
                        counts["tool"] += 1
                        tool_counts[event["name"]] += 1
                continue
            if event_type == "user":
                for block in raw.get("message", {}).get("content", []):
                    if block.get("type") == "tool_result":
                        content, truncated = _clip(block.get("content", ""))
                        tool_id = block.get("tool_use_id", "")
                        tool_result = {
                            "content": content,
                            "is_error": bool(block.get("is_error")),
                            "truncated": truncated,
                            "seq": raw_line_count,
                        }
                        if tool_id in tool_events:
                            tool_events[tool_id]["result"] = tool_result
                        else:
                            events.append({
                                "seq": raw_line_count,
                                "kind": "orphan_result",
                                "tool_id": tool_id,
                                **tool_result,
                            })
                            counts["orphan_result"] += 1
                    elif block.get("type") == "text":
                        text, truncated = _clip(block.get("text", ""))
                        events.append({
                            "seq": raw_line_count,
                            "kind": "user",
                            "text": text,
                            "truncated": truncated,
                        })
                        counts["user"] += 1
                continue
            if event_type == "result":
                result = {
                    key: raw.get(key)
                    for key in (
                        "subtype", "is_error", "duration_ms", "duration_api_ms",
                        "num_turns", "result", "total_cost_usd", "usage",
                    )
                    if key in raw
                }
                events.append({"seq": raw_line_count, "kind": "result", "data": result})
                counts["result"] += 1
                continue

            data, truncated = _clip({
                key: value for key, value in raw.items()
                if key not in {"message", "uuid", "session_id"}
            })
            events.append({
                "seq": raw_line_count,
                "kind": "system",
                "subtype": subtype or event_type,
                "data": data,
                "truncated": truncated,
            })
            counts["system"] += 1

    events.sort(key=lambda event: event["seq"])
    return {
        "summary": {
            "source": path.name,
            "size_bytes": path.stat().st_size,
            "raw_line_count": raw_line_count,
            "visible_event_count": len(events),
            "ignored_thinking_token_events": ignored_thinking_tokens,
            "malformed_lines": malformed_lines,
            "terminal_result_seen": result is not None,
            "completion": "completed" if result is not None else "interrupted",
            "counts": dict(counts),
            "tool_counts": dict(tool_counts.most_common()),
            **init,
        },
        "events": events,
        "result": result,
    }


def _run_dir(run: str) -> Path:
    d = OUTPUTS_DIR / run
    if not d.is_dir() or not (d / "instances.jsonl").exists():
        raise HTTPException(status_code=404, detail=f"Run '{run}' not found")
    return d


def _load_instance_report(run: str, instance_id: str) -> dict:
    """Load the compact scalar portion of the newest per-instance report."""
    candidates = sorted(
        LOGS_DIR.glob(f"{run}_*/*/{instance_id}/report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {}
    try:
        raw = json.loads(candidates[0].read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    report = raw.get(instance_id, raw)
    if not isinstance(report, dict):
        return {}
    excluded = {"coverage_before", "coverage_after", "inference_metrics"}
    compact = {
        key: value for key, value in report.items()
        if key not in excluded and not isinstance(value, dict)
    }
    compact["report_path"] = str(candidates[0].relative_to(LOGS_DIR.parent.parent))
    return compact


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
            "has_trajectory": bool(_trajectory_files(run_dir, iid)),
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
        "evaluation": {
            "csv": ev,
            "report": _load_instance_report(run, instance_id),
            "inference_metrics": agent_pred.get("metrics", {}),
        },
    }


@app.get("/api/runs/{run}/instance/{instance_id}/trajectory")
def instance_trajectory(run: str, instance_id: str, source: str | None = None) -> dict:
    """Return a normalized agent event timeline with tool results paired."""
    run_dir = _run_dir(run)
    if instance_id not in _load_instances(run_dir):
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    files = _trajectory_files(run_dir, instance_id)
    if not files:
        raise HTTPException(status_code=404, detail="No trajectory found for this instance")
    if source is not None:
        if Path(source).name != source:
            raise HTTPException(status_code=400, detail="Invalid trajectory source")
        matches = [path for path in files if path.name == source]
        if not matches:
            raise HTTPException(status_code=404, detail=f"Trajectory source '{source}' not found")
        selected = matches[0]
    else:
        selected = files[0]
    payload = _load_trajectory(selected)
    payload["sources"] = [path.name for path in files]
    return payload


# ── static files (serves index.html at /) ────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
