"""CLI entry point for the LLM algorithm PR evaluation pipeline."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(
        description="Evaluate LLM capability to implement algorithm PRs at 3 input levels"
    )
    p.add_argument("--spreadsheet", default="PRs.xlsx", help="Path to PRs.xlsx")
    p.add_argument("--sheet", default=None,
                   help="Sheet name to read from the spreadsheet (default: active/first sheet)")
    p.add_argument("--model", default="claude-sonnet-4-6",
                   help="Model name passed to the API (e.g. claude-sonnet-4-6, gpt-4o, "
                        "mistral-large, llama3:70b). When --endpoint is given this can be "
                        "any string your provider accepts.")

    # ── LLM backend ────────────────────────────────────────────────────────────
    llm = p.add_argument_group(
        "LLM backend",
        "By default the model name determines the backend (claude-* → Anthropic, "
        "everything else → OpenAI). Supply --endpoint to use any OpenAI-compatible "
        "provider (Ollama, Together AI, Mistral, vLLM, LM Studio, Groq, …)."
    )
    llm.add_argument(
        "--endpoint", default=None,
        help="Base URL of an OpenAI-compatible API, e.g. "
             "http://localhost:11434/v1  (Ollama)  or  "
             "https://api.together.xyz/v1  (Together AI). "
             "When set, --model is passed as-is to that endpoint."
    )
    llm.add_argument(
        "--api_key", default=None,
        help="API key for the chosen backend. Falls back to ANTHROPIC_API_KEY / "
             "OPENAI_API_KEY env vars. Local providers (Ollama) don't need a real key."
    )

    p.add_argument("--levels", default="1,2,3",
                   help="Comma-separated levels to run (e.g. 1,2 or 1,2,3). "
                        "Ignored when --agent is set (agent always runs L2 / issue description).")
    p.add_argument("--agent", action="store_true",
                   help="Use agentic inference: multi-turn tool-use loop that explores the "
                        "cloned repo and writes files, instead of a single-shot LLM call. "
                        "Requires --model to be a claude-* model (Anthropic tool_use API) "
                        "when --agent_backend builtin (default).")
    p.add_argument("--agent_backend", default="builtin", choices=["builtin", "sweagent"],
                   help="Which agent backend to use with --agent. "
                        "'builtin' (default): homegrown multi-turn Anthropic tool-use loop. "
                        "'sweagent': invoke SWE-agent CLI as a subprocess (requires `sweagent` "
                        "to be installed: uv pip install swe-agent).")
    p.add_argument("--sweagent_config", default=None,
                   help="Optional path to a custom SWE-agent config YAML. When omitted a "
                        "minimal config is auto-generated per instance. Only used with "
                        "--agent_backend sweagent.")
    p.add_argument("--max_turns", type=int, default=30,
                   help="Max agent turns per instance (only used with --agent --agent_backend builtin, default 30).")
    p.add_argument("--output_dir", default="outputs", help="Directory for output files")
    p.add_argument("--run_id", default="eval_run_001", help="Unique run identifier")
    p.add_argument("--github_token", default=None,
                   help="GitHub token (or set GITHUB_TOKEN env var)")
    p.add_argument("--max_workers", type=int, default=4,
                   help="Parallel workers for Docker evaluation")
    p.add_argument("--max_cost", type=float, default=None,
                   help="Max inference cost in USD before stopping")
    p.add_argument("--max_tokens", type=int, default=32768,
                   help="Max output tokens per LLM call (default 32768). "
                        "Large multi-file diffs plus chatty reasoning can exceed "
                        "16k and get truncated mid-patch. "
                        "Set lower for small models, e.g. --max_tokens 2048 for Qwen3-8B.")
    p.add_argument("--instance_ids", default=None,
                   help="Comma-separated instance_ids to run, e.g. "
                        "numpy__numpy-23513,scipy__scipy-22580. "
                        "Skips all other instances. Use this for testing a single PR.")
    p.add_argument("--repos", default=None,
                   help="Comma-separated repos to filter, e.g. numpy/numpy,scipy/scipy. "
                        "Skips all other repos.")
    p.add_argument("--has_issue", action="store_true",
                   help="Only run instances that have a linked GitHub issue (non-empty problem_statement). "
                        "Useful to focus on L2-eligible PRs.")
    p.add_argument("--has_tests", action="store_true",
                   help="Only run instances with non-empty FAIL_TO_PASS (heuristically identified test functions).")
    p.add_argument("--verified_only", action="store_true",
                   help="Only run instances where mined FAIL_TO_PASS is non-empty "
                        "(i.e. the gold patch demonstrably fixes at least one test). "
                        "Applied after Stage 2.6 mining; requires --skip_mining=False.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only first N rows from the spreadsheet (for testing)")
    p.add_argument("--skip_ingest", action="store_true",
                   help="Skip fetch stage; reuse existing outputs/instances.jsonl")
    p.add_argument("--skip_inference", action="store_true",
                   help="Skip inference; only run evaluation and reporting")
    p.add_argument("--skip_eval", action="store_true",
                   help="Skip Docker evaluation; only run reporting")
    p.add_argument("--log_dir", default="logs/run_evaluation",
                   help="Log directory for run_evaluation output")
    p.add_argument("--skip_validation", action="store_true",
                   help="Skip Stage 2.5 base_commit build validation. Non-buildable instances "
                        "will then fail at the eval stage and clutter the bucket counts.")
    p.add_argument("--revalidate", action="store_true",
                   help="Re-run build validation even for instance_ids already cached in "
                        "build_validation.json.")
    p.add_argument("--skip_mining", action="store_true",
                   help="Skip Stage 2.6 FAIL_TO_PASS / PASS_TO_PASS mining. Falls back to "
                        "regex-extracted test names from test_patch (less accurate).")
    p.add_argument("--remine", action="store_true",
                   help="Re-run test mining even for instance_ids already cached in "
                        "test_mining.json.")
    p.add_argument("--mine_workers", type=int, default=2,
                   help="Parallel containers for Stage 2.6 mining (default 2). Each one "
                        "runs the test suite twice, so total CPU/memory load can be heavy.")
    p.add_argument("--eval_wallclock_per_instance", type=int, default=900,
                   help="Wall-clock budget per instance (seconds) for the Docker eval stage. "
                        "Total budget = N_instances * this. Kills the eval if a worker hangs "
                        "outside the per-test timeout (e.g. stuck docker build / container start). "
                        "Default 900s (15 min/instance).")
    p.add_argument("--clean_images", action="store_true",
                   help="Delete per-instance Docker images after eval (cache_level=instance). "
                        "Saves disk space on large runs at the cost of slower re-runs. "
                        "Env-level images (sweb.env.*) are always kept for reuse.")
    p.add_argument("--no_ingest_cache", action="store_true",
                   help="Ignore the ingest row cache and re-fetch all GitHub data from scratch.")
    return p.parse_args()


def _eval_subprocess_target(kw):
    """Module-level target for spawn-pickling; runs the harness eval."""
    from swebench.harness.run_evaluation import main as run_eval
    run_eval(**kw)


def _run_eval_with_timeout(timeout_seconds: int, **eval_kwargs) -> bool:
    """Run swebench.harness.run_evaluation.main in a subprocess with a wall-clock cap.

    Returns True if it finished within the budget, False if it had to be killed.
    Reports/logs already written to disk are preserved either way.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_eval_subprocess_target, args=(eval_kwargs,), daemon=False)
    proc.start()
    proc.join(timeout=timeout_seconds)
    if proc.is_alive():
        logger.warning(
            f"Eval exceeded wall-clock budget ({timeout_seconds}s); terminating. "
            f"Killing leftover sweb containers."
        )
        proc.terminate()
        proc.join(timeout=30)
        if proc.is_alive():
            proc.kill()
            proc.join()
        import subprocess
        try:
            ids = subprocess.check_output(
                ["docker", "ps", "-q", "--filter", "name=sweb.eval"],
                text=True, timeout=30,
            ).split()
            if ids:
                subprocess.run(["docker", "rm", "-f", *ids], timeout=60)
        except Exception as e:
            logger.warning(f"Container cleanup failed: {e}")
        return False
    return True


def main():
    args = parse_args()

    levels = [int(x) for x in args.levels.split(",")]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    instances_path = str(output_dir / "instances.jsonl")

    github_token = args.github_token or os.environ.get("GITHUB_TOKEN")
    filter_ids = set(args.instance_ids.split(",")) if args.instance_ids else None
    filter_repos = set(args.repos.split(",")) if args.repos else None

    # ── Stage 1 & 2: Ingest + Instance Building ──────────────────────────────
    ingest_cache_path = output_dir / "ingest_cache.jsonl"
    instance_checkpoint_path = str(output_dir / "instances_checkpoint.jsonl")

    if not args.skip_ingest:
        logger.info("=== Stage 1: Ingesting spreadsheet and fetching GitHub data ===")
        from swebench.eval_pipeline.ingest import fetch_all, instance_ids_to_pr_filter
        pr_filter = instance_ids_to_pr_filter(filter_ids) if filter_ids else None
        enriched_rows = fetch_all(
            spreadsheet_path=args.spreadsheet,
            github_token=github_token,
            limit=args.limit,
            pr_numbers=pr_filter,
            repos=filter_repos,
            cache_path=None if args.no_ingest_cache else ingest_cache_path,
            sheet=args.sheet,
        )

        logger.info("=== Stage 2: Building SWEbench instances ===")
        from swebench.eval_pipeline.instance_builder import build_all_instances, write_instances_jsonl
        instances = build_all_instances(
            enriched_rows,
            github_token=github_token,
            checkpoint_path=instance_checkpoint_path,
        )
        # Merge with any existing jsonl so a partial ingest (e.g. --repos numpy/numpy
        # or --limit 5) doesn't wipe rows ingested in prior runs.
        if Path(instances_path).exists() and (filter_repos or filter_ids or args.limit):
            existing = []
            with open(instances_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        existing.append(json.loads(line))
            new_by_id = {i["instance_id"]: i for i in instances}
            merged = [new_by_id.get(i["instance_id"], i) for i in existing]
            existing_ids = {i["instance_id"] for i in existing}
            for i in instances:
                if i["instance_id"] not in existing_ids:
                    merged.append(i)
            logger.info(
                f"Merging {len(instances)} freshly-ingested instance(s) into existing "
                f"{instances_path} ({len(existing)} on disk → {len(merged)} total)."
            )
            write_instances_jsonl(merged, instances_path)
        else:
            write_instances_jsonl(instances, instances_path)
    else:
        logger.info(f"Skipping ingest; loading instances from {instances_path}")
        instances = []
        with open(instances_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    instances.append(json.loads(line))
        logger.info(f"Loaded {len(instances)} instances")

        # Backfill file_contents for instances that were ingested before this field existed
        missing_fc = [i for i in instances if not i.get("file_contents")]
        if missing_fc:
            logger.info(f"Backfilling file_contents for {len(missing_fc)} instances...")
            from swebench.eval_pipeline.instance_builder import _fetch_file_contents, write_instances_jsonl
            for inst in missing_fc:
                inst["file_contents"] = _fetch_file_contents(
                    inst["repo"], inst["base_commit"], inst.get("patch", ""), github_token
                )
            write_instances_jsonl(instances, instances_path)
            logger.info(f"Done backfilling file_contents; wrote back to {instances_path}")

    # Apply instance_ids filter
    if filter_ids:
        instances = [i for i in instances if i["instance_id"] in filter_ids]
        missing = filter_ids - {i["instance_id"] for i in instances}
        if missing:
            logger.warning(f"instance_ids not found in instances.jsonl: {missing}")
        logger.info(f"Filtered to {len(instances)} instance(s): {[i['instance_id'] for i in instances]}")

    # Apply --has_issue filter using the Has Issue column from the spreadsheet
    if args.has_issue:
        before = len(instances)
        instances = [i for i in instances if i.get("has_issue")]
        logger.info(f"--has_issue: kept {len(instances)}/{before} instances with a linked issue")

    # Apply --has_tests filter (non-empty FAIL_TO_PASS = testable)
    if args.has_tests:
        before = len(instances)
        instances = [i for i in instances if i.get("FAIL_TO_PASS")]
        logger.info(f"--has_tests: kept {len(instances)}/{before} instances with FAIL_TO_PASS tests")

    # ── Stage 2.5: Base-commit Build Validation ──────────────────────────────
    build_validation: dict[str, dict] = {}
    if not args.skip_validation:
        logger.info("=== Stage 2.5: Validating base_commit builds ===")
        from swebench.eval_pipeline.validate_base import validate_buildable
        build_validation = validate_buildable(
            instances=instances,
            cache_path=output_dir / "build_validation.json",
            max_workers=args.max_workers,
            force=args.revalidate,
        )
        n_bad = sum(1 for iid in (i["instance_id"] for i in instances)
                    if not build_validation.get(iid, {}).get("buildable", True))
        if n_bad:
            logger.info(f"{n_bad}/{len(instances)} instance(s) flagged non-buildable; "
                        f"they will still run but be marked in the report.")

    # ── Stage 2.6: FAIL_TO_PASS / PASS_TO_PASS Mining ────────────────────────
    if not args.skip_mining:
        logger.info("=== Stage 2.6: Mining FAIL_TO_PASS / PASS_TO_PASS ===")
        from swebench.eval_pipeline.mine_tests import mine_fail_to_pass, apply_mined_to_instances
        mining = mine_fail_to_pass(
            instances=instances,
            cache_path=output_dir / "test_mining.json",
            run_id=args.run_id,
            max_workers=args.mine_workers,
            force=args.remine,
            build_validation=build_validation,
        )
        instances = apply_mined_to_instances(instances, mining)
        # Persist mined FAIL_TO_PASS / PASS_TO_PASS into instances.jsonl so the
        # harness grader uses them downstream. Merge onto the FULL on-disk set
        # so user filters (--instance_ids, --has_issue, --has_tests) do not
        # destructively prune the cache.
        full_on_disk = []
        with open(instances_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    full_on_disk.append(json.loads(line))
        by_id = {i["instance_id"]: i for i in instances}
        merged = [by_id.get(i["instance_id"], i) for i in full_on_disk]
        # Append any in-memory instances not present on disk (shouldn't normally
        # happen, but keeps the merge total-preserving).
        on_disk_ids = {i["instance_id"] for i in full_on_disk}
        for i in instances:
            if i["instance_id"] not in on_disk_ids:
                merged.append(i)
        with open(instances_path, "w") as f:
            for inst in merged:
                f.write(json.dumps(inst) + "\n")
        logger.info(
            f"Rewrote {instances_path} with mined FAIL_TO_PASS / PASS_TO_PASS "
            f"({len(merged)} total instances preserved, {len(instances)} updated this run)"
        )

    # ── Stage 2.7: Verified-solvable filter ──────────────────────────────────
    if args.verified_only:
        if args.skip_mining:
            logger.warning(
                "--verified_only with --skip_mining: FAIL_TO_PASS values are regex-parsed "
                "(not ground-truth mined); filter may be inaccurate."
            )
        before = len(instances)
        instances = [i for i in instances if i.get("FAIL_TO_PASS")]
        logger.info(
            f"--verified_only: kept {len(instances)}/{before} instances with "
            f"non-empty FAIL_TO_PASS"
        )

    # ── Stage 3: Prompt Building ──────────────────────────────────────────────
    logger.info("=== Stage 3: Building prompts ===")
    from swebench.eval_pipeline.prompt_builder import build_all_prompts
    all_prompts = build_all_prompts(instances)

    for level in levels:
        prompts_path = output_dir / f"level{level}_prompts.jsonl"
        with open(prompts_path, "w") as pf:
            for iid, p_by_level in all_prompts.items():
                pf.write(json.dumps({
                    "instance_id": iid,
                    "level": level,
                    "prompt": p_by_level.get(level),
                }) + "\n")
        logger.info(f"Wrote prompts for level {level} → {prompts_path}")

    # ── Stage 4: Inference ────────────────────────────────────────────────────
    if not args.skip_inference:
        logger.info("=== Stage 4: Running inference ===")

        if args.agent:
            agent_predictions_file = str(output_dir / "agent_predictions.jsonl")
            if args.agent_backend == "sweagent":
                from swebench.eval_pipeline.swe_agent_inference import run_sweagent_inference
                logger.info(f"--- SWE-agent inference → {agent_predictions_file} ---")
                run_sweagent_inference(
                    instances=instances,
                    output_file=agent_predictions_file,
                    model_name=args.model,
                    github_token=github_token,
                    max_workers=args.max_workers,
                    sweagent_config=args.sweagent_config,
                    api_base=args.endpoint,
                    api_key=args.api_key,
                )
            else:
                # Builtin: multi-turn Anthropic tool-use loop
                from swebench.eval_pipeline.inference import make_clients
                from swebench.eval_pipeline.agent_inference import run_agent_inference_for_level
                anthropic_client, _ = make_clients(args.model, endpoint=args.endpoint, api_key=args.api_key)
                logger.info(f"--- Agent inference (builtin, issue description) → {agent_predictions_file} ---")
                run_agent_inference_for_level(
                    instances=instances,
                    output_file=agent_predictions_file,
                    model_name=args.model,
                    anthropic_client=anthropic_client,
                    github_token=github_token,
                    max_turns=args.max_turns,
                    max_workers=args.max_workers,
                )
        else:
            from swebench.eval_pipeline.inference import run_inference_for_level, make_clients
            anthropic_client, openai_compat_client = make_clients(
                args.model,
                endpoint=args.endpoint,
                api_key=args.api_key,
            )

            for level in levels:
                output_file = str(output_dir / f"level{level}_predictions.jsonl")
                logger.info(f"--- Level {level} → {output_file} ---")
                level_prompts = {iid: p[level] for iid, p in all_prompts.items()}
                run_inference_for_level(
                    instances=instances,
                    prompts=level_prompts,
                    model_name=args.model,
                    output_file=output_file,
                    max_cost=args.max_cost,
                    max_tokens=args.max_tokens,
                    anthropic_client=anthropic_client,
                    openai_compat_client=openai_compat_client,
                    max_workers=args.max_workers,
                )

    # ── Stage 5: Docker Evaluation ────────────────────────────────────────────
    run_ids: dict[int, str] = {}
    if not args.skip_eval:
        logger.info("=== Stage 5: Running Docker evaluation ===")

        if args.agent:
            eval_levels_map = {"agent": str(output_dir / "agent_predictions.jsonl")}
        else:
            eval_levels_map = {level: str(output_dir / f"level{level}_predictions.jsonl") for level in levels}

        for level_key, predictions_path in eval_levels_map.items():
            if not Path(predictions_path).exists():
                logger.warning(f"Predictions file not found: {predictions_path}")
                continue

            run_id = f"{args.run_id}_agent" if args.agent else f"{args.run_id}_level{level_key}"
            run_ids[level_key] = run_id
            eval_instance_ids = [i["instance_id"] for i in instances]
            wallclock = args.eval_wallclock_per_instance * max(1, len(eval_instance_ids))
            logger.info(
                f"--- Evaluating {level_key} (run_id={run_id}, "
                f"wallclock_budget={wallclock}s for {len(eval_instance_ids)} instances) ---"
            )

            finished = _run_eval_with_timeout(
                timeout_seconds=wallclock,
                dataset_name=instances_path,
                split="test",
                instance_ids=eval_instance_ids,
                predictions_path=predictions_path,
                max_workers=args.max_workers,
                force_rebuild=False,
                cache_level="instance" if args.clean_images else "env",
                clean=args.clean_images,
                open_file_limit=8192,
                run_id=run_id,
                timeout=1800,
                namespace=None,
                rewrite_reports=False,
                modal=False,
            )
            if not finished:
                logger.warning(
                    f"{level_key} eval hit wall-clock cap. "
                    f"Partial reports under {args.log_dir}/{run_id}/ are preserved."
                )
    else:
        # Reconstruct run_ids from expected names
        if args.agent:
            run_ids["agent"] = f"{args.run_id}_agent"
        else:
            for level in levels:
                run_ids[level] = f"{args.run_id}_level{level}"

    # ── Stage 6: Reporting ────────────────────────────────────────────────────
    logger.info("=== Stage 6: Generating report ===")
    from swebench.eval_pipeline.report import collect_results, render_comparison_table

    results = collect_results(
        run_ids=run_ids,
        log_dir=args.log_dir,
        instance_ids={i["instance_id"] for i in instances},
    )
    output_csv = str(output_dir / f"{args.run_id}_results.csv")
    if args.agent:
        predictions_paths = {"agent": str(output_dir / "agent_predictions.jsonl")}
    else:
        predictions_paths = {
            int(level): str(output_dir / f"level{int(level)}_predictions.jsonl")
            for level in args.levels.split(",")
        }
    run_config = {
        "model": args.model,
        "levels": args.levels,
        "run_id": args.run_id,
        "output_dir": str(output_dir),
        "max_tokens": args.max_tokens,
        "max_workers": args.max_workers,
        "max_cost": args.max_cost,
        "limit": args.limit,
        "instance_ids": args.instance_ids or "(all)",
        "repos": args.repos or "(all)",
        "has_issue": args.has_issue,
        "has_tests": args.has_tests,
        "verified_only": args.verified_only,
        "skip_ingest": args.skip_ingest,
        "skip_inference": args.skip_inference,
        "skip_eval": args.skip_eval,
        "skip_validation": args.skip_validation,
        "skip_mining": args.skip_mining,
        "revalidate": args.revalidate,
        "remine": args.remine,
        "mine_workers": args.mine_workers,
    }
    render_comparison_table(
        results=results,
        instances=instances,
        output_csv=output_csv,
        build_validation=build_validation,
        predictions_paths=predictions_paths,
        run_config=run_config,
    )
    logger.info(f"Done. Results saved to {output_csv}")


if __name__ == "__main__":
    main()
