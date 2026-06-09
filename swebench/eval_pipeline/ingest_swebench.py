"""
Ingest SWE-Bench Verified instances into our pipeline's instance format.

Used as a baseline run: lets us measure our L2 (issue-only) pass-rate on
SWE-Bench Verified and compare against our PRs.xlsx L2 number to quantify
relative task difficulty.

CLI:
  python -m swebench.eval_pipeline.ingest_swebench \
    --n 100 --seed 42 \
    --out outputs/swebench_verified_baseline/instances.jsonl \
    --github_token $GITHUB_TOKEN
"""
from __future__ import annotations

import argparse
import logging
import random
from collections import defaultdict
from typing import Optional

from swebench.eval_pipeline.instance_builder import (
    _fetch_file_contents,
    write_instances_jsonl,
)
from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
from swebench.harness.utils import load_swebench_dataset

logger = logging.getLogger(__name__)

# SWE-Bench Verified contains only one of our PRs.xlsx repos (sklearn, 32 inst).
# scipy/pandas/numpy are not in Verified, so the apples-to-apples comparison is
# sklearn-only. Pass --targets on the CLI to override (e.g. for broader Verified
# sampling across django/sympy/matplotlib/etc.).
TARGET_REPOS = {
    "scikit-learn/scikit-learn": 32,
}


def _has_spec(repo: str, version: str) -> bool:
    return repo in MAP_REPO_VERSION_TO_SPECS and version in MAP_REPO_VERSION_TO_SPECS[repo]


def _stratified_sample(
    eligible_by_repo: dict[str, list[dict]],
    targets: dict[str, int],
    seed: int,
) -> list[dict]:
    """
    Sample per-repo according to targets. If a stratum has fewer items than
    its target, take all of them and reallocate the deficit to sklearn.
    """
    rng = random.Random(seed)
    sampled: list[dict] = []
    deficit = 0
    overflow_repo = "scikit-learn/scikit-learn"

    for repo, target in targets.items():
        pool = eligible_by_repo.get(repo, [])
        if len(pool) <= target:
            sampled.extend(pool)
            deficit += target - len(pool)
            logger.info(f"  {repo}: took all {len(pool)}/{target} (deficit {target - len(pool)})")
        else:
            picked = rng.sample(pool, target)
            sampled.extend(picked)
            logger.info(f"  {repo}: sampled {target}/{len(pool)}")

    if deficit > 0:
        # Reallocate to sklearn — exclude already-picked sklearn rows.
        already = {x["instance_id"] for x in sampled}
        extra_pool = [
            x for x in eligible_by_repo.get(overflow_repo, [])
            if x["instance_id"] not in already
        ]
        take = min(deficit, len(extra_pool))
        sampled.extend(rng.sample(extra_pool, take))
        logger.info(f"  reallocated {take} to {overflow_repo} (deficit was {deficit})")

    return sampled


def _to_pipeline_instance(row: dict, github_token: Optional[str]) -> dict:
    """
    Convert a SWE-Bench Verified row into our pipeline's instance dict shape.
    Fetches file_contents at base_commit so L2 prompts have the same code
    context our PRs.xlsx instances do.
    """
    repo = row["repo"]
    base_commit = row["base_commit"]
    patch = row["patch"]

    file_contents = _fetch_file_contents(repo, base_commit, patch, github_token)

    return {
        "instance_id": row["instance_id"],
        "repo": repo,
        "base_commit": base_commit,
        "patch": patch,
        "test_patch": row["test_patch"],
        "problem_statement": row["problem_statement"],
        "FAIL_TO_PASS": row["FAIL_TO_PASS"],
        "PASS_TO_PASS": row["PASS_TO_PASS"],
        "version": row["version"],
        "environment_setup_commit": row.get("environment_setup_commit", base_commit),
        "created_at": row.get("created_at", ""),
        # Pipeline-specific fields. Empty PR/paper fields make L1 + L3 prompt
        # builders return None; L2 uses problem_statement.
        "pr_title": "",
        "pr_body": "",
        "paper_reference": "",
        "algorithm_name": "",
        "category": "algorithm",
        "file_contents": file_contents,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=32, help="Sample size (default 32 — all Verified sklearn).")
    p.add_argument("--seed", type=int, default=42, help="Sampling seed (default 42).")
    p.add_argument("--out", required=True, help="Output JSONL path.")
    p.add_argument("--github_token", default=None, help="GitHub token for raw fetches.")
    p.add_argument(
        "--dataset",
        default="SWE-bench/SWE-bench_Verified",
        help="HuggingFace dataset name.",
    )
    p.add_argument("--split", default="test")
    p.add_argument(
        "--targets",
        default=None,
        help='Optional override of repo targets as JSON, e.g. \'{"scikit-learn/scikit-learn": 60, ...}\'.'
             " Defaults are scaled from our PRs.xlsx mix to sum to --n.",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.targets:
        import json as _json
        targets = _json.loads(args.targets)
    else:
        # Rescale default mix to requested N.
        scale = args.n / sum(TARGET_REPOS.values())
        targets = {r: max(1, round(v * scale)) for r, v in TARGET_REPOS.items()}
        # Fix rounding drift.
        drift = args.n - sum(targets.values())
        if drift != 0:
            targets["scikit-learn/scikit-learn"] += drift

    logger.info(f"Target distribution: {targets}")

    logger.info(f"Loading {args.dataset} [{args.split}]...")
    dataset = load_swebench_dataset(args.dataset, split=args.split)
    logger.info(f"Loaded {len(dataset)} instances")

    eligible_by_repo: dict[str, list[dict]] = defaultdict(list)
    skipped_no_spec = 0
    for row in dataset:
        repo = row["repo"]
        if repo not in targets:
            continue
        if not _has_spec(repo, row["version"]):
            skipped_no_spec += 1
            continue
        eligible_by_repo[repo].append(row)

    logger.info(
        f"Eligible after repo+spec filter: "
        f"{ {r: len(v) for r, v in eligible_by_repo.items()} } "
        f"(skipped {skipped_no_spec} for missing spec)"
    )

    sampled = _stratified_sample(eligible_by_repo, targets, args.seed)
    logger.info(f"Sampled {len(sampled)} instances")

    instances = []
    for i, row in enumerate(sampled, start=1):
        logger.info(f"[{i}/{len(sampled)}] Fetching files for {row['instance_id']}")
        instances.append(_to_pipeline_instance(row, args.github_token))

    write_instances_jsonl(instances, args.out)
    logger.info(f"Done. Wrote {len(instances)} instances to {args.out}")


if __name__ == "__main__":
    main()
