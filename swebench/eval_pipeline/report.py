"""Stage 6: Aggregate evaluation results and render comparison table."""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def collect_results(
    run_ids: dict[int, str],
    log_dir: str = "logs/run_evaluation",
) -> dict[str, dict[int, Optional[bool]]]:
    """
    Read evaluation results for each level's run.

    Checks two sources:
    1. Per-instance report.json under logs/run_evaluation/{run_id}/{model}/{instance_id}/
       (written only for completed instances where the patch applied and tests ran)
    2. Top-level {model}.{run_id}.json in CWD
       (written for all instances; error_ids = patch apply failed = unresolved)

    Args:
        run_ids: {level: run_id} e.g. {1: "level1_claude_run", 2: "level2_..."}
        log_dir: base log directory (default matches run_evaluation.py default)

    Returns:
        {instance_id: {1: resolved_bool_or_None, 2: ..., 3: ...}}
    """
    results: dict[str, dict[int, Optional[bool]]] = {}

    for level, run_id in run_ids.items():
        # Source 1: per-instance report.json (completed runs)
        run_path = Path(log_dir) / run_id
        report_files = list(run_path.glob("*/*/report.json")) if run_path.exists() else []
        logger.info(f"Level {level} ({run_id}): found {len(report_files)} per-instance report files")

        for report_file in report_files:
            try:
                with open(report_file) as f:
                    data = json.load(f)
                for instance_id, info in data.items():
                    if instance_id not in results:
                        results[instance_id] = {1: None, 2: None, 3: None}
                    results[instance_id][level] = info.get("resolved", False)
            except Exception as e:
                logger.error(f"Error reading {report_file}: {e}")

        # Source 2: top-level run summary JSON (covers error/empty-patch instances)
        # Pattern: {model}.{run_id}.json — search CWD for any file ending in .{run_id}.json
        summary_files = list(Path(".").glob(f"*.{run_id}.json"))
        for summary_file in summary_files:
            try:
                with open(summary_file) as f:
                    data = json.load(f)
                resolved_ids = set(data.get("resolved_ids", []))
                submitted_ids = set(data.get("submitted_ids", []))
                logger.info(f"Level {level} summary ({summary_file.name}): "
                            f"{len(submitted_ids)} submitted, {len(resolved_ids)} resolved")
                for instance_id in submitted_ids:
                    if instance_id not in results:
                        results[instance_id] = {1: None, 2: None, 3: None}
                    # Only fill in if not already set by per-instance report.json
                    if results[instance_id][level] is None:
                        results[instance_id][level] = instance_id in resolved_ids
            except Exception as e:
                logger.error(f"Error reading summary {summary_file}: {e}")

    return results


def compute_pass_rates(results: dict[str, dict[int, Optional[bool]]]) -> dict[int, float]:
    """Return {level: pass_rate} where pass_rate = resolved / total_with_data."""
    rates = {}
    for level in [1, 2, 3]:
        vals = [v[level] for v in results.values() if v[level] is not None]
        rates[level] = sum(vals) / len(vals) if vals else 0.0
    return rates


def render_comparison_table(
    results: dict[str, dict[int, Optional[bool]]],
    instances: list[dict],
    output_csv: str,
) -> None:
    """
    Write a CSV and print an ASCII summary table.

    Args:
        results: output of collect_results()
        instances: list of instance dicts (for repo/pr_number metadata)
        output_csv: path to write the CSV
    """
    # Build metadata lookup
    meta = {inst["instance_id"]: inst for inst in instances}

    rows = []
    for instance_id, level_results in sorted(results.items()):
        inst = meta.get(instance_id, {})
        rows.append({
            "instance_id": instance_id,
            "repo": inst.get("repo", ""),
            "pr_number": inst.get("pull_number", ""),
            "category": inst.get("category", ""),
            "level1_resolved": _bool_str(level_results.get(1)),
            "level2_resolved": _bool_str(level_results.get(2)),
            "level3_resolved": _bool_str(level_results.get(3)),
        })

    # Write CSV
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["instance_id", "repo", "pr_number", "category",
                  "level1_resolved", "level2_resolved", "level3_resolved"]
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Results written to {output_csv}")

    # Print ASCII table
    rates = compute_pass_rates(results)
    total = len(results)

    print("\n" + "=" * 70)
    print(f"{'EVALUATION RESULTS':^70}")
    print("=" * 70)
    print(f"{'Instance':<40} {'L1':^6} {'L2':^6} {'L3':^6}")
    print("-" * 70)
    for row in rows:
        print(
            f"{row['instance_id']:<40} "
            f"{row['level1_resolved']:^6} "
            f"{row['level2_resolved']:^6} "
            f"{row['level3_resolved']:^6}"
        )
    print("=" * 70)
    print(f"{'PASS RATE':<40} "
          f"{rates[1]:^6.1%} "
          f"{rates[2]:^6.1%} "
          f"{rates[3]:^6.1%}")
    print(f"Total instances evaluated: {total}")
    print("=" * 70 + "\n")


def _bool_str(val: Optional[bool]) -> str:
    if val is None:
        return "N/A"
    return "PASS" if val else "FAIL"
