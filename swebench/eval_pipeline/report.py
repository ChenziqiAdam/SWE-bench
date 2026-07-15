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
                    "harness_resolved": bool(info.get("resolved")),
                    "has_report": True,
                }

    return results


def collect_test_generation_results(
    run_id: str,
    log_dir: str = "logs/run_evaluation",
    instance_ids: set[str] | None = None,
    model_name: str | None = None,
) -> dict[str, dict]:
    """Read per-instance generated-test report.json files."""
    results: dict[str, dict] = {}
    run_path = Path(log_dir) / run_id
    if not run_path.exists():
        report_files = []
    elif model_name:
        model_dir = model_name.replace("/", "__")
        report_files = list((run_path / model_dir).glob("*/report.json"))
    else:
        report_files = list(run_path.glob("*/*/report.json"))
    if instance_ids is not None:
        report_files = [p for p in report_files if p.parent.name in instance_ids]
    logger.info(f"Test-generation run ({run_id}): found {len(report_files)} report files")
    for report_file in report_files:
        try:
            data = json.loads(report_file.read_text())
        except Exception as e:
            logger.error(f"Error reading {report_file}: {e}")
            continue
        for instance_id, info in data.items():
            if instance_ids is not None and instance_id not in instance_ids:
                continue
            results[instance_id] = info
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


def _load_predictions(predictions_path: str | None) -> dict[str, dict]:
    """Load the latest prediction row per instance for report metadata."""
    out: dict[str, dict] = {}
    if not predictions_path or not Path(predictions_path).exists():
        return out
    with open(predictions_path) as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("instance_id"):
                out[row["instance_id"]] = row
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
    excluded_harness_resolved = sum(
        1
        for row in rows
        if row["status"] == "excluded"
        and (results.get(row["instance_id"]) or {}).get("harness_resolved")
    )
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
        print(f"  WARNING: {counts['errored']} instance(s) errored (prediction submitted but no usable report).")
    if excluded_harness_resolved:
        print(
            f"  NOTE: {excluded_harness_resolved} harness-resolved instance(s) were excluded "
            "from the scorable denominator because FAIL_TO_PASS was empty/non-evaluable."
        )
    print("=" * 78 + "\n")


def render_test_generation_table(
    results: dict[str, dict],
    instances: list[dict],
    output_csv: str,
    predictions_path: str | None = None,
    run_config: dict | None = None,
) -> None:
    """Write a CSV and print test-generation success results."""
    meta = {inst["instance_id"]: inst for inst in instances}
    nonempty = _load_nonempty_prediction_ids(predictions_path)
    predictions = _load_predictions(predictions_path)
    statuses = ("resolved", "unresolved", "excluded", "not_exercised", "errored", "no-pred")

    rows = []
    for instance_id in sorted(meta.keys()):
        inst = meta[instance_id]
        info = results.get(instance_id) or {}
        status = info.get("status")
        if not status:
            status = "errored" if instance_id in nonempty else "no-pred"
        metrics = (predictions.get(instance_id) or {}).get("metrics") or info.get(
            "inference_metrics"
        ) or {}
        rows.append({
            "instance_id": instance_id,
            "repo": inst.get("repo", ""),
            "pr_number": inst.get("pull_number", ""),
            "category": inst.get("category", ""),
            "status": status,
            "has_pred": "yes" if instance_id in nonempty else "no",
            "test_patch_applied": "yes" if info.get("test_patch_applied") else "no",
            "gold_patch_applied": "yes" if info.get("gold_patch_applied") else "no",
            "base_failed_tests": len(info.get("base_failed_tests") or []),
            "gold_passed_tests": len(info.get("gold_passed_tests") or []),
            "failure_reason": info.get("failure_reason", ""),
            "inference_wall_time_seconds": metrics.get("wall_time_seconds", ""),
            "provider_duration_seconds": metrics.get("provider_duration_seconds", ""),
            "input_tokens": metrics.get("input_tokens", ""),
            "output_tokens": metrics.get("output_tokens", ""),
            "cache_read_input_tokens": metrics.get("cache_read_input_tokens", ""),
            "cache_creation_input_tokens": metrics.get("cache_creation_input_tokens", ""),
            "total_tokens": metrics.get("total_tokens", ""),
            "cost_usd": metrics.get("cost_usd", ""),
            "turns": metrics.get("turns", ""),
            "evaluation_wall_time_seconds": info.get("evaluation_wall_time_seconds", ""),
            "base_test_wall_time_seconds": info.get("base_test_wall_time_seconds", ""),
            "gold_test_wall_time_seconds": info.get("gold_test_wall_time_seconds", ""),
        })

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "instance_id",
        "repo",
        "pr_number",
        "category",
        "status",
        "has_pred",
        "test_patch_applied",
        "gold_patch_applied",
        "base_failed_tests",
        "gold_passed_tests",
        "failure_reason",
        "inference_wall_time_seconds",
        "provider_duration_seconds",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "total_tokens",
        "cost_usd",
        "turns",
        "evaluation_wall_time_seconds",
        "base_test_wall_time_seconds",
        "gold_test_wall_time_seconds",
    ]
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Test-generation results written to {output_csv}")

    counts = {s: 0 for s in statuses}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    total = len(rows)
    rate = counts["resolved"] / total if total else 0.0

    print("\n" + "=" * 78)
    print(f"{'TEST-GENERATION RESULTS':^78}")
    print("=" * 78)
    if run_config:
        print("RUN CONFIGURATION")
        for k, v in run_config.items():
            print(f"  {k:<28} {v}")
        print("-" * 78)
    print(f"{'Instance':<40} {'Status':^12} {'Base F':^8} {'Gold P':^8}")
    print("-" * 78)
    for row in rows:
        print(
            f"{row['instance_id']:<40} {row['status']:^12} "
            f"{row['base_failed_tests']:^8} {row['gold_passed_tests']:^8}"
        )
    print("=" * 78)
    print(f"TEST-GENERATION SUCCESS RATE {rate:6.1%}  ({counts['resolved']}/{total})")
    print(
        f"  resolved={counts['resolved']}  unresolved={counts['unresolved']}  "
        f"excluded={counts['excluded']}  not_exercised={counts['not_exercised']}  "
        f"errored={counts['errored']}  no-pred={counts['no-pred']}"
    )
    def _sum(field: str) -> float:
        return sum(
            row[field] for row in rows if isinstance(row[field], (int, float))
        )

    print(
        "  tracked totals: "
        f"input={int(_sum('input_tokens'))} tokens, "
        f"output={int(_sum('output_tokens'))} tokens, "
        f"cache-read={int(_sum('cache_read_input_tokens'))} tokens, "
        f"cost=${_sum('cost_usd'):.6f}, "
        f"inference={_sum('inference_wall_time_seconds'):.1f}s, "
        f"evaluation={_sum('evaluation_wall_time_seconds'):.1f}s"
    )
    print("=" * 78 + "\n")


def render_coverage_generation_table(
    results: dict[str, dict],
    instances: list[dict],
    output_csv: str,
    predictions_path: str | None = None,
    run_config: dict | None = None,
) -> None:
    """Write coverage/mutation deltas and test-patch integrity metrics."""
    meta = {inst["instance_id"]: inst for inst in instances}
    nonempty = _load_nonempty_prediction_ids(predictions_path)
    predictions = _load_predictions(predictions_path)
    rows = []
    for instance_id in sorted(meta):
        inst = meta[instance_id]
        info = results.get(instance_id) or {}
        status = info.get("status") or ("errored" if instance_id in nonempty else "no-pred")
        before_cov = info.get("coverage_before") or {}
        after_cov = info.get("coverage_after") or {}
        before_mut = info.get("mutation_before") or {}
        after_mut = info.get("mutation_after") or {}
        prediction = predictions.get(instance_id) or {}
        metrics = prediction.get("metrics") or info.get("inference_metrics") or {}
        rows.append({
            "instance_id": instance_id,
            "repo": inst.get("repo", ""),
            "pr_number": inst.get("pull_number", ""),
            "category": inst.get("category", ""),
            "coverage_targets": ";".join(info.get("coverage_targets") or []),
            "coverage_scope": info.get("coverage_scope") or (
                "repository" if inst.get("standalone") else "targeted"
            ),
            "mutation_targets": ";".join(info.get("mutation_targets") or []),
            "mutation_skipped_no_selected_modules": (
                "yes" if info.get("mutation_skipped_no_selected_modules") else "no"
            ),
            "base_commit": info.get("base_commit", inst.get("base_commit", "")),
            "status": status,
            "failure_reason": info.get("failure_reason") or prediction.get("error", ""),
            "has_pred": "yes" if instance_id in nonempty else "no",
            "tests_only_patch": "yes" if info.get("tests_only_patch") else "no",
            "no_existing_test_lines_removed": (
                "yes" if info.get(
                    "no_existing_test_lines_removed",
                    info.get("preserves_existing_test_behavior", False),
                ) else "no"
            ),
            "illegal_changed_files": ";".join(info.get("illegal_changed_files") or []),
            "base_tests_passed": "yes" if info.get("base_tests_passed") else "no",
            "after_tests_passed": "yes" if info.get("after_tests_passed") else "no",
            "setup_before_exit_code": info.get("setup_before_exit_code", ""),
            "setup_after_exit_code": info.get("setup_after_exit_code", ""),
            "tools_before_exit_code": info.get("tools_before_exit_code", ""),
            "tools_after_exit_code": info.get("tools_after_exit_code", ""),
            "base_coverage_tests_passed": (
                "yes" if info.get("base_coverage_tests_passed") else "no"
            ),
            "after_coverage_tests_passed": (
                "yes" if info.get("after_coverage_tests_passed") else "no"
            ),
            "baseline_flaky": "yes" if info.get("baseline_flaky") else "no",
            "generated_tests_flaky": "yes" if info.get("generated_tests_flaky") else "no",
            "flaky": "yes" if info.get("flaky") else "no",
            "added_test_count": info.get("added_test_count", 0),
            "added_assertion_count": info.get("added_assertion_count", 0),
            "removed_test_line_count": info.get("removed_test_line_count", 0),
            "line_coverage_before": before_cov.get("line_coverage", ""),
            "line_coverage_after": after_cov.get("line_coverage", ""),
            "line_coverage_delta": info.get("coverage_line_delta", ""),
            "branch_coverage_before": before_cov.get("branch_coverage", ""),
            "branch_coverage_after": after_cov.get("branch_coverage", ""),
            "branch_coverage_delta": info.get("coverage_branch_delta", ""),
            "mutation_score_before": before_mut.get("score", ""),
            "mutation_score_after": after_mut.get("score", ""),
            "mutation_timeout_adjusted_score_before": before_mut.get(
                "score_killed_or_timeout", ""
            ),
            "mutation_timeout_adjusted_score_after": after_mut.get(
                "score_killed_or_timeout", ""
            ),
            "mutation_score_definition": before_mut.get(
                "score_definition", after_mut.get("score_definition", "")
            ),
            "mutation_score_delta": info.get("mutation_score_delta", ""),
            "mutation_before_exit_code": info.get("mutation_before_exit_code", ""),
            "mutation_after_exit_code": info.get("mutation_after_exit_code", ""),
            "mutation_setup_before_exit_code": info.get(
                "mutation_setup_before_exit_code", ""
            ),
            "mutation_setup_after_exit_code": info.get(
                "mutation_setup_after_exit_code", ""
            ),
            "mutation_before_tool_error": (
                "yes" if info.get("mutation_before_tool_error") else "no"
            ),
            "mutation_after_tool_error": (
                "yes" if info.get("mutation_after_tool_error") else "no"
            ),
            "mutation_unsupported_python": (
                "yes" if info.get("mutation_unsupported_python") else "no"
            ),
            "inference_wall_time_seconds": metrics.get("wall_time_seconds", ""),
            "input_tokens": metrics.get("input_tokens", ""),
            "output_tokens": metrics.get("output_tokens", ""),
            "total_tokens": metrics.get("total_tokens", ""),
            "cost_usd": metrics.get("cost_usd", ""),
            "turns": metrics.get("turns", ""),
            "before_wall_time_seconds": info.get("before_wall_time_seconds", ""),
            "after_wall_time_seconds": info.get("after_wall_time_seconds", ""),
            "mutation_before_wall_time_seconds": info.get(
                "mutation_before_wall_time_seconds", ""
            ),
            "mutation_after_wall_time_seconds": info.get(
                "mutation_after_wall_time_seconds", ""
            ),
            "evaluation_wall_time_seconds": info.get("evaluation_wall_time_seconds", ""),
        })
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["instance_id", "status"]
    with open(output_csv, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Coverage-generation results written to %s", output_csv)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("\n" + "=" * 92)
    print(f"{'COVERAGE-GENERATION RESULTS':^92}")
    print("=" * 92)
    if run_config:
        print("RUN CONFIGURATION")
        for key, value in run_config.items():
            print(f"  {key:<28} {value}")
        print("-" * 92)
    print(f"{'Instance':<40} {'Status':^12} {'Line Δ':>10} {'Branch Δ':>10} {'Mutation Δ':>12}")
    print("-" * 92)
    for row in rows:
        def fmt(value):
            return f"{value:+.2f}" if isinstance(value, (int, float)) else "-"
        print(
            f"{row['instance_id']:<40} {row['status']:^12} "
            f"{fmt(row['line_coverage_delta']):>10} {fmt(row['branch_coverage_delta']):>10} "
            f"{fmt(row['mutation_score_delta']):>12}"
        )
    print("=" * 92)
    print("  " + "  ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    print("=" * 92 + "\n")
