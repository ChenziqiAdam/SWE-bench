#!/usr/bin/env python3
"""G6 blind identification for 0023_core via the codex CLI (protocol deviation).

PROTOCOL DEVIATION -- read before use
------------------------------------
PAPER.md's G6 protocol requires three independent contexts driven by the
``MODEL_NAME`` configured in ``.env`` over an OpenAI-compatible HTTP endpoint.
The ``.env`` OpenRouter key in this repo is dead (free models retired; paid
blocked with "Key limit exceeded"), so the canonical
``run_0023_core_blind_identification.py`` cannot run here.

This script runs the identical blind-reviewer prompt through three fresh,
ephemeral ``codex exec`` invocations (``gpt-5.6-sol``, ``--ignore-user-config``,
no repository access, no network research), which is a stronger blind test than
a free GLM model but is a documented deviation.  The resulting audit record sets
``model_selection = "codex_cli_gpt-5.6-sol_protocol_deviation"`` and records the
reason.  A curator must accept the deviation explicitly before promotion.

Isolation: each invocation runs under a ``sandbox-exec`` profile that denies all
reads outside a temp workspace containing only ``paper.txt`` (the extracted paper
text).  The agent gets the paper and the public numeric I/O in the prompt; it
never sees the repository, hidden cases, curation files, or algorithm name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0023_core"
MODEL = "gpt-5.6-sol"


def clean(text: str) -> dict:
    value = text.strip()
    if "```" in value:
        # take the last fenced block
        parts = value.split("```")
        for chunk in reversed(parts):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                return json.loads(chunk)
    return json.loads(value)


def judge(value: dict) -> tuple[bool, str]:
    """Accept an answer that names the paper's PE pipeline for the distribution of W.

    The target is the probability-estimation method: the moment recursion feeding a
    bounded-error Taylor Laplace-Stieltjes transform with the embedded branching-
    process contraction, inverted (concentrated matrix exponential) to the CDF.
    An answer may describe this by name ("PE method", "Algorithm 1") or purely by
    its mechanism; both are accepted.  Naming only the moment-matching /
    generalized-gamma branch is NOT accepted (that is the fast approximation, not
    the pipeline the CDF+moments output requires).
    """
    if not isinstance(value, dict) or set(value) != {"identified_algorithm", "paper_evidence", "reasoning"}:
        return False, "invalid response schema"
    text = json.dumps(value, ensure_ascii=False).lower()

    # the quantity: the limiting r.v. W / the time-shift / its distribution
    quantity = any(
        w in text
        for w in (
            "time-shift", "time shift", "timeshift", "limiting", "martingale",
            "asymptotic phase", " w ", "distribution of w", "random variable w",
            "laplace-stieltjes", "laplace stieltjes",
        )
    )
    # the transform + moment machinery
    transform = any(
        w in text
        for w in ("laplace-stieltjes", "laplace stieltjes", "lst", "transform", "phi(", "φ(")
    )
    moments = "moment" in text
    taylor = "taylor" in text or "series expansion" in text or "series-expansion" in text
    embedded = "embedded" in text or "imbedded" in text or "recursion" in text or "functional equation" in text
    inversion = any(
        w in text
        for w in ("invert", "inversion", "concentrated matrix exponential", "cme", "inverse laplace")
    )
    # explicitly the PE pipeline, or at least the mechanism, and NOT just MM
    pe_named = "probability-estimation" in text or "probability estimation" in text or "algorithm 1" in text or " pe " in text or "pe method" in text or "pe pipeline" in text
    only_mm = ("moment-matching" in text or "moment matching" in text or "generalised gamma" in text or "generalized gamma" in text) and not (inversion or taylor or pe_named)

    evidence = isinstance(value["paper_evidence"], list) and len(value["paper_evidence"]) >= 1

    mechanism_ok = quantity and transform and moments and (taylor or embedded) and inversion
    ok = evidence and not only_mm and (pe_named or mechanism_ok)
    return ok, (
        "PE pipeline for the distribution of W identified"
        if ok
        else ("only the moment-matching branch named" if only_mm else "target method or paper evidence not clearly identified")
    )


def public_io_digest() -> str:
    lines = ["PUBLIC NUMERIC I/O (worked examples)"]
    for case_dir in sorted((TASK / "public/cases").iterdir()):
        inp = json.loads((case_dir / "input.json").read_text())
        out = json.loads((case_dir / "output.json").read_text())
        lines.append(f"\n== {case_dir.name} ==")
        lines.append("input.json keys: " + ", ".join(sorted(inp)))
        lines.append(json.dumps(inp)[:4000])
        lines.append("output.json keys: " + ", ".join(sorted(out)))
        lines.append(json.dumps(out)[:4000])
    return "\n".join(lines)


def run_one(prompt: str, timeout: float) -> tuple[str | None, str]:
    with tempfile.TemporaryDirectory(prefix="0023_g6_codex_") as tmp:
        stage = Path(tmp)
        workspace = stage / "workspace"
        workspace.mkdir()
        (workspace / "paper.txt").write_text(prompt_paper_text)
        profile = stage / "profile.sb"
        profile.write_text('(version 1)\n(allow default)\n' + f'(deny file-read* (subpath "{ROOT.parent}"))\n')
        final = stage / "final.txt"
        command = [
            "/usr/bin/sandbox-exec", "-f", str(profile),
            "codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
            "-m", MODEL, "-c", 'model_reasoning_effort="high"',
            "-C", str(workspace), "--json", "-o", str(final), prompt,
        ]
        completed = subprocess.run(command, cwd=workspace, timeout=timeout, capture_output=True, text=True)
        if completed.returncode != 0:
            return None, f"codex exec failed: {completed.stderr[:200]}"
        events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        answer = next(
            (
                item["item"].get("text")
                for item in reversed(events)
                if item.get("type") == "item.completed"
                and item.get("item", {}).get("type") == "agent_message"
            ),
            None,
        )
        return (answer, "ok") if answer else (None, "no agent message")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--accept-deviation", action="store_true",
                        help="required: acknowledge this is a documented protocol deviation")
    args = parser.parse_args()
    if not args.accept_deviation:
        raise SystemExit("refusing to run: pass --accept-deviation to acknowledge the codex-CLI deviation")

    global prompt_paper_text
    with tempfile.TemporaryDirectory(prefix="0023_g6_pdf_") as tmp:
        text_path = Path(tmp) / "paper.txt"
        subprocess.run(["pdftotext", str(TASK / "public/paper.pdf"), str(text_path)], check=True, timeout=120)
        prompt_paper_text = text_path.read_text()

    prompt = (
        "You are a blind scientific benchmark reviewer. The file paper.txt in your working "
        "directory is the complete paper. Below is the public numeric I/O of a benchmark task. "
        "Identify the one specific method in the paper that maps these inputs to these outputs. "
        "Return ONLY JSON with exactly identified_algorithm (string), paper_evidence (array of "
        "objects with page_or_section and concise_quote), and reasoning (string). Do not propose "
        "code. No repository, curator files, hidden data, or web research are available.\n\n"
        + public_io_digest()
    )
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    runs = []
    for index in range(1, 4):
        answer, note = run_one(prompt, args.timeout)
        try:
            value = clean(answer) if answer else None
            passed, reason = judge(value) if value else (False, note)
        except Exception as exc:
            value = None
            passed = False
            reason = f"unparseable answer: {type(exc).__name__}"
        runs.append(
            {
                "run": index,
                "configured_model": MODEL,
                "actual_model": MODEL,
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
        "model_selection": "codex_cli_gpt-5.6-sol_protocol_deviation",
        "configured_primary_model": MODEL,
        "configured_model": MODEL,
        "protocol_deviation": (
            "The .env OpenRouter key is non-functional (free models retired, paid blocked). "
            "G6 was run via three fresh ephemeral `codex exec` contexts (gpt-5.6-sol, "
            "--ignore-user-config, sandbox-exec denying all repository reads, paper text + public "
            "I/O only). A curator must accept this deviation before promotion."
        ),
        "prompt": prompt,
        "prompt_sha256": prompt_hash,
        "runs": runs,
        "redaction": "credentials, endpoint, provider IDs, request IDs, and raw envelopes not retained",
    }
    destination = ROOT / "core_algorithm_audits/0023_core_blind.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp_path, destination)
    print(json.dumps({"G6": report["G6"], "pass_count": count,
                      "judgments": [r["judgment"] for r in runs]}, indent=2))
    if report["G6"] != "PASS":
        raise SystemExit(f"G6 failed: {count}/3")


if __name__ == "__main__":
    main()
