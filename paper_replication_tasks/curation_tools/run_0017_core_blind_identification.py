#!/usr/bin/env python3
"""Run G6 in three independent model contexts with restricted public file tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sobiEquity_core_blind_common import read_env, run_context

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0017_core"


def clean_json(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(value)


def judge(value: dict) -> tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != {"identified_algorithm", "paper_evidence", "reasoning"}:
        return False, "invalid response schema"
    text = json.dumps(value, ensure_ascii=False).lower()
    target = "balanced floating catchment" in text or "bfca" in text or "b2sfca" in text
    evidence = isinstance(value["paper_evidence"], list) and bool(value["paper_evidence"]) and ("paez" in text or "balanc" in text)
    return target and evidence, "BFCA identified with paper evidence" if target and evidence else "target or evidence mismatch"


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--env-file", type=Path, default=Path(".env")); parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(); env = read_env(args.env_file); public = TASK / "public"
    with tempfile.TemporaryDirectory(prefix="scibench_0017_core_g6_") as temporary:
        text_path = Path(temporary) / "paper.txt"
        subprocess.run(["pdftotext", str(public / "paper.pdf"), str(text_path)], check=True, timeout=120)
        paper = text_path.read_text(encoding="utf-8")
    prompt = ("You are a blind scientific benchmark reviewer. You have a read-only file tool restricted to the final public bundle. "
              "Identify the one specific method from the complete paper that maps the public inputs to outputs. Inspect the public cases and data as needed. "
              "Return JSON with exactly identified_algorithm (string), paper_evidence (array of objects containing page_or_section and concise_quote), and reasoning (string). "
              "Do not propose code. No repository, curator files, gold hidden data, or network are available.\n\nCOMPLETE PAPER TEXT\n" + paper)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest(); runs = []
    for index in range(1, 4):
        answer, actual = run_context(env, prompt, public, args.timeout)
        try: value = clean_json(answer)
        except Exception: value = {"identified_algorithm": "", "paper_evidence": [], "reasoning": answer[:4000]}
        passed, judgment = judge(value)
        runs.append({"run": index, "configured_model": env["MODEL_NAME"], "actual_model": actual, "prompt_sha256": prompt_hash, "answer": value, "passed": passed, "judgment": judgment})
    count = sum(row["passed"] for row in runs)
    report = {"schema_version": 1, "task_id": TASK.name, "generated_at": datetime.now(timezone.utc).isoformat(), "G6": "PASS" if count >= 2 else "FAIL", "threshold": "at least 2/3", "pass_count": count, "independent_contexts": 3, "prompt_sha256": prompt_hash, "prompt": prompt, "runs": runs, "file_tool_isolation": "read-only and path-confined to final public bundle", "redaction": "credentials, endpoint, IDs, and raw envelopes not retained"}
    destination = ROOT / "core_algorithm_audits/0017_core_blind.json"; destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp"); temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"); os.replace(temporary, destination)
    if report["G6"] != "PASS": raise RuntimeError(f"G6 failed: {count}/3")


if __name__ == "__main__": main()
