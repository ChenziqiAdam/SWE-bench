"""CLI entry point for the LLM algorithm PR evaluation pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from swebench.eval_pipeline.prediction_utils import unique_instances_by_id, write_selected_predictions
from swebench.eval_pipeline.pynguin_generation import PYNGUIN_POSTPROCESSING_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_COVERAGE_SETUP_COMMAND = "python -m pip install -e . pytest"
DEFAULT_COVERAGE_TEST_COMMAND = "python -m pytest"
DEFAULT_CPP_COVERAGE_IMAGE = (
    "localhost/swebench-coverage-cpp:gcc12.5-cmake3.25-gcovr8.6"
)

STANDALONE_COVERAGE_REPO_PROFILES = {
    "biopython/biopython": {
        "coverage_setup_command": (
            "python -m pip install -e . setuptools 'pytest<9' && "
            "python setup.py build_ext --inplace"
        ),
        "coverage_test_command": "python Tests/run_tests.py --offline",
        "coverage_command": (
            "python -m coverage run --branch --source=Bio "
            "Tests/run_tests.py --offline"
        ),
        "coverage_pytest_command": (
            "python -m coverage run --branch --source=Bio --append -m pytest"
        ),
        "mutation_test_style": "biopython",
        "mutation_tests_dir": "Tests",
    },
    "geopandas/geopandas": {
        "coverage_python_executable": "python3.11",
        "coverage_setup_command": (
            # The history-isolated checkout has no tags, so GeoPandas reports a
            # fallback development version. Resolve optional test dependencies
            # before installing that checkout to avoid pip backtracking to old,
            # incompatible pointpats/libpysal releases.
            "python -m pip install -r requirements-dev.txt && "
            "python -m pip install -e . --no-deps"
        ),
        "coverage_environment_preflight_command": (
            "python -c \"import dateutil, geopandas, pandas, shapely\""
        ),
        "coverage_test_command": "python -m pytest -m 'not web' geopandas",
        "coverage_command": (
            "python -m coverage run --branch --source=geopandas "
            "-m pytest -m 'not web' geopandas"
        ),
        "mutation_test_style": "pytest_generated",
        "mutation_tests_dir": "geopandas/tests",
        "pynguin_ignore_noncallable_signatures": True,
    },
    "astropy/astropy": {
        "coverage_python_executable": "python3.11",
        "coverage_setup_command": "python -m pip install -e '.[test]'",
        "coverage_environment_preflight_command": "python -c \"import astropy\"",
        "coverage_test_command": "python -m pytest --pyargs astropy",
        "coverage_command": (
            "python -m coverage run --branch --source=astropy "
            "-m pytest --pyargs astropy"
        ),
        "mutation_test_style": "pytest_generated",
        "mutation_tests_dir": "astropy",
        # One phase includes primary, coverage, and two repeat runs of ~32k tests.
        "coverage_phase_timeout": 7200,
        "pynguin_warning_filters": [
            "ignore::astropy.utils.exceptions.AstropyDeprecationWarning"
        ],
        # mutmut 2.5/parso cannot parse this module's current syntax.
        "mutation_excluded_targets": ["astropy/utils/data.py"],
    },
    "openmm/openmm": {
        "coverage_language": "cpp",
        "coverage_source_roots": [
            "openmmapi/src", "platforms/cpu/src", "platforms/reference/src",
            "serialization/src", "plugins",
        ],
        "coverage_setup_command": (
            "cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug "
            "-DBUILD_TESTING=ON -DOPENMM_BUILD_CPU_LIB=ON "
            "-DOPENMM_BUILD_CPU_TESTS=ON -DOPENMM_BUILD_REFERENCE_TESTS=ON "
            "-DOPENMM_BUILD_SERIALIZATION_TESTS=ON "
            "-DOPENMM_BUILD_CUDA_LIB=OFF -DOPENMM_BUILD_HIP_LIB=OFF "
            "-DOPENMM_BUILD_OPENCL_LIB=OFF -DOPENMM_BUILD_PYTHON_WRAPPERS=OFF "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF "
            "-DOPENMM_BUILD_EXAMPLES=OFF "
            "-DCMAKE_C_FLAGS=--coverage -DCMAKE_CXX_FLAGS=--coverage "
            "-DCMAKE_SHARED_LINKER_FLAGS=--coverage "
            "-DCMAKE_EXE_LINKER_FLAGS=--coverage && cmake --build build"
        ),
        "coverage_test_command": (
            "(cd build && "
            "python3 ../devtools/run-ctest.py --attempts 0 --parallel 2 "
            "--job-duration 120 --timeout 900 || "
            "{ test -s Testing/Temporary/LastTestsFailed.log && "
            "ctest --output-on-failure --rerun-failed --parallel 2 "
            "--timeout 900; })"
        ),
        "coverage_reset_command": "find build -name '*.gcda' -delete",
        "coverage_command": (
            "(cd build && "
            "python3 ../devtools/run-ctest.py --attempts 0 --parallel 2 "
            "--job-duration 120 --timeout 900 || "
            "{ test -s Testing/Temporary/LastTestsFailed.log && "
            "ctest --output-on-failure --rerun-failed --parallel 2 "
            "--timeout 900; })"
        ),
        "coverage_results_command": (
            "gcovr --root . --filter openmmapi/src --filter platforms/cpu/src "
            "--filter platforms/reference/src --filter serialization/src "
            "--filter plugins --exclude '.*/(tests?|serialization/tests)/.*' "
            "--exclude 'build/.*' "
            "--gcov-ignore-parse-errors=suspicious_hits.warn_once_per_file "
            "--json-summary {output}"
        ),
        "coverage_phase_timeout": 14400,
    },
}


def _clear_selected_evaluation_cache(
    log_dir: str | Path,
    run_id: str,
    instance_ids: list[str],
) -> int:
    """Clear only selected reports and stale containers for a forced rerun."""
    import shutil
    import docker

    removed = 0
    for instance_id in instance_ids:
        for report_dir in Path(log_dir).glob(f"{run_id}/*/{instance_id}"):
            shutil.rmtree(report_dir, ignore_errors=True)
            removed += 1

    # Use the Docker-compatible API rather than a hard-coded ``docker`` CLI.
    # Rootless Podman exposes this API through DOCKER_HOST but commonly does not
    # install a binary named ``docker``.
    client = None
    try:
        client = docker.from_env()
        for instance_id in instance_ids:
            container_name = f"sweb.eval.{instance_id}.{run_id}"
            try:
                client.containers.get(container_name).remove(force=True)
            except docker.errors.NotFound:
                pass
            except docker.errors.DockerException as exc:
                logger.warning(
                    "Could not remove stale evaluation container %s: %s",
                    container_name,
                    exc,
                )
    except docker.errors.DockerException as exc:
        logger.warning("Could not connect for stale-container cleanup: %s", exc)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return removed


def _write_prompts_preserving_unselected(
    prompts_path: Path,
    prompts: dict[str, str],
    preserve_existing: bool,
) -> int:
    """Write prompts without pruning unrelated rows during a partial rerun."""
    merged: dict[str, str] = {}
    if preserve_existing and prompts_path.exists():
        for line in prompts_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("instance_id"):
                merged[row["instance_id"]] = row.get("prompt", "")
    merged.update(prompts)
    with prompts_path.open("w") as prompt_file:
        for instance_id, prompt in merged.items():
            prompt_file.write(
                json.dumps({"instance_id": instance_id, "prompt": prompt}) + "\n"
            )
    return len(merged)


def _load_targeted_report_scope(
    spreadsheet_path: str,
    sheet: str | None,
    checkpoint_path: str | Path,
    repos: set[str] | None = None,
    issue_types: set[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Recover the full spreadsheet cohort for a targeted cached-report repair.

    ``instances.jsonl`` may contain a different sheet from the most recent run.
    Resolve the intended report IDs from the current spreadsheet/sheet and load
    their metadata from the shared instance checkpoint instead.
    """
    from swebench.eval_pipeline.constants import COL_CATEGORY, COL_PR_NUMBER, COL_REPO
    from swebench.eval_pipeline.ingest import load_spreadsheet_rows, normalize_issue_type
    from swebench.eval_pipeline.instance_builder import _make_instance_id

    rows = load_spreadsheet_rows(spreadsheet_path, sheet=sheet)
    if repos:
        rows = [row for row in rows if row.get(COL_REPO) in repos]
    if issue_types:
        rows = [
            row for row in rows
            if normalize_issue_type(row.get(COL_CATEGORY)) in issue_types
        ]
    if limit:
        rows = rows[:limit]

    requested_ids = list(dict.fromkeys(
        _make_instance_id(row[COL_REPO], row[COL_PR_NUMBER])
        for row in rows
    ))
    checkpoint_by_id: dict[str, dict] = {}
    checkpoint = Path(checkpoint_path)
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            if not line.strip():
                continue
            instance = json.loads(line)
            checkpoint_by_id[instance["instance_id"]] = instance

    missing = [instance_id for instance_id in requested_ids
               if instance_id not in checkpoint_by_id]
    if missing:
        logger.warning(
            "Targeted report scope is missing %d checkpoint instance(s): %s",
            len(missing),
            missing,
        )
    return [
        checkpoint_by_id[instance_id]
        for instance_id in requested_ids
        if instance_id in checkpoint_by_id
    ]


def _docker_unavailable_reason() -> str | None:
    """Return a diagnostic when the Docker daemon cannot service requests."""
    import docker

    client = None
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        return f"Docker daemon unavailable: {type(exc).__name__}: {exc}"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return None


def _write_evaluation_failure(
    path: Path, reason: str, stage: str = "docker_preflight"
) -> None:
    """Persist a run-level infrastructure failure for automation and audits."""
    path.write_text(
        json.dumps({"status": "errored", "stage": stage, "error": reason}, indent=2)
    )
    logger.error("%s. Evaluation skipped; failure record written to %s", reason, path)


def parse_args():
    p = argparse.ArgumentParser(
        description="Evaluate an agent's issue-resolution rate on scientific-software PRs"
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
        "provider for builtin/SWE-agent, a Responses-compatible provider for Codex, "
        "or an Anthropic-compatible provider for Claude Code."
    )
    llm.add_argument(
        "--endpoint", default=None,
        help="Base URL of an OpenAI-compatible API, e.g. "
             "http://localhost:11434/v1  (Ollama)  or  "
             "https://api.together.xyz/v1  (Together AI). "
             "When set, --model is passed as-is to that endpoint. For Codex this "
             "must support Codex's Responses-style API; for Claude Code this is "
             "passed as ANTHROPIC_BASE_URL and must be Anthropic-compatible."
    )
    llm.add_argument(
        "--api_key", default=None,
        help="API key for the chosen backend. Falls back to ANTHROPIC_API_KEY / "
             "OPENAI_API_KEY env vars. Local providers (Ollama) don't need a real key."
    )

    p.add_argument("--agent", action="store_true", default=True,
                   help="(Always on.) Agentic inference: multi-turn tool-use loop that explores "
                        "the cloned repo and writes files. The pipeline is agent-only; this flag "
                        "is kept for backward compatibility with existing scripts.")
    p.add_argument("--agent_backend", default="builtin",
                   choices=["builtin", "sweagent", "codex", "claude_code", "agy"],
                   help="Which agent backend to use with --agent. "
                        "'builtin' (default): homegrown multi-turn Anthropic tool-use loop. "
                        "'sweagent': invoke SWE-agent CLI as a subprocess (requires `sweagent` "
                        "to be installed: uv pip install swe-agent). "
                        "'codex': invoke local Codex CLI via `codex exec`. "
                        "'claude_code': invoke local Claude Code CLI via `claude -p`. "
                        "'agy': invoke local Antigravity CLI via `agy -p`.")
    p.add_argument(
        "--inference_network_policy",
        choices=["model-only", "unrestricted"],
        default="model-only",
        help="Network boundary for inference tools (default: model-only). "
        "The safe mode permits host agent CLIs to contact only a loopback model "
        "gateway (for example --endpoint http://localhost:4000) and fails closed "
        "when no supported OS guard is available. "
        "Use unrestricted only for explicitly non-benchmark debugging.",
    )
    p.add_argument(
        "--inference_hidden_path",
        action="append",
        default=[],
        help="Additional existing file or directory to hide from host inference "
        "agents. May be repeated for nonstandard evaluation/cache locations.",
    )
    p.add_argument("--sweagent_config", default=None,
                   help="Optional path to a custom SWE-agent config YAML. When omitted a "
                        "minimal config is auto-generated per instance. Only used with "
                        "--agent_backend sweagent.")
    p.add_argument("--max_turns", type=int, default=30,
                   help="Max agent turns per instance (only used with --agent --agent_backend builtin, default 30).")
    p.add_argument("--output_dir", default="outputs", help="Directory for output files")
    p.add_argument("--run_id", default="eval_run_001", help="Unique run identifier")
    p.add_argument(
        "--eval_mode",
        default="fix",
        choices=["fix", "test_generation", "coverage_generation"],
        help="Evaluation mode. 'fix' preserves normal SWE-bench patch evaluation; "
             "'test_generation' asks agents to write regression tests and scores "
             "fail-on-base/pass-after-golden-patch; 'coverage_generation' asks "
             "agents to improve tests and compares coverage and mutation metrics.",
    )
    p.add_argument(
        "--coverage_target", action="append", default=None,
        help="Optional repo-relative mutation target. Repeat for multiple modules. "
             "Without it, the agent chooses modules from whole-repository coverage.",
    )
    p.add_argument(
        "--coverage_language",
        choices=["auto", "python", "cpp"],
        default="auto",
        help="Coverage adapter. Auto-detection rejects ambiguous mixed repositories.",
    )
    p.add_argument(
        "--coverage_container_image",
        default=DEFAULT_CPP_COVERAGE_IMAGE,
        help="Prebuilt offline Linux evaluator image used for C++ coverage.",
    )
    p.add_argument(
        "--coverage_source_root",
        action="append",
        default=None,
        help="Repository-relative production source root; repeat as needed.",
    )
    p.add_argument(
        "--traditional_test_generator", choices=["pynguin"], default=None,
        help="Optional conventional control arm for standalone coverage generation.",
    )
    p.add_argument(
        "--comparison_protocol",
        choices=["independent", "agent_led_shared_targets"],
        default="independent",
        help="Comparison target-selection protocol (default: legacy independent).",
    )
    p.add_argument(
        "--shared_generation_budget", type=int, default=900,
        help="Generation-only wall-time seconds per arm in shared-target mode.",
    )
    p.add_argument("--pynguin_version", default="0.45.0")
    p.add_argument("--pynguin_seed", type=int, default=0)
    p.add_argument("--pynguin_total_budget", type=int, default=900)
    p.add_argument(
        "--pynguin_module_slice",
        type=int,
        default=60,
        help="Maximum Pynguin search seconds per module (default: 60).",
    )
    p.add_argument(
        "--pynguin_module_finalization_grace",
        type=int,
        default=30,
        help="Extra seconds per module for minimization/assertion/export (default: 30).",
    )
    p.add_argument(
        "--pynguin_test_execution_timeout",
        type=int,
        default=1,
        help="Maximum seconds for one generated candidate test (default: 1).",
    )
    p.add_argument(
        "--pynguin_force_subprocess",
        action="store_true",
        help="Execute every generated candidate in a killable subprocess.",
    )
    p.add_argument(
        "--pynguin_verbose",
        action="store_true",
        help="Enable Pynguin INFO logs and retain complete per-module output.",
    )
    p.add_argument("--pynguin_assertion_mode", default="SIMPLE")
    p.add_argument(
        "--skip_pynguin", action="store_true",
        help="Reuse a matching cached Pynguin prediction without running Pynguin. "
             "Reports a missing cached prediction when none is available.",
    )
    p.add_argument(
        "--force_pynguin", action="store_true",
        help="Regenerate the Pynguin prediction even when a matching cache exists, "
             "without forcing agent inference. --skip_pynguin takes precedence.",
    )
    p.add_argument(
        "--pynguin_module", action="append", default=None,
        help="Optional import name or source path; repeat to restrict Pynguin eligibility.",
    )
    p.add_argument(
        "--repo_url", default=None,
        help="Standalone coverage_generation repository URL. Bypasses spreadsheet/issue "
             "ingestion and requires --base_commit.",
    )
    p.add_argument(
        "--base_commit", default=None,
        help="Fixed git commit for standalone --repo_url coverage generation.",
    )
    p.add_argument(
        "--coverage_python_executable", default=None,
        help="Python executable used to create standalone disposable environments. "
             "Repository profiles may select a compatibility version (GeoPandas and "
             "Astropy use python3.11).",
    )
    p.add_argument(
        "--coverage_setup_command", default=DEFAULT_COVERAGE_SETUP_COMMAND,
        help="Repository setup command run before each standalone baseline/after phase "
             "(default uses an editable install so source-tree tests can import built "
             "extensions, and also installs pytest).",
    )
    p.add_argument(
        "--coverage_test_command", default=DEFAULT_COVERAGE_TEST_COMMAND,
        help="Complete test command for standalone coverage generation.",
    )
    p.add_argument(
        "--coverage_command", default=None,
        help="Standalone whole-repository coverage command (default: coverage run "
             "--branch --source=. -m pytest).",
    )
    p.add_argument(
        "--coverage_results_command", default=None,
        help="Standalone command that writes coverage JSON to {output}; defaults to coverage json.",
    )
    p.add_argument(
        "--mutation_command", default=None,
        help="Mutation command scoped after coverage analysis. Use {targets} in a custom "
             "command; default: mutmut run for agent-selected modules.",
    )
    p.add_argument(
        "--mutation_results_command", default="mutmut results",
        help="Standalone command that prints the mutation summary.",
    )
    p.add_argument(
        "--mutation_target_statement_budget", type=int, default=500,
        help="Maximum baseline executable statements selected for standalone mutation "
             "testing (default 500; 0 disables the limit). Explicit --coverage_target "
             "values are still subject to this safety budget.",
    )
    p.add_argument(
        "--coverage_tool_install_command", default=None,
        help="Optional standalone coverage/mutation tool installation command.",
    )
    p.add_argument(
        "--coverage_eval_timeout", type=int, default=3600,
        help="Seconds allowed for each before/after coverage+mutation phase (default 3600).",
    )
    p.add_argument(
        "--coverage_flaky_runs", type=int, default=2,
        help="Additional complete pytest reruns in both baseline and generated-test phases "
             "for comparable flakiness checks (default 2).",
    )
    p.add_argument("--github_token", default=None,
                   help="GitHub token (or set GITHUB_TOKEN env var)")
    p.add_argument("--max_workers", type=int, default=4,
                   help="Parallel workers for agent inference (default 4)")
    p.add_argument(
        "--docker_workers", type=int, default=2,
        help="Parallel workers for image validation and Docker evaluation (default 2).",
    )
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
    p.add_argument("--issue_types", action="append", default=None,
                   help="Only run issues whose spreadsheet Type/Category exactly matches this "
                        "value, e.g. --issue_types 1 or --issue_types 1,2. Repeat the flag for "
                        "multiple exact values. Defaults to all types.")
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
    p.add_argument("--force_inference", action="store_true",
                   help="Delete existing agent_predictions.jsonl before Stage 4 and rerun "
                        "inference for all selected instances.")
    p.add_argument("--retry_empty_predictions", action="store_true",
                   help="During Stage 4 resume, rerun instances whose existing prediction has "
                        "an empty model_patch. Useful for SWE-agent format/context failures.")
    p.add_argument("--skip_eval", action="store_true",
                   help="Skip Docker evaluation; only run reporting")
    p.add_argument("--force_eval", action="store_true",
                   help="Re-run evaluation even for instances that already have a cached "
                        "per-instance report. Deletes logs/run_evaluation/{run_id}/{model}/* "
                        "for the evaluated instances before Stage 5 so they are not skipped. "
                        "Use after changing a test_spec (build/test_cmd/pre_install).")
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
    p.add_argument("--sweagent_max_input_tokens", type=int, default=32768,
                   help="SWE-agent model max_input_tokens override for history truncation. "
                        "Lower values can reduce context-window exits on large C++ instances. "
                        "Only used with --agent_backend sweagent.")
    p.add_argument("--codex_timeout", type=int, default=900,
                   help="Wall-clock timeout per instance in seconds for Codex CLI inference. "
                        "Only used with --agent_backend codex.")
    p.add_argument("--codex_sandbox", default="workspace-write",
                   choices=["read-only", "workspace-write", "danger-full-access"],
                   help="Sandbox mode passed to `codex exec`. Only used with "
                        "--agent_backend codex.")
    p.add_argument("--codex_profile", default=None,
                   help="Optional Codex CLI profile passed as `--profile`. Only used with "
                        "--agent_backend codex. When --endpoint is also supplied, this "
                        "profile is generated in a temporary CODEX_HOME.")
    p.add_argument("--codex_model", default=None,
                   help="Optional model override for Codex CLI. Defaults to --model. Only used "
                        "with --agent_backend codex.")
    p.add_argument("--claude_code_timeout", type=int, default=900,
                   help="Wall-clock timeout per instance in seconds for Claude Code CLI inference. "
                        "Only used with --agent_backend claude_code.")
    p.add_argument(
        "--claude_code_max_patch_bytes",
        type=int,
        default=1_000_000,
        help="Reject runaway Claude Code patches larger than this many bytes "
             "(default 1000000; use 0 to disable).",
    )
    p.add_argument(
        "--claude_code_setup_timeout",
        type=int,
        default=1800,
        help="Wall-clock timeout for harness-managed standalone environment setup "
             "before Claude Code inference (default 1800 seconds).",
    )
    p.add_argument(
        "--claude_code_interrupt_retries",
        type=int,
        default=1,
        help="Retries after interruption-style Claude Code exits such as 129/SIGHUP "
             "(default 1). The retry continues from the same working tree.",
    )
    p.add_argument("--claude_code_permission_mode", default="acceptEdits",
                   choices=["acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan"],
                   help="Permission mode passed to `claude -p`. Only used with "
                        "--agent_backend claude_code.")
    p.add_argument("--claude_code_max_turns", type=int, default=60,
                   help="Claude Code max-turns metadata/env value (default 60). Current local Claude "
                        "CLI versions may not expose a --max-turns flag, so the pipeline does "
                        "not pass it as a CLI argument.")
    p.add_argument("--claude_code_model", default=None,
                   help="Optional model override for Claude Code CLI. Defaults to --model. Only "
                        "used with --agent_backend claude_code.")
    p.add_argument("--agy_timeout", type=int, default=900,
                   help="Wall-clock timeout per instance in seconds for Antigravity CLI inference. "
                        "Only used with --agent_backend agy.")
    p.add_argument("--agy_print_timeout", default="15m",
                   help="Value passed to `agy -p --print-timeout` (e.g. '15m'). Only used with "
                        "--agent_backend agy.")
    p.add_argument("--agy_effort", default=None, choices=["low", "medium", "high"],
                   help="Optional reasoning effort passed to `agy -p --effort`. Only used with "
                        "--agent_backend agy.")
    p.add_argument("--agy_model", default=None,
                   help="Optional model override for Antigravity CLI. Defaults to --model. Only "
                        "used with --agent_backend agy.")
    p.add_argument("--clean_images", action="store_true",
                   help="Delete per-instance Docker images after eval. In test-generation "
                        "mode deletion occurs only after report.json is saved. Saves disk "
                        "space on large runs at the cost of slower re-runs; shared "
                        "sweb.base.* and sweb.env.* images are kept.")
    p.add_argument("--no_ingest_cache", action="store_true",
                   help="Ignore the ingest row cache and re-fetch all GitHub data from scratch.")
    return p.parse_args()


def _parse_issue_types(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    from swebench.eval_pipeline.ingest import normalize_issue_type

    parsed = {normalize_issue_type(v) for v in values}
    parsed.discard("")
    return parsed or None


def _eval_subprocess_target(kw, result_queue=None):
    """Module-level target for spawn-pickling; runs the harness eval."""
    import traceback

    from swebench.harness.run_evaluation import main as run_eval
    try:
        report_path = run_eval(**kw)
    except Exception:
        if result_queue is not None:
            result_queue.put({"ok": False, "traceback": traceback.format_exc()})
        raise
    else:
        if result_queue is not None:
            result_queue.put({"ok": True, "report_path": str(report_path) if report_path else ""})


def _run_eval_with_timeout(timeout_seconds: int, **eval_kwargs) -> bool:
    """Run swebench.harness.run_evaluation.main in a subprocess with a wall-clock cap.

    Returns True if it finished within the budget, False if it had to be killed.
    Reports/logs already written to disk are preserved either way.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    proc = ctx.Process(
        target=_eval_subprocess_target,
        args=(eval_kwargs, result_queue),
        daemon=False,
    )
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
        result_queue.close()
        result_queue.join_thread()
        return False
    child_result = None
    try:
        child_result = result_queue.get(timeout=1)
    except Exception:
        pass
    finally:
        result_queue.close()
        result_queue.join_thread()
    if proc.exitcode:
        if child_result and child_result.get("traceback"):
            logger.error("Eval subprocess failed:\n%s", child_result["traceback"])
        else:
            logger.error("Eval subprocess exited with code %s", proc.exitcode)
        return False
    if child_result and child_result.get("report_path"):
        logger.info("Harness run report written to %s", child_result["report_path"])
    return True


def _run_agent_backend(args, instances: list[dict], output_file: str,
                       inference_model: str, github_token: str | None) -> None:
    """Dispatch one inference backend for both SWE-bench and standalone modes."""
    hidden_paths = [
        path
        for path in (
            getattr(args, "log_dir", None),
            getattr(args, "spreadsheet", None),
            *getattr(args, "inference_hidden_path", []),
        )
        if path
    ]
    if args.agent_backend == "sweagent":
        from swebench.eval_pipeline.swe_agent_inference import run_sweagent_inference
        run_sweagent_inference(
            instances=instances, output_file=output_file, model_name=inference_model,
            github_token=github_token, max_workers=args.max_workers,
            sweagent_config=args.sweagent_config, api_base=args.endpoint,
            api_key=args.api_key, retry_empty_predictions=args.retry_empty_predictions,
            max_input_tokens=args.sweagent_max_input_tokens, eval_mode=args.eval_mode,
            network_policy=args.inference_network_policy,
        )
    elif args.agent_backend == "codex":
        from swebench.eval_pipeline.codex_inference import run_codex_inference
        run_codex_inference(
            instances=instances, output_file=output_file, model_name=inference_model,
            github_token=github_token, max_workers=args.max_workers,
            timeout=args.codex_timeout, sandbox=args.codex_sandbox,
            profile=args.codex_profile, api_base=args.endpoint, api_key=args.api_key,
            retry_empty_predictions=args.retry_empty_predictions, eval_mode=args.eval_mode,
            network_policy=args.inference_network_policy,
            hidden_paths=hidden_paths,
        )
    elif args.agent_backend == "claude_code":
        from swebench.eval_pipeline.claude_code_inference import run_claude_code_inference
        run_claude_code_inference(
            instances=instances, output_file=output_file, model_name=inference_model,
            github_token=github_token, max_workers=args.max_workers,
            timeout=args.claude_code_timeout,
            permission_mode=args.claude_code_permission_mode, api_base=args.endpoint,
            api_key=args.api_key, retry_empty_predictions=args.retry_empty_predictions,
            max_turns=args.claude_code_max_turns, eval_mode=args.eval_mode,
            interrupt_retries=args.claude_code_interrupt_retries,
            network_policy=args.inference_network_policy,
            setup_timeout=args.claude_code_setup_timeout,
            hidden_paths=hidden_paths,
            max_patch_bytes=args.claude_code_max_patch_bytes,
        )
    elif args.agent_backend == "agy":
        from swebench.eval_pipeline.agy_inference import run_agy_inference
        run_agy_inference(
            instances=instances, output_file=output_file, model_name=inference_model,
            github_token=github_token, max_workers=args.max_workers,
            timeout=args.agy_timeout, print_timeout=args.agy_print_timeout,
            effort=args.agy_effort,
            retry_empty_predictions=args.retry_empty_predictions, eval_mode=args.eval_mode,
            network_policy=args.inference_network_policy,
            hidden_paths=hidden_paths,
        )
    else:
        from swebench.eval_pipeline.agent_inference import run_agent_inference_for_level
        from swebench.eval_pipeline.inference import make_clients
        anthropic_client, _ = make_clients(
            args.model, endpoint=args.endpoint, api_key=args.api_key
        )
        run_agent_inference_for_level(
            instances=instances, output_file=output_file, model_name=inference_model,
            anthropic_client=anthropic_client, github_token=github_token,
            max_turns=args.max_turns, max_workers=args.max_workers,
            eval_mode=args.eval_mode,
            network_policy=args.inference_network_policy,
            hidden_paths=hidden_paths,
        )


def _standalone_coverage_instance(args) -> dict:
    if not args.base_commit:
        raise SystemExit("--base_commit is required with --repo_url")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", args.base_commit):
        raise SystemExit("--base_commit must be a full 40- or 64-character commit hash")
    targets = []
    for raw_path in args.coverage_target or []:
        path = raw_path.strip().replace("\\", "/")
        if not path:
            continue
        if path.startswith("/"):
            raise SystemExit("--coverage_target values must be repository-relative paths")
        while path.startswith("./"):
            path = path[2:]
        targets.append(path)
    if any(".." in Path(path).parts for path in targets):
        raise SystemExit("--coverage_target values must be repository-relative paths")
    source_roots = []
    for raw_root in args.coverage_source_root or []:
        source_root = raw_root.strip().replace("\\", "/")
        while source_root.startswith("./"):
            source_root = source_root[2:]
        if (
            not source_root
            or source_root.startswith("/")
            or ".." in Path(source_root).parts
        ):
            raise SystemExit(
                "--coverage_source_root values must be repository-relative paths"
            )
        source_roots.append(source_root.rstrip("/"))
    if args.mutation_command and not targets and "{targets}" not in args.mutation_command:
        raise SystemExit(
            "repository-wide --mutation_command must contain {targets}; otherwise "
            "the pipeline cannot enforce agent-selected mutation scope"
        )
    parsed = urlparse(args.repo_url)
    repo_path = parsed.path if parsed.scheme else args.repo_url
    repo_path = repo_path.strip("/")
    if repo_path.endswith(".git"):
        repo_path = repo_path[:-4]
    profile = STANDALONE_COVERAGE_REPO_PROFILES.get(repo_path.lower(), {})
    language = (
        profile.get("coverage_language")
        if args.coverage_language == "auto" and profile.get("coverage_language")
        else args.coverage_language
    )
    if profile.get("coverage_language") and language != profile["coverage_language"]:
        profile = {}
    if language == "cpp":
        pynguin_overrides = (
            args.traditional_test_generator == "pynguin"
            or args.pynguin_module
            or args.comparison_protocol != "independent"
        )
        if pynguin_overrides:
            raise SystemExit(
                "Pynguin and shared Pynguin comparison options are unsupported "
                "with --coverage_language cpp"
            )
    setup_command = args.coverage_setup_command
    test_command = args.coverage_test_command
    coverage_command = args.coverage_command
    coverage_results_command = args.coverage_results_command
    mutation_results_command = args.mutation_results_command
    if profile:
        if setup_command == DEFAULT_COVERAGE_SETUP_COMMAND:
            setup_command = profile["coverage_setup_command"]
        if test_command == DEFAULT_COVERAGE_TEST_COMMAND:
            test_command = profile["coverage_test_command"]
        if coverage_command is None:
            coverage_command = profile["coverage_command"]
        if coverage_results_command is None:
            coverage_results_command = profile.get("coverage_results_command")
        if (
            mutation_results_command == "mutmut results"
            and profile.get("coverage_language") != "cpp"
        ):
            # mutmut 2.5's results renderer crashes through Pony ORM on the
            # Python 3.13 environment; its run progress already has the counts.
            mutation_results_command = "true"
        logger.info("Using standalone coverage profile for %s", repo_path.lower())
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "__", repo_path)
    identity = hashlib.sha256(
        json.dumps([args.repo_url, args.base_commit, sorted(targets)]).encode()
    ).hexdigest()[:10]
    return {
        "instance_id": f"standalone__{slug}-{identity}",
        "repo": args.repo_url,
        "repo_url": args.repo_url,
        "base_commit": args.base_commit,
        "problem_statement": "",
        "coverage_targets": sorted(set(targets)),
        "coverage_language": language,
        "coverage_tool": (
            "gcovr" if language == "cpp"
            else "coverage.py" if language == "python"
            else ""
        ),
        "coverage_container_image": (
            args.coverage_container_image if language in {"auto", "cpp"} else ""
        ),
        "coverage_source_roots": (
            sorted(set(source_roots))
            if args.coverage_source_root is not None
            else profile.get("coverage_source_roots", [])
        ),
        "coverage_python_executable": (
            args.coverage_python_executable
            or profile.get("coverage_python_executable")
        ),
        "coverage_setup_command": setup_command,
        "coverage_environment_preflight_command": profile.get(
            "coverage_environment_preflight_command"
        ),
        "coverage_test_command": test_command,
        "coverage_reset_command": profile.get("coverage_reset_command"),
        "coverage_command": coverage_command,
        "coverage_pytest_command": profile.get("coverage_pytest_command"),
        "coverage_results_command": coverage_results_command,
        "mutation_command": args.mutation_command,
        "mutation_results_command": mutation_results_command,
        "mutation_supported": (
            language != "cpp"
            or bool(
                args.mutation_command
                and args.mutation_results_command != "mutmut results"
            )
        ),
        "mutation_test_style": profile.get("mutation_test_style"),
        "mutation_tests_dir": profile.get("mutation_tests_dir"),
        "mutation_excluded_targets": profile.get("mutation_excluded_targets", []),
        "mutation_target_statement_budget": args.mutation_target_statement_budget,
        "coverage_phase_timeout": profile.get("coverage_phase_timeout", 0),
        "pynguin_warning_filters": profile.get("pynguin_warning_filters", []),
        "pynguin_ignore_noncallable_signatures": profile.get(
            "pynguin_ignore_noncallable_signatures", False
        ),
        "coverage_tool_install_command": (
            args.coverage_tool_install_command
            or ("true" if language == "cpp" else None)
        ),
        "standalone": True,
    }


def _reuse_cached_pynguin_prediction(args) -> bool:
    """Return whether the matching control cache may be reused."""
    return args.skip_pynguin or not (args.force_inference or args.force_pynguin)


def _resolve_standalone_coverage_language(
    instance: dict, github_token: str | None, work_root: Path
) -> None:
    """Resolve auto language and generic commands against a clean checkout."""
    from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
    from swebench.eval_pipeline.coverage_adapters import (
        default_commands,
        detect_coverage_language,
        discover_cpp_sources,
    )

    language = instance.get("coverage_language", "auto")
    repo_dir = None
    try:
        if language == "auto":
            repo_dir = _clone_repo_at_commit(
                instance.get("repo_url") or instance["repo"],
                instance["base_commit"],
                github_token,
                tmp_root=work_root,
            )
            language = detect_coverage_language(repo_dir)
            instance["coverage_language"] = language
        commands = default_commands(language, instance.get("coverage_source_roots"))
        if language == "cpp":
            # The pinned evaluator image already contains the C++ coverage
            # toolchain. Avoid Python/Mutmut installation attempts in the
            # network-disabled container.
            instance["coverage_tool_install_command"] = (
                instance.get("coverage_tool_install_command") or "true"
            )
            if instance.get("coverage_setup_command") == DEFAULT_COVERAGE_SETUP_COMMAND:
                instance["coverage_setup_command"] = commands.setup
            if instance.get("coverage_test_command") == DEFAULT_COVERAGE_TEST_COMMAND:
                instance["coverage_test_command"] = commands.test
            instance["coverage_reset_command"] = (
                instance.get("coverage_reset_command") or commands.reset
            )
            instance["coverage_command"] = (
                instance.get("coverage_command") or commands.run
            )
            instance["coverage_results_command"] = (
                instance.get("coverage_results_command") or commands.report
            )
            if repo_dir:
                instance["coverage_targets_discovered"] = discover_cpp_sources(
                    repo_dir, instance.get("coverage_source_roots")
                )
        instance["coverage_tool"] = "gcovr" if language == "cpp" else "coverage.py"
        if language == "python":
            instance["coverage_container_image"] = ""
        instance["mutation_supported"] = (
            language != "cpp"
            or bool(
                instance.get("mutation_command")
                and instance.get("mutation_results_command") != "mutmut results"
            )
        )
    finally:
        if repo_dir:
            shutil.rmtree(repo_dir, ignore_errors=True)


def _retain_cached_pynguin_prediction(cached: dict | None, generated: dict) -> dict:
    """Keep a usable control patch when forced regeneration produces none."""
    if generated.get("model_patch") or not (cached or {}).get("model_patch"):
        return generated
    retained = {**cached, "metrics": dict((cached or {}).get("metrics") or {})}
    generated_metrics = generated.get("metrics") or {}
    retained["metrics"]["last_regeneration_failure"] = {
        "error": generated.get("error") or "empty_prediction",
        "wall_time_seconds": generated_metrics.get("wall_time_seconds"),
        "timed_out": generated_metrics.get("timed_out"),
        "attempted_module_count": len(generated_metrics.get("attempted_modules") or []),
        "successful_modules": generated_metrics.get("successful_modules") or [],
    }
    return retained


def _matching_cached_pynguin_prediction(
    rows: list[dict], instance_id: str, args,
    requested_modules: list[str] | None = None,
    setup_profile_fingerprint: str = "",
) -> dict | None:
    """Return the latest control cache matching this repository and policy."""
    matched = None
    for candidate in rows:
        metrics = candidate.get("metrics") or {}
        if (
            candidate.get("instance_id") == instance_id
            and metrics.get("version") == args.pynguin_version
            and metrics.get("seed") == args.pynguin_seed
            and metrics.get("total_budget_seconds") == (
                args.shared_generation_budget
                if args.comparison_protocol == "agent_led_shared_targets"
                else args.pynguin_total_budget
            )
            and metrics.get("module_slice_seconds") == args.pynguin_module_slice
            and metrics.get("module_finalization_grace_seconds")
            == args.pynguin_module_finalization_grace
            and metrics.get("test_execution_timeout_seconds")
            == args.pynguin_test_execution_timeout
            and metrics.get("force_subprocess", False)
            == args.pynguin_force_subprocess
            and metrics.get("verbose", False) == args.pynguin_verbose
            and metrics.get("assertion_mode") == args.pynguin_assertion_mode
            and metrics.get("postprocessing_version")
            == PYNGUIN_POSTPROCESSING_VERSION
            and (
                args.comparison_protocol != "agent_led_shared_targets"
                or (
                    metrics.get("requested_modules")
                    == sorted(set(requested_modules or []))
                    and metrics.get("budget_strategy")
                    == "uncapped_equal_shared_targets"
                    and metrics.get("setup_profile_fingerprint")
                    == setup_profile_fingerprint
                )
            )
        ):
            matched = candidate
    return matched


def _upsert_prediction_by_instance(rows: list[dict], prediction: dict) -> list[dict]:
    """Preserve other repositories while replacing one cached prediction."""
    instance_id = prediction.get("instance_id")
    return [
        *[row for row in rows if row.get("instance_id") != instance_id],
        prediction,
    ]


def _setup_profile_fingerprint(instance: dict) -> str:
    """Identify repository setup/tool policy used by a generated-test arm."""
    fields = {
        key: instance.get(key)
        for key in (
            "coverage_setup_command",
            "coverage_python_executable",
            "coverage_environment_preflight_command",
            "coverage_tool_install_command",
            "coverage_test_command",
            "coverage_command",
            "coverage_results_command",
            "coverage_language",
            "coverage_source_roots",
            "coverage_container_image",
            "coverage_container_digest",
            "toolchain",
            "pynguin_warning_filters",
            "pynguin_ignore_noncallable_signatures",
        )
    }
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True).encode()
    ).hexdigest()[:16]


def _run_standalone_coverage(args, inference_model: str, github_token: str | None) -> None:
    from swebench.eval_pipeline.coverage_generation_eval import (
        apply_target_importability_results,
        evaluate_common_mutation_targets,
        freeze_agent_selected_targets,
        format_baseline_coverage_report,
        prepare_standalone_coverage_baseline,
        run_standalone_coverage_evaluation,
        standalone_baseline_failure,
    )
    from swebench.eval_pipeline.prediction_utils import (
        read_prediction_rows,
        write_prediction_rows,
        write_selected_predictions,
    )
    from swebench.eval_pipeline.prompt_builder import build_all_prompts
    from swebench.eval_pipeline.report import (
        collect_test_generation_results,
        render_coverage_comparison_table,
        render_coverage_generation_table,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    instance = _standalone_coverage_instance(args)
    if not (args.skip_inference and args.skip_eval):
        _resolve_standalone_coverage_language(
            instance, github_token, output_dir / ".coverage-language-checkouts"
        )
    if (
        instance["coverage_language"] == "cpp"
        and (
            args.traditional_test_generator == "pynguin"
            or args.pynguin_module
            or args.comparison_protocol != "independent"
        )
    ):
        raise SystemExit(
            "Pynguin and shared Pynguin comparison options are unsupported for C++"
        )
    eval_run_id = f"{args.run_id}_coveragegen"
    if not args.skip_inference or not args.skip_eval:
        evaluation_failure = _docker_unavailable_reason()
        if evaluation_failure:
            failure_path = output_dir / f"{args.run_id}_evaluation_failure.json"
            _write_evaluation_failure(failure_path, evaluation_failure)
            render_coverage_generation_table(
                results={},
                instances=[instance],
                output_csv=str(output_dir / f"{args.run_id}_results.csv"),
                pipeline_failure=evaluation_failure,
                run_config={
                    "mode": "standalone repository",
                    "repo_url": args.repo_url,
                    "run_id": args.run_id,
                },
            )
            return
    baseline = None
    if not args.skip_inference or not args.skip_eval:
        logger.info("=== Standalone coverage generation: whole-repository baseline ===")
        baseline = prepare_standalone_coverage_baseline(
            instance=instance,
            run_id=eval_run_id,
            log_dir=args.log_dir,
            timeout=args.coverage_eval_timeout,
            flaky_runs=args.coverage_flaky_runs,
            github_token=github_token,
        )
        baseline_failure = standalone_baseline_failure(baseline)
        if baseline_failure:
            baseline_log = (
                Path(args.log_dir).resolve()
                / eval_run_id
                / "baseline"
                / instance["instance_id"]
                / "baseline_coverage.log"
            )
            raise SystemExit(
                f"standalone coverage baseline is invalid: {baseline_failure}; "
                f"see {baseline_log}"
            )
        instance["baseline_coverage_report"] = format_baseline_coverage_report(
            baseline.get("coverage")
        )
    instances = [instance]
    (output_dir / "instances.jsonl").write_text(json.dumps(instance) + "\n")
    prompts = build_all_prompts(instances, eval_mode="coverage_generation")
    _write_prompts_preserving_unselected(
        output_dir / "agent_prompts.jsonl", prompts, preserve_existing=False
    )

    predictions_master = output_dir / "agent_predictions.jsonl"
    if args.force_inference and predictions_master.exists():
        retained = [
            row for row in read_prediction_rows(predictions_master)
            if row.get("instance_id") != instance["instance_id"]
        ]
        from swebench.eval_pipeline.prediction_utils import write_prediction_rows
        write_prediction_rows(predictions_master, retained)
    shared_protocol = args.comparison_protocol == "agent_led_shared_targets"
    if shared_protocol:
        if args.pynguin_module:
            raise SystemExit(
                "--pynguin_module conflicts with agent_led_shared_targets; "
                "targets are frozen from the agent coverage delta"
            )
        if args.agent_backend == "codex":
            args.codex_timeout = args.shared_generation_budget
        elif args.agent_backend == "claude_code":
            args.claude_code_timeout = args.shared_generation_budget
        elif args.agent_backend == "agy":
            args.agy_timeout = args.shared_generation_budget
    if not args.skip_inference:
        logger.info("=== Standalone coverage generation: agent inference ===")
        _run_agent_backend(
            args, instances, str(predictions_master), inference_model, github_token
        )

    selected_path = output_dir / "agent_predictions.selected.jsonl"
    write_selected_predictions(
        predictions_master,
        selected_path,
        backend=args.agent_backend,
        model_name=inference_model,
        eval_mode="coverage_generation",
        instance_ids={instance["instance_id"]},
    )
    selected = read_prediction_rows(selected_path)
    prediction = selected[-1] if selected else {
        "model_name_or_path": inference_model,
        "model_patch": "",
        "metrics": {},
    }
    setup_fingerprint = _setup_profile_fingerprint(instance)
    frozen_target_manifest = None
    manifest_path = output_dir / f"{args.run_id}_target_manifest.json"
    early_agent_result = None
    if shared_protocol and not args.skip_eval:
        logger.info(
            "=== Agent-led shared targets: agent coverage-only evaluation ==="
        )
        early_agent_result = run_standalone_coverage_evaluation(
            instance=instance,
            prediction=prediction,
            run_id=eval_run_id,
            log_dir=args.log_dir,
            timeout=args.coverage_eval_timeout,
            flaky_runs=args.coverage_flaky_runs,
            github_token=github_token,
            baseline=baseline,
            run_mutation=False,
        )
        frozen_target_manifest = freeze_agent_selected_targets(
            (baseline or {}).get("coverage"),
            early_agent_result,
            statement_budget=args.mutation_target_statement_budget,
            excluded_targets=instance.get("mutation_excluded_targets"),
        )
        manifest_path.write_text(json.dumps(frozen_target_manifest, indent=2))
        logger.info("Frozen target manifest written to %s", manifest_path)

    frozen_modules = (
        (frozen_target_manifest or {}).get("import_modules") or []
        if shared_protocol else None
    )
    pynguin_prediction = None
    if args.traditional_test_generator == "pynguin":
        pynguin_path = output_dir / "pynguin_predictions.jsonl"
        cached_pynguin_prediction = None
        pynguin_rows = []
        if pynguin_path.exists():
            pynguin_rows = read_prediction_rows(pynguin_path)
            cached_pynguin_prediction = _matching_cached_pynguin_prediction(
                pynguin_rows, instance["instance_id"], args,
                requested_modules=frozen_modules,
                setup_profile_fingerprint=setup_fingerprint,
            )
        if cached_pynguin_prediction and _reuse_cached_pynguin_prediction(args):
            pynguin_prediction = cached_pynguin_prediction
            logger.info("Reusing cached Pynguin prediction from %s", pynguin_path)
        if (
            pynguin_prediction is None
            and baseline is not None
            and (not shared_protocol or bool(frozen_modules))
            and not args.skip_pynguin
        ):
            logger.info("=== Standalone coverage generation: Pynguin control ===")
            from swebench.eval_pipeline.pynguin_generation import generate_pynguin_prediction

            generated_pynguin_prediction = generate_pynguin_prediction(
                instance,
                baseline.get("coverage") or {},
                Path(args.log_dir) / eval_run_id / "pynguin" / instance["instance_id"],
                github_token=github_token,
                version=args.pynguin_version,
                seed=args.pynguin_seed,
                total_budget=(
                    args.shared_generation_budget
                    if shared_protocol else args.pynguin_total_budget
                ),
                module_slice=args.pynguin_module_slice,
                module_finalization_grace=args.pynguin_module_finalization_grace,
                test_execution_timeout=args.pynguin_test_execution_timeout,
                force_subprocess=args.pynguin_force_subprocess,
                verbose=args.pynguin_verbose,
                diagnostic_dir=(
                    output_dir / f"{args.run_id}_pynguin_module_logs"
                ).resolve(),
                assertion_mode=args.pynguin_assertion_mode,
                explicit_modules=(
                    frozen_modules if shared_protocol else args.pynguin_module
                ),
                budget_strategy=(
                    "uncapped_equal_shared_targets"
                    if shared_protocol else "sequential_slice"
                ),
                setup_profile_fingerprint=setup_fingerprint,
                warning_filters=instance.get("pynguin_warning_filters"),
                ignore_noncallable_signatures=instance.get(
                    "pynguin_ignore_noncallable_signatures", False
                ),
            )
            pynguin_prediction = (
                generated_pynguin_prediction
                if shared_protocol
                else _retain_cached_pynguin_prediction(
                    cached_pynguin_prediction, generated_pynguin_prediction
                )
            )
            if pynguin_prediction is not generated_pynguin_prediction:
                logger.warning(
                    "Pynguin regeneration produced no patch; retaining cached prediction from %s",
                    pynguin_path,
                )
            write_prediction_rows(
                pynguin_path,
                _upsert_prediction_by_instance(pynguin_rows, pynguin_prediction),
            )
        elif pynguin_prediction is None:
            error = (
                "no_agent_selected_targets"
                if shared_protocol and not frozen_modules
                else "missing_cached_prediction"
            )
            pynguin_prediction = {
                "instance_id": instance["instance_id"],
                "model_name_or_path": "pynguin", "model_patch": "",
                "error": error, "metrics": {
                    "method": "pynguin", "version": args.pynguin_version,
                    "seed": args.pynguin_seed,
                    "module_finalization_grace_seconds": (
                        args.pynguin_module_finalization_grace
                    ),
                    "test_execution_timeout_seconds": (
                        args.pynguin_test_execution_timeout
                    ),
                    "force_subprocess": args.pynguin_force_subprocess,
                    "verbose": args.pynguin_verbose,
                    "requested_modules": frozen_modules or [],
                    "budget_strategy": (
                        "uncapped_equal_shared_targets"
                        if shared_protocol else "sequential_slice"
                    ),
                },
            }
    if shared_protocol and frozen_target_manifest is not None:
        apply_target_importability_results(
            frozen_target_manifest,
            ((pynguin_prediction or {}).get("metrics") or {}).get(
                "module_attempts"
            ) or [],
        )
        manifest_path.write_text(json.dumps(frozen_target_manifest, indent=2))
    model_dir = inference_model.replace("/", "__")
    report_dir = Path(args.log_dir) / eval_run_id / model_dir / instance["instance_id"]
    if args.force_eval and report_dir.exists():
        shutil.rmtree(report_dir)
    if not args.skip_eval:
        logger.info("=== Standalone coverage generation: independent coverage evaluation ===")
        result = early_agent_result or run_standalone_coverage_evaluation(
            instance=instance, prediction=prediction, run_id=eval_run_id,
            log_dir=args.log_dir, timeout=args.coverage_eval_timeout,
            flaky_runs=args.coverage_flaky_runs, github_token=github_token,
            baseline=baseline, run_mutation=False,
        )
        arm_predictions = {"agent": prediction}
        arm_results = {"agent": result}
        if pynguin_prediction is not None:
            pynguin_result = run_standalone_coverage_evaluation(
                instance=instance,
                prediction=pynguin_prediction,
                run_id=eval_run_id,
                log_dir=args.log_dir,
                timeout=args.coverage_eval_timeout,
                flaky_runs=args.coverage_flaky_runs,
                github_token=github_token,
                baseline=baseline,
                run_mutation=False,
            )
            arm_predictions["pynguin"] = pynguin_prediction
            arm_results["pynguin"] = pynguin_result
        original, arm_results = evaluate_common_mutation_targets(
            instance, arm_predictions, arm_results, baseline, eval_run_id,
            log_dir=args.log_dir, timeout=args.coverage_eval_timeout,
            github_token=github_token,
            frozen_target_manifest=frozen_target_manifest,
        )
        result = arm_results["agent"]
        result["method_version"] = inference_model
        results = {instance["instance_id"]: result}
        comparison_rows = [original]
        if "pynguin" in arm_results:
            comparison_rows.append(arm_results["pynguin"])
        comparison_rows.append(result)
        render_coverage_comparison_table(
            comparison_rows, str(output_dir / f"{args.run_id}_comparison.csv")
        )
        if "pynguin" in arm_results:
            render_coverage_generation_table(
                {instance["instance_id"]: arm_results["pynguin"]}, instances,
                str(output_dir / f"{args.run_id}_pynguin_results.csv"),
                predictions_path=str(output_dir / "pynguin_predictions.jsonl"),
                run_config={
                    "method": "pynguin",
                    "version": args.pynguin_version,
                    "seed": args.pynguin_seed,
                    "module_finalization_grace_seconds": (
                        args.pynguin_module_finalization_grace
                    ),
                    "test_execution_timeout_seconds": (
                        args.pynguin_test_execution_timeout
                    ),
                    "force_subprocess": args.pynguin_force_subprocess,
                    "verbose": args.pynguin_verbose,
                    "run_id": args.run_id,
                },
            )
    else:
        results = collect_test_generation_results(
            run_id=eval_run_id,
            log_dir=args.log_dir,
            instance_ids={instance["instance_id"]},
            model_name=inference_model,
        )
    render_coverage_generation_table(
        results=results,
        instances=instances,
        output_csv=str(output_dir / f"{args.run_id}_results.csv"),
        predictions_path=str(selected_path),
        run_config={
            "mode": "standalone repository",
            "repo_url": args.repo_url,
            "base_commit": args.base_commit,
            "coverage_scope": "repository",
            "mutation_targets": ";".join(instance["coverage_targets"])
            or "agent-selected from coverage increases",
            "agent_backend": args.agent_backend,
            "model": inference_model,
            "run_id": args.run_id,
        },
    )


def main():
    args = parse_args()
    if (
        args.comparison_protocol == "agent_led_shared_targets"
        and args.pynguin_module
    ):
        raise SystemExit(
            "--pynguin_module conflicts with agent_led_shared_targets; "
            "targets are frozen from the agent coverage delta"
        )
    if args.shared_generation_budget <= 0:
        raise SystemExit("--shared_generation_budget must be positive")
    inference_model = args.model
    if args.agent_backend == "codex" and args.codex_model:
        inference_model = args.codex_model
    elif args.agent_backend == "claude_code" and args.claude_code_model:
        inference_model = args.claude_code_model
    elif args.agent_backend == "agy" and args.agy_model:
        inference_model = args.agy_model
    if args.agent_backend == "codex" and args.api_key and not args.endpoint:
        logger.warning(
            "--api_key is only translated into Codex config when --endpoint is "
            "also supplied. Otherwise Codex uses its existing CLI auth/config."
        )
    if args.agent_backend == "claude_code" and args.endpoint:
        logger.warning(
            "--endpoint for Claude Code is passed as ANTHROPIC_BASE_URL and must "
            "be Anthropic-compatible, not generic OpenAI-compatible."
        )
    if args.agent_backend == "agy" and (args.endpoint or args.api_key):
        logger.warning(
            "--endpoint/--api_key are not supported by the Antigravity CLI backend "
            "and are ignored. agy uses its own cached CLI authentication."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    instances_path = str(output_dir / "instances.jsonl")

    github_token = args.github_token or os.environ.get("GITHUB_TOKEN")
    if args.repo_url:
        if args.eval_mode != "coverage_generation":
            raise SystemExit("--repo_url is only valid with --eval_mode coverage_generation")
        _run_standalone_coverage(args, inference_model, github_token)
        return
    filter_ids = set(args.instance_ids.split(",")) if args.instance_ids else None
    filter_repos = set(args.repos.split(",")) if args.repos else None
    filter_issue_types = _parse_issue_types(args.issue_types)

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
            issue_types=filter_issue_types,
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

    # Apply issue/category type filter. Re-run after loading instances so
    # --skip_ingest and cached JSONL runs behave like fresh spreadsheet ingest.
    if filter_issue_types:
        from swebench.eval_pipeline.ingest import normalize_issue_type

        before = len(instances)
        instances = [
            i for i in instances
            if normalize_issue_type(i.get("category")) in filter_issue_types
        ]
        logger.info(
            f"--issue_types: kept {len(instances)}/{before} instance(s) matching "
            f"{sorted(filter_issue_types)}"
        )

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

    if args.eval_mode == "coverage_generation" and args.coverage_target:
        targets = [path.strip().lstrip("./") for path in args.coverage_target if path.strip()]
        instances = [{**instance, "coverage_targets": targets} for instance in instances]
        logger.info("Coverage targets overridden for %s instance(s): %s", len(instances), targets)

    evaluation_failure = None
    evaluation_failure_path = output_dir / f"{args.run_id}_evaluation_failure.json"
    if not args.skip_eval:
        evaluation_failure = _docker_unavailable_reason()
        if evaluation_failure:
            _write_evaluation_failure(evaluation_failure_path, evaluation_failure)
        elif evaluation_failure_path.exists():
            evaluation_failure_path.unlink()

    # ── Stage 2.5: Base-commit Build Validation ──────────────────────────────
    build_validation: dict[str, dict] = {}
    if not args.skip_validation and not evaluation_failure:
        logger.info("=== Stage 2.5: Validating base_commit builds ===")
        from swebench.eval_pipeline.validate_base import validate_buildable
        build_validation = validate_buildable(
            instances=instances,
            cache_path=output_dir / "build_validation.json",
            max_workers=args.docker_workers,
            force=args.revalidate,
            clean_images=args.clean_images,
        )
        n_bad = sum(1 for iid in (i["instance_id"] for i in instances)
                    if not build_validation.get(iid, {}).get("buildable", True))
        if n_bad:
            logger.info(f"{n_bad}/{len(instances)} instance(s) flagged non-buildable; "
                        f"inference will skip them and the report will mark them excluded.")

    # ── Stage 2.6: FAIL_TO_PASS / PASS_TO_PASS Mining ────────────────────────
    if not args.skip_mining and args.eval_mode == "fix" and not evaluation_failure:
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
        if args.eval_mode == "test_generation":
            logger.warning(
                "--verified_only in test_generation mode still filters by existing "
                "FAIL_TO_PASS metadata; generated-test scoring does not use mining."
            )
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

    # ── Stage 2.8: Issue media download ──────────────────────────────────────
    from swebench.eval_pipeline.media_assets import attach_issue_media
    from swebench.eval_pipeline.instance_builder import write_instances_jsonl

    instances = attach_issue_media(instances, output_dir=output_dir, github_token=github_token)
    if Path(instances_path).exists():
        full_on_disk = []
        with open(instances_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    full_on_disk.append(json.loads(line))
        by_id = {i["instance_id"]: i for i in instances}
        merged = [by_id.get(i["instance_id"], i) for i in full_on_disk]
        on_disk_ids = {i["instance_id"] for i in full_on_disk}
        for i in instances:
            if i["instance_id"] not in on_disk_ids:
                merged.append(i)
        write_instances_jsonl(merged, instances_path)

    # ── Stage 3: Prompt Building ──────────────────────────────────────────────
    logger.info("=== Stage 3: Building prompts ===")
    from swebench.eval_pipeline.prompt_builder import build_all_prompts
    all_prompts = build_all_prompts(instances, eval_mode=args.eval_mode)

    prompts_path = output_dir / "agent_prompts.jsonl"
    prompt_count = _write_prompts_preserving_unselected(
        prompts_path, all_prompts, preserve_existing=bool(filter_ids)
    )
    logger.info(f"Wrote {prompt_count} agent prompts → {prompts_path}")

    # ── Stage 4: Inference (agent-only) ───────────────────────────────────────
    if not args.skip_inference and not evaluation_failure:
        logger.info("=== Stage 4: Running inference ===")

        agent_predictions_file = str(output_dir / "agent_predictions.jsonl")
        if args.force_inference:
            pred_path = Path(agent_predictions_file)
            if pred_path.exists():
                pred_path.unlink()
                logger.info(f"--force_inference: removed {pred_path}")
        inference_instances = [
            instance for instance in instances
            if build_validation.get(instance["instance_id"], {}).get("buildable", True)
        ]
        skipped_nonbuildable = len(instances) - len(inference_instances)
        if skipped_nonbuildable:
            logger.info(
                "Skipping inference for %s non-buildable instance(s)",
                skipped_nonbuildable,
            )
        _run_agent_backend(
            args, inference_instances, agent_predictions_file, inference_model, github_token
        )

    # ── Stage 5: Docker Evaluation (agent-only) ───────────────────────────────
    run_ids: dict[str, str] = {}
    agent_predictions_master_path = str(output_dir / "agent_predictions.jsonl")
    agent_predictions_path = str(output_dir / "agent_predictions.selected.jsonl")
    selected_count = write_selected_predictions(
        source_path=agent_predictions_master_path,
        dest_path=agent_predictions_path,
        backend=args.agent_backend,
        model_name=inference_model,
        eval_mode=args.eval_mode,
        instance_ids={i["instance_id"] for i in instances},
    )
    logger.info(
        f"Selected {selected_count} {args.agent_backend}/{inference_model} prediction(s) "
        f"for eval → {agent_predictions_path}"
    )
    run_id = {
        "test_generation": f"{args.run_id}_testgen",
        "coverage_generation": f"{args.run_id}_coveragegen",
    }.get(args.eval_mode, f"{args.run_id}_agent")
    if not args.skip_eval and not evaluation_failure:
        evaluation_failure = _docker_unavailable_reason()
        if evaluation_failure:
            _write_evaluation_failure(evaluation_failure_path, evaluation_failure)
    if not args.skip_eval and not evaluation_failure:
        logger.info("=== Stage 5: Running Docker evaluation ===")

        if not Path(agent_predictions_path).exists():
            logger.warning(f"Predictions file not found: {agent_predictions_path}")
        else:
            run_ids["agent"] = run_id
            unique_eval_instances = unique_instances_by_id(instances)
            skipped_eval_duplicates = len(instances) - len(unique_eval_instances)
            if skipped_eval_duplicates:
                logger.info(f"Skipping {skipped_eval_duplicates} duplicate instance row(s) before eval")
            if args.eval_mode == "test_generation" and build_validation:
                before_validation_filter = len(unique_eval_instances)
                unique_eval_instances = [
                    instance for instance in unique_eval_instances
                    if build_validation.get(
                        instance["instance_id"], {}
                    ).get("buildable", True)
                ]
                skipped_invalid = before_validation_filter - len(unique_eval_instances)
                if skipped_invalid:
                    logger.info(
                        "Skipping evaluation for %s environment-invalid instance(s)",
                        skipped_invalid,
                    )
            eval_instance_ids = [i["instance_id"] for i in unique_eval_instances]

            # --force_eval: drop cached per-instance report dirs so run_evaluation
            # does not skip them as "already run", AND remove any stale eval
            # container left by a prior run (its name `sweb.eval.<iid>.<run_id>`
            # would otherwise cause a 409 Conflict on create — the bug that made
            # 4881 silently error). Both are best-effort.
            if args.force_eval:
                removed = _clear_selected_evaluation_cache(
                    args.log_dir, run_id, eval_instance_ids
                )
                logger.info(
                    f"--force_eval: cleared {removed} cached report dir(s) and removed "
                    f"any stale eval containers under {args.log_dir}/{run_id}/."
                )
            if args.eval_mode == "test_generation":
                from swebench.eval_pipeline.test_generation_eval import (
                    run_test_generation_evaluation,
                )

                logger.info(
                    f"--- Evaluating generated tests (run_id={run_id}, "
                    f"{len(eval_instance_ids)} instances) ---"
                )
                run_test_generation_evaluation(
                    instances=unique_eval_instances,
                    predictions_path=agent_predictions_path,
                    run_id=run_id,
                    log_dir=args.log_dir,
                    max_workers=args.docker_workers,
                    timeout=1800,
                    clean_images=args.clean_images,
                )
            elif args.eval_mode == "coverage_generation":
                from swebench.eval_pipeline.coverage_generation_eval import (
                    run_coverage_generation_evaluation,
                )

                logger.info(
                    "--- Evaluating coverage-generating tests (run_id=%s, %s instances) ---",
                    run_id, len(eval_instance_ids),
                )
                run_coverage_generation_evaluation(
                    instances=unique_eval_instances,
                    predictions_path=agent_predictions_path,
                    run_id=run_id,
                    log_dir=args.log_dir,
                    max_workers=args.docker_workers,
                    timeout=args.coverage_eval_timeout,
                    flaky_runs=args.coverage_flaky_runs,
                )
            else:
                wallclock = args.eval_wallclock_per_instance * max(1, len(eval_instance_ids))
                logger.info(
                    f"--- Evaluating agent (run_id={run_id}, "
                    f"wallclock_budget={wallclock}s for {len(eval_instance_ids)} instances) ---"
                )

                finished = _run_eval_with_timeout(
                    timeout_seconds=wallclock,
                    dataset_name=instances_path,
                    split="test",
                    instance_ids=eval_instance_ids,
                    predictions_path=agent_predictions_path,
                    max_workers=args.docker_workers,
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
                        f"agent eval hit wall-clock cap. "
                        f"Partial reports under {args.log_dir}/{run_id}/ are preserved."
                    )
    else:
        run_ids["agent"] = run_id

    # ── Stage 6: Reporting ────────────────────────────────────────────────────
    logger.info("=== Stage 6: Generating report ===")
    from swebench.eval_pipeline.report import (
        collect_results,
        collect_test_generation_results,
        render_comparison_table,
        render_coverage_generation_table,
        render_test_generation_table,
    )

    output_csv = str(output_dir / f"{args.run_id}_results.csv")
    run_config = {
        "model": args.model,
        "inference_model": inference_model,
        "eval_mode": args.eval_mode,
        "run_id": args.run_id,
        "output_dir": str(output_dir),
        "max_tokens": args.max_tokens,
        "max_workers": args.max_workers,
        "docker_workers": args.docker_workers,
        "max_cost": args.max_cost,
        "agent_backend": args.agent_backend,
        "limit": args.limit,
        "instance_ids": args.instance_ids or "(all)",
        "repos": args.repos or "(all)",
        "issue_types": args.issue_types or "(all)",
        "has_issue": args.has_issue,
        "has_tests": args.has_tests,
        "verified_only": args.verified_only,
        "skip_ingest": args.skip_ingest,
        "skip_inference": args.skip_inference,
        "force_inference": args.force_inference,
        "retry_empty_predictions": args.retry_empty_predictions,
        "skip_eval": args.skip_eval,
        "skip_validation": args.skip_validation,
        "skip_mining": args.skip_mining,
        "revalidate": args.revalidate,
        "remine": args.remine,
        "mine_workers": args.mine_workers,
        "clean_images": args.clean_images,
        "sweagent_max_input_tokens": args.sweagent_max_input_tokens,
        "codex_timeout": args.codex_timeout,
        "codex_sandbox": args.codex_sandbox,
        "codex_profile": args.codex_profile,
        "codex_model": args.codex_model,
        "claude_code_timeout": args.claude_code_timeout,
        "claude_code_max_patch_bytes": args.claude_code_max_patch_bytes,
        "claude_code_interrupt_retries": args.claude_code_interrupt_retries,
        "claude_code_permission_mode": args.claude_code_permission_mode,
        "claude_code_max_turns": args.claude_code_max_turns,
        "claude_code_model": args.claude_code_model,
        "agy_timeout": args.agy_timeout,
        "agy_print_timeout": args.agy_print_timeout,
        "agy_effort": args.agy_effort,
        "agy_model": args.agy_model,
        "inference_network_policy": args.inference_network_policy,
        "coverage_target": args.coverage_target or "(inferred per instance)",
        "coverage_eval_timeout": args.coverage_eval_timeout,
        "coverage_flaky_runs": args.coverage_flaky_runs,
    }
    if args.eval_mode == "test_generation":
        report_instances = instances
        report_predictions_path = agent_predictions_path
        if args.force_eval and args.skip_inference and filter_ids:
            # A targeted harness repair should update the selected cached
            # reports, then regenerate the complete spreadsheet/sheet cohort.
            # instances.jsonl may currently hold a different batch.
            report_instances = _load_targeted_report_scope(
                spreadsheet_path=args.spreadsheet,
                sheet=args.sheet,
                checkpoint_path=instance_checkpoint_path,
                repos=filter_repos,
                issue_types=filter_issue_types,
                limit=args.limit,
            )
            report_predictions_path = agent_predictions_master_path
        results = collect_test_generation_results(
            run_id=run_id,
            log_dir=args.log_dir,
            instance_ids={i["instance_id"] for i in report_instances},
            model_name=inference_model,
        )
        render_test_generation_table(
            results=results,
            instances=report_instances,
            output_csv=output_csv,
            build_validation=build_validation,
            predictions_path=report_predictions_path,
            run_config=run_config,
            pipeline_failure=evaluation_failure,
        )
    elif args.eval_mode == "coverage_generation":
        results = collect_test_generation_results(
            run_id=run_id,
            log_dir=args.log_dir,
            instance_ids={i["instance_id"] for i in instances},
            model_name=inference_model,
        )
        render_coverage_generation_table(
            results=results,
            instances=instances,
            output_csv=output_csv,
            predictions_path=agent_predictions_path,
            run_config=run_config,
            pipeline_failure=evaluation_failure,
        )
    else:
        results = collect_results(
            run_ids=run_ids,
            log_dir=args.log_dir,
            instance_ids={i["instance_id"] for i in instances},
        )
        render_comparison_table(
            results=results,
            instances=instances,
            output_csv=output_csv,
            build_validation=build_validation,
            predictions_path=agent_predictions_path,
            run_config=run_config,
            pipeline_failure=evaluation_failure,
        )
    logger.info(f"Done. Results saved to {output_csv}")


if __name__ == "__main__":
    main()
