#!/usr/bin/env python3
"""Formal G6 for 0023_core: three independent configured-model reviews of the public bundle.

The blind reviewer sees only the complete paper and the public numeric I/O.  It
must name the one method that maps the branching-process inputs to the CDF /
moments / extinction-probability outputs, with paper evidence.  >= 2/3 must
identify the random-time-shift distribution computation (moment engine + LST
inversion + moment matching).
"""

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
TASK = ROOT / "scibench_replication_0023_core"


def clean(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(value)


def judge(value: dict) -> tuple[bool, str]:
    if not isinstance(value, dict) or set(value) != {"identified_algorithm", "paper_evidence", "reasoning"}:
        return False, "invalid response schema"
    text = json.dumps(value, ensure_ascii=False).lower()
    # Target: the paper's probability-estimation (PE) pipeline for the distribution
    # of the limiting r.v. W -- the moment recursion feeding a bounded-error Taylor
    # Laplace-Stieltjes transform with the embedded branching-process contraction,
    # inverted (concentrated matrix exponential) to the CDF.  Accept a by-name
    # ("PE method", "Algorithm 1") or a by-mechanism identification; reject naming
    # only the moment-matching / generalized-gamma branch.
    quantity = any(
        w in text
        for w in (
            "time-shift", "time shift", "timeshift", "limiting", "martingale",
            "asymptotic phase", "distribution of w", "random variable w",
            "laplace-stieltjes", "laplace stieltjes",
        )
    )
    transform = any(w in text for w in ("laplace-stieltjes", "laplace stieltjes", "lst", "transform", "phi(", "φ("))
    moments = "moment" in text
    taylor = "taylor" in text or "series expansion" in text
    embedded = "embedded" in text or "imbedded" in text or "recursion" in text or "functional equation" in text
    inversion = any(w in text for w in ("invert", "inversion", "concentrated matrix exponential", "cme", "inverse laplace"))
    pe_named = any(w in text for w in ("probability-estimation", "probability estimation", "algorithm 1", "pe method", "pe pipeline"))
    only_mm = (
        "moment-matching" in text or "moment matching" in text
        or "generalised gamma" in text or "generalized gamma" in text
    ) and not (inversion or taylor or pe_named)
    evidence = isinstance(value["paper_evidence"], list) and len(value["paper_evidence"]) >= 1
    mechanism_ok = quantity and transform and moments and (taylor or embedded) and inversion
    ok = evidence and not only_mm and (pe_named or mechanism_ok)
    return ok, (
        "PE pipeline for the distribution of W identified"
        if ok
        else ("only the moment-matching branch named" if only_mm else "target method or paper evidence not clearly identified")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--use-fallback", action="store_true")
    args = parser.parse_args()

    env = read_env(args.env_file)
    primary = env["MODEL_NAME"]
    if args.use_fallback:
        if not env.get("FALLBACK_MODEL_NAME"):
            raise RuntimeError("FALLBACK_MODEL_NAME is not configured")
        env["MODEL_NAME"] = env["FALLBACK_MODEL_NAME"]
    model_selection = "user_authorized_FALLBACK_MODEL_NAME" if args.use_fallback else "MODEL_NAME"

    public = TASK / "public"
    with tempfile.TemporaryDirectory(prefix="0023_core_g6_") as temporary:
        text = Path(temporary) / "paper.txt"
        subprocess.run(["pdftotext", str(public / "paper.pdf"), str(text)], check=True, timeout=120)
        paper = text.read_text()

    prompt = (
        "You are a blind scientific benchmark reviewer. You may inspect only the final "
        "public bundle. Identify the one specific method in the complete paper that maps "
        "the public numeric inputs to the public numeric outputs. Return JSON with exactly "
        "identified_algorithm (string), paper_evidence (array of objects with page_or_section "
        "and concise_quote), and reasoning (string). Do not propose code. No repository, "
        "curator files, hidden data, or network are available.\n\nCOMPLETE PAPER TEXT\n" + paper
    )
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    runs = []
    for index in range(1, 4):
        try:
            answer, actual = run_context(env, prompt, public, args.timeout)
            value = clean(answer)
            passed, reason = judge(value)
        except Exception as exc:
            actual = None
            value = None
            passed = False
            reason = f"no valid answer: {'HTTP 429' if '429' in str(exc) else type(exc).__name__}"
        runs.append(
            {
                "run": index,
                "configured_model": env["MODEL_NAME"],
                "actual_model": actual,
                "prompt_sha256": prompt_hash,
                "answer": value,
                "passed": passed,
                "judgment": reason,
            }
        )

    count = sum(x["passed"] for x in runs)
    report = {
        "schema_version": 1,
        "task_id": TASK.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "G6": "PASS" if count >= 2 else "FAIL",
        "threshold": "at least 2/3",
        "pass_count": count,
        "independent_contexts_required": 3,
        "completed_contexts": sum(x["answer"] is not None for x in runs),
        "model_selection": model_selection,
        "configured_primary_model": primary,
        "configured_model": env["MODEL_NAME"],
        "protocol_deviation": "User explicitly authorized FALLBACK_MODEL_NAME after primary HTTP 429."
        if args.use_fallback
        else None,
        "prompt": prompt,
        "prompt_sha256": prompt_hash,
        "runs": runs,
        "redaction": "credentials, endpoint, provider IDs, request IDs, and raw envelopes not retained",
    }
    destination = ROOT / "core_algorithm_audits/0023_core_blind.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if args.use_fallback and destination.is_file():
        archived = ROOT / "core_algorithm_audits/failed_attempts/0023_core_g6_primary_429.json"
        archived.parent.mkdir(parents=True, exist_ok=True)
        if not archived.exists():
            shutil.copyfile(destination, archived)
    tmp = destination.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, destination)
    if report["G6"] != "PASS":
        raise RuntimeError(f"G6 failed: {count}/3")


if __name__ == "__main__":
    main()
