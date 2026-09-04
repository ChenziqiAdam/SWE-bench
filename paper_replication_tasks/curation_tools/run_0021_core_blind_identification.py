#!/usr/bin/env python3
"""Run G6 in three independent contexts against only the final public bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sobiEquity_core_blind_common import read_env, run_context

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0021_core"


def clean(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"): value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(value)


def judge(value: dict) -> tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != {"identified_algorithm", "paper_evidence", "reasoning"}:
        return False, "invalid response schema"
    text = json.dumps(value, ensure_ascii=False).lower()
    named = "reim" in text or "rational empirical interpolation" in text or "rational approximation via the eim" in text
    evidence = isinstance(value["paper_evidence"], list) and bool(value["paper_evidence"]) and ("algorithm 2.1" in text or "greedy" in text)
    shared = "shared" in text or "family" in text or "invariant" in text
    return named and evidence and shared, "rEIM with paper evidence and shared-basis purpose" if named and evidence and shared else "target/evidence mismatch"


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--env-file", type=Path, default=Path(".env")); parser.add_argument("--timeout", type=float, default=600); parser.add_argument("--use-fallback", action="store_true"); args = parser.parse_args()
    env = read_env(args.env_file)
    configured_primary = env["MODEL_NAME"]
    if args.use_fallback:
        if not env.get("FALLBACK_MODEL_NAME"): raise RuntimeError("FALLBACK_MODEL_NAME is not configured")
        env["MODEL_NAME"] = env["FALLBACK_MODEL_NAME"]
    model_selection = "user_authorized_FALLBACK_MODEL_NAME" if args.use_fallback else "MODEL_NAME"
    public = TASK / "public"
    with tempfile.TemporaryDirectory(prefix="scibench_0021_core_g6_") as temporary:
        text_path = Path(temporary) / "paper.txt"; subprocess.run(["pdftotext", str(public / "paper.pdf"), str(text_path)], check=True, timeout=120); paper = text_path.read_text()
    prompt = ("You are a blind scientific benchmark reviewer. You may inspect only the final public bundle. Identify the one specific method in the complete paper that maps the public numeric inputs to outputs. "
              "Return JSON with exactly identified_algorithm (string), paper_evidence (array of objects with page_or_section and concise_quote), and reasoning (string). Do not propose code. No repository, curator files, hidden data, or network are available.\n\nCOMPLETE PAPER TEXT\n" + paper)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest(); runs = []
    for index in range(1, 4):
        try:
            answer, actual = run_context(env, prompt, public, args.timeout)
        except Exception as exc:
            category = "HTTP 429" if "429" in str(exc) else type(exc).__name__
            runs.append({"run": index, "configured_model": env["MODEL_NAME"], "actual_model": None, "prompt_sha256": prompt_hash, "answer": None, "passed": False, "judgment": f"no answer: {category}"})
            break
        try: value = clean(answer)
        except Exception: value = {"identified_algorithm": "", "paper_evidence": [], "reasoning": answer[:4000]}
        passed, judgment = judge(value); runs.append({"run": index, "configured_model": env["MODEL_NAME"], "actual_model": actual, "prompt_sha256": prompt_hash, "answer": value, "passed": passed, "judgment": judgment})
    count = sum(row["passed"] for row in runs)
    report = {"schema_version": 1, "task_id": TASK.name, "generated_at": datetime.now(timezone.utc).isoformat(), "G6": "PASS" if count >= 2 else "FAIL", "threshold": "at least 2/3", "pass_count": count, "independent_contexts_required": 3, "completed_contexts": sum(row["answer"] is not None for row in runs), "model_selection": model_selection, "configured_primary_model": configured_primary, "protocol_deviation": "User explicitly authorized FALLBACK_MODEL_NAME after primary HTTP 429." if args.use_fallback else None, "prompt": prompt, "prompt_sha256": prompt_hash, "runs": runs, "redaction": "credentials, endpoint, provider IDs, and raw envelopes not retained"}
    destination = ROOT / "core_algorithm_audits/0021_core_blind.json"; destination.parent.mkdir(parents=True, exist_ok=True)
    if args.use_fallback and destination.is_file():
        archived = ROOT / "core_algorithm_audits/failed_attempts/0021_core_g6_primary_429.json"; archived.parent.mkdir(parents=True, exist_ok=True)
        if not archived.exists(): shutil.copyfile(destination, archived)
    temporary = destination.with_suffix(".tmp"); temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"); os.replace(temporary, destination)
    if report["G6"] != "PASS": raise RuntimeError(f"G6 failed: {count}/3")


if __name__ == "__main__": main()
