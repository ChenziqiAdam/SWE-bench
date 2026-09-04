#!/usr/bin/env python3
"""Run 0018_core G6 in three fresh, restricted model contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from sobiEquity_core_blind_common import read_env, run_context

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
DESTINATION = ROOT / "core_algorithm_audits/0018_core_blind.json"


def clean_json(text: str) -> dict:
    value = text.strip()
    for marker in ("```json", "```"):
        if marker in value:
            fenced = value.split(marker, 1)[1].split("```", 1)[0].strip()
            try:
                return json.loads(fenced)
            except json.JSONDecodeError:
                pass
    start = value.find("{")
    if start >= 0:
        parsed, _ = json.JSONDecoder().raw_decode(value[start:])
        return parsed
    raise json.JSONDecodeError("no JSON object found", value, 0)


def judge(value: dict) -> tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != {
        "identified_framework", "paper_evidence", "pipeline"
    }:
        return False, "invalid response schema"
    text = json.dumps(value, ensure_ascii=False).lower()
    named = "a posteriori" in text and ("time series aggregation" in text or "tsa" in text)
    stages = all(any(term in text for term in alternatives) for alternatives in (
        ("a priori", "initial aggregation", "initial clustering"),
        ("preliminary", "initial capacity"),
        ("full-series", "full series", "full time series"),
        ("importance", "extreme"),
        ("chronolog", "inter-period", "inter period"),
        ("re-opt", "reopt", "final capacity", "final optimal", "redesign", "second planning"),
    ))
    evidence = isinstance(value["paper_evidence"], list) and len(value["paper_evidence"]) >= 2
    passed = named and stages and evidence
    return passed, ("complete two-stage storage-aware a-posteriori framework identified"
                    if passed else "framework, stages, or paper evidence incomplete")


def run_with_rate_limit_retries(env: dict[str, str], prompt: str, public: Path,
                                timeout: float) -> tuple[str, str, str, list[str]]:
    failures: list[str] = []
    models = [env["MODEL_NAME"]]
    fallback = env.get("FALLBACK_MODEL_NAME")
    if fallback and fallback != models[0]:
        models.append(fallback)
    for model_index, model in enumerate(models):
        attempts = 1 if model_index == 0 and len(models) > 1 else 6
        model_env = {**env, "MODEL_NAME": model}
        for attempt in range(1, attempts + 1):
            try:
                answer, actual = run_context(model_env, prompt, public, timeout)
                return answer, model, actual, failures
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None
                if status != 429:
                    raise
                failures.append(f"model {model}: attempt {attempt}: upstream_429")
                final_attempt = model_index == len(models) - 1 and attempt == attempts
                if final_attempt:
                    error.g6_transient_failures = failures
                    raise
                if attempt < attempts:
                    time.sleep(min(5 * attempt, 30))
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--rejudge-existing", action="store_true")
    args = parser.parse_args()
    if args.rejudge_existing:
        report = json.loads(DESTINATION.read_text())
        runs = report.get("runs", [])
        if len(runs) != 3 or any(not isinstance(row.get("answer"), dict) for row in runs):
            raise RuntimeError("existing report does not contain three structured answers")
        for row in runs:
            row["passed"], row["judgment"] = judge(row["answer"])
        pass_count = sum(row["passed"] for row in runs)
        report["pass_count"] = pass_count
        report["G6"] = "PASS" if pass_count >= 2 else "FAIL"
        report["rejudged_at"] = datetime.now(timezone.utc).isoformat()
        report["judge_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        temporary = DESTINATION.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True,
                                        ensure_ascii=False) + "\n")
        os.replace(temporary, DESTINATION)
        if report["G6"] != "PASS":
            raise RuntimeError(f"G6 failed after rejudge: {pass_count}/3")
        return
    env = read_env(args.env_file)
    public = TASK / "public"
    with tempfile.TemporaryDirectory(prefix="scibench_0018_core_g6_") as temporary:
        text_path = Path(temporary) / "paper.txt"
        subprocess.run(["pdftotext", "-layout", str(public / "paper.pdf"), str(text_path)],
                       check=True, timeout=120)
        paper = text_path.read_text(encoding="utf-8")
    prompt = (
        "You are a blind scientific benchmark reviewer. You have a read-only file tool "
        "restricted to the final public bundle. Identify the one complete scientific "
        "framework from the paper that maps the public numeric inputs to all public outputs. "
        "Distinguish the complete core framework from baselines and incomplete variants. "
        "Inspect public cases as needed. Return JSON with exactly: identified_framework "
        "(string), paper_evidence (array of at least two objects with page_or_section and "
        "concise_quote), and pipeline (ordered array of concise stage descriptions). Do not "
        "propose code. No repository, curator files, hidden cases, prior conversations, or "
        "network are available.\n\nCOMPLETE PAPER TEXT\n" + paper
    )
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    runs = []
    for index in range(1, 4):
        try:
            answer, requested, actual, transient_failures = run_with_rate_limit_retries(
                env, prompt, public, args.timeout)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            blocked = {
                "schema_version": 1,
                "task_id": TASK.name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "G6": "BLOCKED",
                "configured_model": env["MODEL_NAME"],
                "fallback_model": env.get("FALLBACK_MODEL_NAME"),
                "blocked_context": index,
                "http_status": status,
                "transient_failures": getattr(error, "g6_transient_failures", []),
                "completed_contexts": runs,
                "prompt": prompt,
                "prompt_sha256": prompt_hash,
                "file_tool_isolation": "read-only and path-confined to final public bundle",
                "redaction": "credentials, endpoint, provider/user/request IDs, and raw envelopes not retained",
            }
            DESTINATION.parent.mkdir(parents=True, exist_ok=True)
            temporary = DESTINATION.with_suffix(".tmp")
            temporary.write_text(json.dumps(blocked, indent=2, sort_keys=True,
                                            ensure_ascii=False) + "\n")
            os.replace(temporary, DESTINATION)
            raise RuntimeError(f"G6 externally blocked: HTTP {status}") from error
        try:
            value = clean_json(answer)
        except Exception:
            value = {"identified_framework": "", "paper_evidence": [], "pipeline": [answer[:4000]]}
        passed, judgment = judge(value)
        runs.append({
            "run": index,
            "configured_model": env["MODEL_NAME"],
            "fallback_model": env.get("FALLBACK_MODEL_NAME"),
            "requested_model": requested,
            "actual_model": actual,
            "prompt_sha256": prompt_hash,
            "answer": value,
            "passed": passed,
            "judgment": judgment,
            "transient_failures": transient_failures,
        })
    pass_count = sum(row["passed"] for row in runs)
    report = {
        "schema_version": 1,
        "task_id": TASK.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "G6": "PASS" if pass_count >= 2 else "FAIL",
        "configured_model": env["MODEL_NAME"],
        "fallback_model": env.get("FALLBACK_MODEL_NAME"),
        "threshold": "at least 2/3 identify the same complete framework",
        "pass_count": pass_count,
        "independent_contexts": 3,
        "prompt": prompt,
        "prompt_sha256": prompt_hash,
        "public_bundle_files": [path.relative_to(public).as_posix()
                                for path in sorted(public.rglob("*")) if path.is_file()],
        "runs": runs,
        "file_tool_isolation": "read-only and path-confined to final public bundle",
        "redaction": "credentials, endpoint, provider/user/request IDs, and raw envelopes not retained",
    }
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    temporary = DESTINATION.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(temporary, DESTINATION)
    if report["G6"] != "PASS":
        raise RuntimeError(f"G6 failed: {pass_count}/3")


if __name__ == "__main__":
    main()
