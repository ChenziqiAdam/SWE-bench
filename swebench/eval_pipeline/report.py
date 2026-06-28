"""Stage 6: Aggregate agent evaluation results and render a single-column table.

The pipeline evaluates one thing: the agent's issue-resolution rate. Each
instance gets a status derived from its harness report.json (NOT the raw
`resolved` flag, which is vacuously true when FAIL_TO_PASS is empty):

    resolved   FAIL_TO_PASS.success non-empty AND FAIL_TO_PASS.failure empty
    unresolved any FAIL_TO_PASS failed (a real, scored miss)
    excluded   non-scorable: empty FAIL_TO_PASS (placeholder PR) or non-buildable
    errored    a prediction existed but no usable report (e.g. container 409)
    no-pred    no/empty model patch

Only `resolved`/`unresolved` count toward the denominator. This neutralises the
two integrity bugs from sci_agent_001: vacuous resolves (empty F2P) and swallowed
eval errors (missing report despite a submitted patch).
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

AGENT = "agent"


def collect_results(
    run_ids: dict[str, str],
    log_dir: str = "logs/run_evaluation",
    instance_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Read the agent run's per-instance report.json files.

    Returns {instance_id: {"f2p_success": int, "f2p_failure": int,
                           "has_report": bool}} for every instance that produced
    a harness report. Instances without a report are absent here; the renderer
    classifies them as errored/no-pred using the predictions file.

    run_ids maps {"agent": run_id}; any extra keys are honoured but the pipeline
    only passes the single agent run.
    """
    results: dict[str, dict] = {}

    for _level, run_id in run_ids.items():
        run_path = Path(log_dir) / run_id
        report_files = list(run_path.glob("*/*/report.json")) if run_path.exists() else []
        logger.info(f"Agent run ({run_id}): found {len(report_files)} per-instance report files")

        for report_file in report_files:
            try:
                with open(report_file) as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"Error reading {report_file}: {e}")
                continue
            for instance_id, info in data.items():
                if instance_ids is not None and instance_id not in instance_ids:
                    continue
                f2p = (info.get("tests_status") or {}).get("FAIL_TO_PASS") or {}
                results[instance_id] = {
                    "f2p_success": len(f2p.get("success") or []),
                    "f2p_failure": len(f2p.get("failure") or []),
                    "has_report": True,
                }

    return results


def _classify(
    instance_id: str,
    report: dict | None,
    buildable: bool,
    f2p_empty: bool,
    has_pred: bool,
) -> str:
    """Map a single instance to one of the five status strings (see module docstring)."""
    if not buildable or f2p_empty:
        return "excluded"
    if report is None or not report.get("has_report"):
        return "errored" if has_pred else "no-pred"
    if report["f2p_success"] > 0 and report["f2p_failure"] == 0:
        return "resolved"
    return "unresolved"


def _load_nonempty_prediction_ids(predictions_path: str | None) -> set[str]:
    """instance_ids whose agent prediction has a non-empty model_patch."""
    out: set[str] = set()
    if not predictions_path or not Path(predictions_path).exists():
        return out
    with open(predictions_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("model_patch") or "").strip():
                out.add(row["instance_id"])
    return out


def render_comparison_table(
    results: dict[str, dict],
    instances: list[dict],
    output_csv: str,
    build_validation: dict[str, dict] | None = None,
    predictions_path: str | None = None,
    run_config: dict | None = None,
) -> None:
    """Write a CSV and print the single-column agent resolution table."""
    meta = {inst["instance_id"]: inst for inst in instances}
    build_validation = build_validation or {}
    nonempty = _load_nonempty_prediction_ids(predictions_path)

    rows = []
    for instance_id in sorted(meta.keys()):
        inst = meta[instance_id]
        bv = build_validation.get(instance_id, {})
        buildable = bv.get("buildable", True)
        f2p_empty = not (inst.get("FAIL_TO_PASS") or [])
        has_pred = instance_id in nonempty
        status = _classify(
            instance_id,
            results.get(instance_id),
            buildable=buildable,
            f2p_empty=f2p_empty,
            has_pred=has_pred,
        )
        rows.append({
            "instance_id": instance_id,
            "repo": inst.get("repo", ""),
            "pr_number": inst.get("pull_number", ""),
            "category": inst.get("category", ""),
            "buildable": "" if not build_validation else ("yes" if buildable else "no"),
            "status": status,
            "has_pred": "yes" if has_pred else "no",
        })

    # ── CSV ───────────────────────────────────────────────────────────────────
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["instance_id", "repo", "pr_number", "category",
                  "buildable", "status", "has_pred"]
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Results written to {output_csv}")

    # ── Counts ────────────────────────────────────────────────────────────────
    counts = {s: 0 for s in ("resolved", "unresolved", "excluded", "errored", "no-pred")}
    for r in rows:
        counts[r["status"]] += 1
    scorable = counts["resolved"] + counts["unresolved"]
    rate = counts["resolved"] / scorable if scorable else 0.0

    # ── Print ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"{'EVALUATION RESULTS':^78}")
    print("=" * 78)
    if run_config:
        print("RUN CONFIGURATION")
        for k, v in run_config.items():
            print(f"  {k:<28} {v}")
        print("-" * 78)
    print(f"{'Instance':<40} {'Build':^7} {'Status':^12}")
    print("-" * 78)
    for row in rows:
        print(f"{row['instance_id']:<40} {(row['buildable'] or '-'):^7} {row['status']:^12}")
    print("=" * 78)
    print(f"RESOLUTION RATE   {rate:6.1%}  ({counts['resolved']}/{scorable} scorable)")
    print(
        f"  resolved={counts['resolved']}  unresolved={counts['unresolved']}  "
        f"excluded={counts['excluded']}  errored={counts['errored']}  "
        f"no-pred={counts['no-pred']}"
    )
    if counts["errored"]:
        print(f"  ⚠ {counts['errored']} instance(s) errored (prediction submitted but no usable report).")
    print("=" * 78 + "\n")
