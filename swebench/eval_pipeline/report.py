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
    instance_ids: set[str] | None = None,
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
                    if instance_ids is not None and instance_id not in instance_ids:
                        continue
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
                    if instance_ids is not None and instance_id not in instance_ids:
                        continue
                    if instance_id not in results:
                        results[instance_id] = {1: None, 2: None, 3: None}
                    # Only fill in if not already set by per-instance report.json
                    if results[instance_id][level] is None:
                        results[instance_id][level] = instance_id in resolved_ids
            except Exception as e:
                logger.error(f"Error reading summary {summary_file}: {e}")

    return results


def compute_pass_rates(
    results: dict[str, dict[int, Optional[bool]]],
    exclude_ids: set[str] | None = None,
    per_level_eligible: dict[int, set[str]] | None = None,
) -> dict[int, tuple[float, int, int]]:
    """Return {level: (rate, resolved, denominator)}.

    - exclude_ids drops instances at every level (e.g. non-buildable).
    - per_level_eligible[level], if provided, further restricts the denominator at
      that level to the listed instance_ids — used for "had a non-empty prompt/patch"
      fair-denominator views.
    """
    exclude_ids = exclude_ids or set()
    rates: dict[int, tuple[float, int, int]] = {}
    for level in [1, 2, 3]:
        eligible = per_level_eligible.get(level) if per_level_eligible else None
        vals = []
        for iid, v in results.items():
            if iid in exclude_ids:
                continue
            if eligible is not None and iid not in eligible:
                continue
            if v[level] is None:
                continue
            vals.append(v[level])
        denom = len(vals)
        resolved = sum(1 for x in vals if x)
        rates[level] = (resolved / denom if denom else 0.0, resolved, denom)
    return rates


def _load_nonempty_prediction_ids(predictions_paths: dict[int, str]) -> dict[int, set[str]]:
    """Return {level: {instance_id, ...}} for instances with a non-empty model_patch."""
    out: dict[int, set[str]] = {1: set(), 2: set(), 3: set()}
    for level, path in predictions_paths.items():
        level = int(level)
        if level not in out:
            out[level] = set()
        if not path or not Path(path).exists():
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (row.get("model_patch") or "").strip():
                    out[level].add(row["instance_id"])
    return out


def render_comparison_table(
    results: dict[str, dict[int, Optional[bool]]],
    instances: list[dict],
    output_csv: str,
    build_validation: dict[str, dict] | None = None,
    predictions_paths: dict[int, str] | None = None,
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
    build_validation = build_validation or {}
    unbuildable_ids = {iid for iid, v in build_validation.items() if not v.get("buildable", True)}

    nonempty = _load_nonempty_prediction_ids(predictions_paths or {})

    rows = []
    for instance_id, level_results in sorted(results.items()):
        inst = meta.get(instance_id, {})
        bv = build_validation.get(instance_id, {})
        rows.append({
            "instance_id": instance_id,
            "repo": inst.get("repo", ""),
            "pr_number": inst.get("pull_number", ""),
            "category": inst.get("category", ""),
            "buildable": "" if not build_validation else ("yes" if bv.get("buildable", True) else "no"),
            "level1_resolved": _bool_str(level_results.get(1)),
            "level2_resolved": _bool_str(level_results.get(2)),
            "level3_resolved": _bool_str(level_results.get(3)),
            "level1_has_pred": "yes" if instance_id in nonempty[1] else "no",
            "level2_has_pred": "yes" if instance_id in nonempty[2] else "no",
            "level3_has_pred": "yes" if instance_id in nonempty[3] else "no",
        })

    # Write CSV
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["instance_id", "repo", "pr_number", "category", "buildable",
                  "level1_resolved", "level2_resolved", "level3_resolved",
                  "level1_has_pred", "level2_has_pred", "level3_has_pred"]
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Results written to {output_csv}")

    rates_raw = compute_pass_rates(results)
    rates_clean = compute_pass_rates(results, exclude_ids=unbuildable_ids)
    rates_fair = compute_pass_rates(
        results,
        exclude_ids=unbuildable_ids,
        per_level_eligible=nonempty,
    )
    total = len(results)
    n_buildable = total - len(unbuildable_ids & set(results.keys()))

    def _fmt(r):
        rate, res, denom = r
        return f"{rate:6.1%} ({res}/{denom})"

    print("\n" + "=" * 78)
    print(f"{'EVALUATION RESULTS':^78}")
    print("=" * 78)
    print(f"{'Instance':<40} {'Build':^6} {'L1':^6} {'L2':^6} {'L3':^6}")
    print("-" * 78)
    for row in rows:
        print(
            f"{row['instance_id']:<40} "
            f"{(row['buildable'] or '-'):^6} "
            f"{row['level1_resolved']:^6} "
            f"{row['level2_resolved']:^6} "
            f"{row['level3_resolved']:^6}"
        )
    print("=" * 78)
    print(f"{'PASS RATE (all instances)':<32} "
          f"{_fmt(rates_raw[1]):>14} {_fmt(rates_raw[2]):>14} {_fmt(rates_raw[3]):>14}")
    if build_validation:
        print(f"{'PASS RATE (buildable only)':<32} "
              f"{_fmt(rates_clean[1]):>14} {_fmt(rates_clean[2]):>14} {_fmt(rates_clean[3]):>14}")
    if predictions_paths:
        print(f"{'PASS RATE (non-empty pred, fair)':<32} "
              f"{_fmt(rates_fair[1]):>14} {_fmt(rates_fair[2]):>14} {_fmt(rates_fair[3]):>14}")
    if build_validation:
        print(f"Total instances: {total}  |  buildable: {n_buildable}  |  "
              f"non-buildable: {total - n_buildable}")
    else:
        print(f"Total instances evaluated: {total}")
    print("=" * 78 + "\n")


def _bool_str(val: Optional[bool]) -> str:
    if val is None:
        return "N/A"
    return "PASS" if val else "FAIL"
