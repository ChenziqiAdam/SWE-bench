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
                   help="Comma-separated levels to run (e.g. 1,2 or 1,2,3)")
    p.add_argument("--output_dir", default="outputs", help="Directory for output files")
    p.add_argument("--run_id", default="eval_run_001", help="Unique run identifier")
    p.add_argument("--github_token", default=None,
                   help="GitHub token (or set GITHUB_TOKEN env var)")
    p.add_argument("--max_workers", type=int, default=4,
                   help="Parallel workers for Docker evaluation")
    p.add_argument("--max_cost", type=float, default=None,
                   help="Max inference cost in USD before stopping")
    p.add_argument("--max_tokens", type=int, default=8192,
                   help="Max output tokens per LLM call (default 8192). "
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
    return p.parse_args()


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
        )

        logger.info("=== Stage 2: Building SWEbench instances ===")
        from swebench.eval_pipeline.instance_builder import build_all_instances, write_instances_jsonl
        instances = build_all_instances(enriched_rows, github_token=github_token)
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

    # Apply instance_ids filter
    if filter_ids:
        instances = [i for i in instances if i["instance_id"] in filter_ids]
        missing = filter_ids - {i["instance_id"] for i in instances}
        if missing:
            logger.warning(f"instance_ids not found in instances.jsonl: {missing}")
        logger.info(f"Filtered to {len(instances)} instance(s): {[i['instance_id'] for i in instances]}")

    # Apply --has_issue filter (problem_statement non-empty = has linked issue)
    if args.has_issue:
        before = len(instances)
        instances = [i for i in instances if i.get("problem_statement", "").strip()]
        logger.info(f"--has_issue: kept {len(instances)}/{before} instances with a linked issue")

    # Apply --has_tests filter (non-empty FAIL_TO_PASS = testable)
    if args.has_tests:
        before = len(instances)
        instances = [i for i in instances if i.get("FAIL_TO_PASS")]
        logger.info(f"--has_tests: kept {len(instances)}/{before} instances with FAIL_TO_PASS tests")

    # ── Stage 3: Prompt Building ──────────────────────────────────────────────
    logger.info("=== Stage 3: Building prompts ===")
    from swebench.eval_pipeline.prompt_builder import build_all_prompts
    all_prompts = build_all_prompts(instances)

    # ── Stage 4: Inference ────────────────────────────────────────────────────
    if not args.skip_inference:
        logger.info("=== Stage 4: Running inference ===")
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
            )

    # ── Stage 5: Docker Evaluation ────────────────────────────────────────────
    run_ids: dict[int, str] = {}
    if not args.skip_eval:
        logger.info("=== Stage 5: Running Docker evaluation ===")
        from swebench.harness.run_evaluation import main as run_eval

        for level in levels:
            predictions_path = str(output_dir / f"level{level}_predictions.jsonl")
            if not Path(predictions_path).exists():
                logger.warning(f"Predictions file not found for level {level}: {predictions_path}")
                continue

            run_id = f"{args.run_id}_level{level}"
            run_ids[level] = run_id
            logger.info(f"--- Evaluating level {level} (run_id={run_id}) ---")

            eval_instance_ids = [i["instance_id"] for i in instances]
            run_eval(
                dataset_name=instances_path,
                split="test",
                instance_ids=eval_instance_ids,
                predictions_path=predictions_path,
                max_workers=args.max_workers,
                force_rebuild=False,
                cache_level="env",
                clean=False,
                open_file_limit=8192,
                run_id=run_id,
                timeout=1800,
                namespace=None,
                rewrite_reports=False,
                modal=False,
            )
    else:
        # Reconstruct run_ids from expected names
        for level in levels:
            run_ids[level] = f"{args.run_id}_level{level}"

    # ── Stage 6: Reporting ────────────────────────────────────────────────────
    logger.info("=== Stage 6: Generating report ===")
    from swebench.eval_pipeline.report import collect_results, render_comparison_table

    results = collect_results(run_ids=run_ids, log_dir=args.log_dir)
    output_csv = str(output_dir / f"{args.run_id}_results.csv")
    render_comparison_table(results=results, instances=instances, output_csv=output_csv)
    logger.info(f"Done. Results saved to {output_csv}")


if __name__ == "__main__":
    main()
