#!/usr/bin/env python3
"""Run three isolated G6 identifications from the strict public bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0015_core"


def read_env(path: Path) -> dict[str, str]:
    allowed = {"ENDPOINT", "API_KEY", "MODEL_NAME"}; result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"): continue
        key, value = raw.split("=", 1); key = key.strip(); value = value.strip().strip("'\"")
        if key in allowed: result[key] = value
    missing = allowed - result.keys()
    if missing: raise RuntimeError(f"missing .env fields: {sorted(missing)}")
    return result


def public_prompt(task: Path, paper_text: str) -> str:
    schema = (task / "public/interface.schema.json").read_text(encoding="utf-8")
    instruction = (task / "public/task.md").read_text(encoding="utf-8")
    examples = []
    for case in sorted((task / "public/cases").iterdir()):
        examples.append({"input": json.loads((case / "input.json").read_text()), "output": json.loads((case / "output.json").read_text())})
    return (
        "You are a blind scientific benchmark reviewer. You may use only the public bundle below. "
        "Identify the one specific method from the paper that a submission must implement to map these inputs to outputs. "
        "Return JSON with exactly: identified_algorithm (string), paper_evidence (array of objects with page_or_section and concise_quote), "
        "reasoning (string). Cite the paper, not the examples. Do not propose code.\n\n"
        f"TASK INSTRUCTION\n{instruction}\nINTERFACE SCHEMA\n{schema}\nPUBLIC NUMERIC EXAMPLES\n"
        f"{json.dumps(examples, separators=(',', ':'))}\nCOMPLETE PAPER TEXT\n{paper_text}"
    )


def judge(value: dict) -> tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != {"identified_algorithm", "paper_evidence", "reasoning"}:
        return False, "invalid response schema"
    text = " ".join((str(value["identified_algorithm"]), str(value["reasoning"]), json.dumps(value["paper_evidence"]))).lower()
    algorithm = (("fixed-spars" in text or "fixed sparse" in text)
                 and ("least square" in text or "least-square" in text) and "gaussian" in text)
    evidence = ("algorithm 2.1" in text or "section 2" in text) and isinstance(value["paper_evidence"], list) and bool(value["paper_evidence"])
    return algorithm and evidence, "identified section-2 Gaussian fixed-sparsity row least-squares method with paper evidence" if algorithm and evidence else "target or evidence mismatch"


def normalize_answer(value: dict) -> dict:
    """Accept a provider's redundant JSON object inside the reasoning string."""
    if value.get("identified_algorithm") or value.get("paper_evidence") or not isinstance(value.get("reasoning"), str):
        return value
    text = value["reasoning"].strip()
    start, stop = text.find("{"), text.rfind("}")
    if start >= 0 and stop > start:
        try:
            nested = json.loads(re.sub(r",\s*}", "}", text[start:stop + 1]))
        except json.JSONDecodeError:
            return value
        if isinstance(nested, dict) and set(nested) == {"identified_algorithm", "paper_evidence", "reasoning"}:
            return nested
    return value


def write_report(report: dict) -> None:
    destination = ROOT / "core_algorithm_audits/0015_core_blind.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--env-file", type=Path, default=Path(".env")); parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--regrade-existing", action="store_true")
    args = parser.parse_args()
    if args.regrade_existing:
        path = ROOT / "core_algorithm_audits/0015_core_blind.json"; report = json.loads(path.read_text(encoding="utf-8"))
        for row in report["runs"]:
            row["answer"] = normalize_answer(row["answer"]); row["passed"], row["judgment"] = judge(row["answer"])
        report["pass_count"] = sum(row["passed"] for row in report["runs"]); report["G6"] = "PASS" if report["pass_count"] >= 2 else "FAIL"
        report["regraded_at"] = datetime.now(timezone.utc).isoformat(); report["regrade_note"] = "Schema-only normalization of redundant nested JSON; no model calls or run selection."
        write_report(report)
        if report["G6"] != "PASS": raise RuntimeError(f"G6 failed: {report['pass_count']}/3")
        return
    env = read_env(args.env_file); task = ROOT / TASK_ID
    with tempfile.TemporaryDirectory(prefix="scibench_0015_core_blind_") as temporary:
        text_path = Path(temporary) / "paper.txt"
        subprocess.run(["pdftotext", str(task / "public/paper.pdf"), str(text_path)], check=True, timeout=120)
        prompt = public_prompt(task, text_path.read_text(encoding="utf-8"))
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    endpoint = env["ENDPOINT"].rstrip("/")
    if not endpoint.endswith("/chat/completions"): endpoint += "/chat/completions"
    runs = []
    for index in range(1, 4):
        for attempt in range(12):
            response = requests.post(endpoint, headers={"Authorization": f"Bearer {env['API_KEY']}", "Content-Type": "application/json"},
                                     json={"model": env["MODEL_NAME"], "messages": [{"role": "user", "content": prompt}],
                                           "temperature": 0.2, "max_tokens": 4000,
                                           "reasoning": {"effort": "minimal", "exclude": True}}, timeout=args.timeout)
            if response.status_code != 429: break
            delay = min(30.0, float(response.headers.get("Retry-After", 2 ** min(attempt, 4))))
            time.sleep(delay)
        response.raise_for_status()
        envelope = response.json(); content = envelope["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip(): raise RuntimeError("model returned no answer content")
        raw = content.strip()
        if raw.startswith("```"): raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try: value = normalize_answer(json.loads(raw))
        except json.JSONDecodeError: value = {"identified_algorithm": "", "paper_evidence": [], "reasoning": raw[:4000]}
        passed, judgment = judge(value)
        runs.append({"run": index, "prompt_sha256": prompt_hash, "model": env["MODEL_NAME"], "answer": value, "passed": passed, "judgment": judgment})
    pass_count = sum(row["passed"] for row in runs)
    report = {"schema_version": 1, "task_id": TASK_ID, "generated_at": datetime.now(timezone.utc).isoformat(),
              "G6": "PASS" if pass_count >= 2 else "FAIL", "threshold": "at least 2/3", "pass_count": pass_count,
              "independent_contexts": 3, "prompt_sha256": prompt_hash, "runs": runs,
              "redaction": "No credentials, endpoint, provider response IDs, or raw envelopes retained."}
    write_report(report)
    if report["G6"] != "PASS": raise RuntimeError(f"G6 failed: {pass_count}/3")


if __name__ == "__main__":
    main()
