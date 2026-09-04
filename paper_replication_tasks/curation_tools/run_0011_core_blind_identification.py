#!/usr/bin/env python3
"""Run the 0011_core G6 gate in three independent configured-model contexts."""

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
PUBLIC = ROOT / "curation_reports/official_runs/0011_core_feasibility/public_bundle"


def clean_json(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for start, character in enumerate(value):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(value[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"raw_response": value}


def judge(value: dict) -> tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "invalid response schema"
    text = json.dumps(value, ensure_ascii=False).lower()
    bayesian = "bayesian" in text and ("posterior" in text or "mcmc" in text)
    covariance = "covariance" in text and ("free" in text or "recondition" in text or "minimum eigen" in text)
    identified = value.get("identified_algorithm", value.get("raw_response", ""))
    not_baseline = "raw_response" in value or not any(
        name in identified.lower() for name in ("ordinary least squares", "weighted least squares", "random walk generation")
    )
    if "raw_response" in value:
        evidence = any(marker in text for marker in ("eqn.", "equation", "section", "paper"))
    else:
        evidence = isinstance(value.get("paper_evidence"), list) and len(value["paper_evidence"]) >= 1
    passed = bayesian and covariance and not_baseline and evidence
    return passed, "complete approximate Bayesian MSD regression identified" if passed else "target, covariance stage, or paper evidence missing"


def run_with_rate_limit_retries(env: dict[str, str], prompt: str, timeout: float) -> tuple[str, str, str, list[str]]:
    failures = []
    models = [env["MODEL_NAME"]]
    fallback = env.get("FALLBACK_MODEL_NAME")
    if fallback and fallback != models[0]:
        models.append(fallback)
    for model_index, model in enumerate(models):
        attempts = 1 if model_index == 0 and len(models) > 1 else 6
        model_env = {**env, "MODEL_NAME": model}
        for attempt in range(1, attempts + 1):
            try:
                answer, actual = run_context(model_env, prompt, PUBLIC, timeout)
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
    args = parser.parse_args()
    env = read_env(args.env_file)
    with tempfile.TemporaryDirectory(prefix="scibench_0011_core_g6_") as temporary:
        paper_text = Path(temporary) / "paper.txt"
        subprocess.run(["pdftotext", str(PUBLIC / "paper.pdf"), str(paper_text)], check=True, timeout=120)
        paper = paper_text.read_text(encoding="utf-8")
    prompt = (
        "You are a blind scientific benchmark reviewer. You have a read-only file tool restricted to the complete public benchmark bundle. "
        "Identify the one specific method from the paper that a submission must implement to map the public numeric inputs to outputs. "
        "Inspect all public cases as needed. Return JSON with exactly identified_algorithm (string), paper_evidence "
        "(array of objects containing page_or_section and concise_quote), and reasoning (string). Do not propose code. "
        "No repository, curator material, hidden cases, or network is available.\n\nCOMPLETE PAPER TEXT\n" + paper
    )
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    runs = []
    for index in range(1, 4):
        try:
            answer, requested, actual, transient_failures = run_with_rate_limit_retries(env, prompt, args.timeout)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            blocked = {
                "schema_version": 1,
                "task_id": "scibench_replication_0011_core",
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
                "file_tool_isolation": "read-only and path-confined to provisional public bundle",
                "redaction": "credentials, endpoint, provider/request/response IDs, and raw envelopes not retained",
            }
            destination = ROOT / "core_algorithm_audits/0011_core_blind.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(blocked, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            os.replace(temporary, destination)
            raise RuntimeError(f"G6 externally blocked: HTTP {status}") from error
        value = clean_json(answer)
        passed, judgment = judge(value)
        runs.append({
            "run": index,
            "configured_model": env["MODEL_NAME"],
            "requested_model": requested,
            "actual_model": actual,
            "prompt_sha256": prompt_hash,
            "answer": value,
            "passed": passed,
            "judgment": judgment,
            "transient_failures": transient_failures,
        })
    count = sum(row["passed"] for row in runs)
    report = {
        "schema_version": 1,
        "task_id": "scibench_replication_0011_core",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "G6": "PASS" if count >= 2 else "FAIL",
        "threshold": "at least 2/3",
        "pass_count": count,
        "independent_contexts": 3,
        "prompt_sha256": prompt_hash,
        "prompt": prompt,
        "runs": runs,
        "public_bundle_sha256": json.loads((ROOT / "curation_reports/0011_core_feasibility.json").read_text())["public_bundle_sha256"],
        "file_tool_isolation": "read-only and path-confined to provisional public bundle",
        "redaction": "credentials, endpoint, provider/request/response IDs, and raw envelopes not retained",
    }
    destination = ROOT / "core_algorithm_audits/0011_core_blind.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    if report["G6"] != "PASS":
        raise RuntimeError(f"G6 failed: {count}/3")


if __name__ == "__main__":
    main()
