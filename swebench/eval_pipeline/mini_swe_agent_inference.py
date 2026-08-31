"""Stage 4 backend for the official mini-swe-agent v2 ``mini`` CLI."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from tqdm.auto import tqdm

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference import (
    _clean_patch,
    _repair_patch,
    _strip_generated_artifact_diff_blocks,
)
from swebench.eval_pipeline.inference_metrics import with_wall_time
from swebench.eval_pipeline.inference_security import (
    guarded_hidden_paths,
    inference_input_hash,
    inference_worktree_root,
)
from swebench.eval_pipeline.media_assets import format_issue_media_for_prompt
from swebench.eval_pipeline.network_isolation import (
    guard_command,
    validate_network_policy,
)
from swebench.eval_pipeline.prediction_utils import (
    prediction_matches_backend,
    read_prediction_rows,
    unique_instances_by_id,
    write_prediction_rows,
)
from swebench.eval_pipeline.prompt_builder import (
    _coverage_generation_instruction,
    _problem_text,
    _test_generation_instruction,
)

logger = logging.getLogger(__name__)

AGENT_BACKEND = "mini_swe_agent"
_MINI_SWE_AGENT_TIMEOUT = 900
_MINI_SWE_AGENT_COMMAND_TIMEOUT = 300


def _mini_swe_agent_bin() -> str:
    """Find either official console-script name, preferring ``mini``."""
    import sys

    for name in ("mini", "mini-swe-agent"):
        found = shutil.which(name)
        if found:
            return found
    for name in ("mini", "mini-swe-agent"):
        candidate = Path(sys.executable).parent / name
        if candidate.exists():
            return str(candidate)
    repo_root = Path(__file__).resolve().parents[2]
    for environment in (".venv", "venv"):
        for name in ("mini", "mini-swe-agent"):
            candidate = repo_root / environment / "bin" / name
            if candidate.exists():
                return str(candidate)
    return "mini"


def _mini_problem_text(instance: dict, eval_mode: str = "fix") -> str:
    """Build the task supplied to mini-swe-agent without exposing gold patches."""
    problem = _problem_text(instance)
    target_files = sorted((instance.get("file_contents") or {}).keys())
    fail_to_pass = instance.get("FAIL_TO_PASS") or []

    if eval_mode == "coverage_generation":
        guidance = [
            _coverage_generation_instruction(instance),
            "Inspect the target modules and existing tests, and run tests/coverage while iterating.",
            "Leave the test edits unstaged in the working tree; the evaluator captures git diff.",
        ]
    elif eval_mode == "test_generation":
        guidance = [
            "Write a minimal regression test patch for this SWE-bench issue.",
            "Do not fix the bug or modify implementation/source files.",
            "Only add or modify tests and small test data files required by those tests.",
            "Prefer targeted inspection of relevant tests over broad repository scans.",
            "Leave the test edits unstaged in the working tree; the evaluator captures git diff.",
            _test_generation_instruction(),
        ]
    else:
        guidance = [
            "Resolve this SWE-bench scientific software issue in the local repository.",
            "Make the smallest source change needed to address the issue.",
            "Do not refactor unrelated code or rewrite generated files.",
            "Prefer targeted inspection of relevant files over broad repository scans.",
            "Leave the edits unstaged in the working tree; the evaluator captures git diff.",
        ]
    if target_files:
        guidance.append("Relevant base-commit files from instance construction:")
        guidance.extend(f"- {path}" for path in target_files[:12])
    if fail_to_pass:
        guidance.append("Mined FAIL_TO_PASS tests used for scoring:")
        guidance.extend(f"- {test}" for test in fail_to_pass[:12])

    media = format_issue_media_for_prompt(instance)
    issue = f"\n\nIssue:\n{problem}" if problem else ""
    return (
        f"Repository: {instance['repo']}\n\n"
        + "\n".join(guidance)
        + "\n\n"
        + media
        + issue
    )


def _capture_patch(repo_dir: Path, exclude_cpp_build: bool = False) -> str:
    command = ["git", "add", "-N", "."]
    if exclude_cpp_build:
        from swebench.eval_pipeline.coverage_adapters import COVERAGE_GIT_EXCLUDES

        command = ["git", "add", "-N", "--", ".", *COVERAGE_GIT_EXCLUDES]
    subprocess.run(command, cwd=repo_dir, capture_output=True)
    result = subprocess.run(
        ["git", "-c", "core.fileMode=false", "diff", "--binary", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return result.stdout or ""


def _redact(text: str, secret: str | None) -> str:
    return text.replace(secret, "<redacted>") if secret else text


def _litellm_model_name(model_name: str, api_base: str | None) -> str:
    """Select LiteLLM's OpenAI-compatible provider for custom endpoints."""
    if api_base and not model_name.startswith("openai/"):
        return f"openai/{model_name}"
    return model_name


def _installed_mini_version() -> str:
    try:
        return importlib.metadata.version("mini-swe-agent")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _load_trajectory(path: Path, api_key: str | None = None) -> dict:
    if not path.exists():
        return {}
    text = _redact(path.read_text(errors="replace"), api_key)
    path.write_text(text)
    try:
        trajectory = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(trajectory, dict):
        return {}
    info = trajectory.setdefault("info", {})
    if isinstance(info, dict):
        info.setdefault("mini_version", _installed_mini_version())
    path.write_text(json.dumps(trajectory, indent=2))
    return trajectory


def _trajectory_metrics(trajectory: dict) -> dict:
    """Normalize mini-swe-agent trajectory cost, calls, and token usage."""
    metrics: dict[str, int | float] = {}
    info = trajectory.get("info") if isinstance(trajectory.get("info"), dict) else {}
    stats = info.get("model_stats") if isinstance(info.get("model_stats"), dict) else {}
    cost = stats.get("instance_cost")
    calls = stats.get("api_calls")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        metrics["cost_usd"] = float(cost)
    if isinstance(calls, int) and not isinstance(calls, bool):
        metrics["api_calls"] = calls
        metrics["turns"] = calls

    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "cache_read_input_tokens": ("cache_read_input_tokens", "cached_tokens"),
        "cache_creation_input_tokens": ("cache_creation_input_tokens",),
    }
    tool_calls = 0
    for message in trajectory.get("messages", []):
        if not isinstance(message, dict):
            continue
        extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
        actions = extra.get("actions")
        if isinstance(actions, list):
            tool_calls += len(actions)
        response = extra.get("response")
        usage = response.get("usage") if isinstance(response, dict) else None
        if not isinstance(usage, dict):
            continue
        for target, names in aliases.items():
            for name in names:
                value = usage.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[target] += int(value)
                    break
        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict) and not any(
            isinstance(usage.get(name), (int, float))
            for name in aliases["cache_read_input_tokens"]
        ):
            cached = prompt_details.get("cached_tokens")
            if isinstance(cached, (int, float)) and not isinstance(cached, bool):
                totals["cache_read_input_tokens"] += int(cached)
    metrics.update({key: value for key, value in totals.items() if value})
    if totals["input_tokens"] or totals["output_tokens"]:
        metrics["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    if tool_calls:
        metrics["tool_calls"] = tool_calls
    mini_version = info.get("mini_version")
    if mini_version:
        metrics["mini_swe_agent_version"] = str(mini_version)
    return metrics


def _command(
    *,
    executable: str,
    repo_dir: Path,
    prompt: str,
    trajectory_path: Path,
    model_name: str,
    config_path: str | None,
    command_timeout: int,
    cost_limit: float,
    api_base: str | None,
) -> list[str]:
    base_config = (
        str(Path(config_path).expanduser().resolve()) if config_path else "mini.yaml"
    )
    command = [
        executable,
        "--config",
        base_config,
        "--config",
        f"environment.cwd={json.dumps(str(repo_dir))}",
        "--config",
        f"environment.timeout={command_timeout}",
    ]
    if api_base:
        command += [
            "--config",
            f"model.model_kwargs.api_base={json.dumps(api_base.rstrip('/'))}",
        ]
    command += [
        "--environment-class",
        "local",
        "--model",
        _litellm_model_name(model_name, api_base),
        "--task",
        prompt,
        "--yolo",
        "--exit-immediately",
        "--cost-limit",
        str(cost_limit),
        "--output",
        str(trajectory_path),
    ]
    return command


def run_mini_swe_agent_inference(
    instances: list[dict],
    output_file: str,
    model_name: str,
    github_token: Optional[str] = None,
    max_workers: int = 2,
    timeout: int = _MINI_SWE_AGENT_TIMEOUT,
    command_timeout: int = _MINI_SWE_AGENT_COMMAND_TIMEOUT,
    cost_limit: float = 0,
    config_path: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    retry_empty_predictions: bool = False,
    eval_mode: str = "fix",
    network_policy: str = "unrestricted",
    hidden_paths: list[str] | None = None,
) -> None:
    """Run the official mini-swe-agent v2 host CLI and write prediction JSONL."""
    if timeout <= 0 or command_timeout <= 0:
        raise ValueError("mini-swe-agent timeouts must be positive")
    if cost_limit < 0:
        raise ValueError("mini-swe-agent cost limit cannot be negative")
    if config_path and not Path(config_path).expanduser().is_file():
        raise FileNotFoundError(f"mini-swe-agent config not found: {config_path}")
    validate_network_policy(network_policy, api_base)

    # The mini process runs with ``cwd=repo_dir``.  Keep every harness-owned
    # path absolute so mini cannot resolve a relative ``--output`` path inside
    # the cloned repository and have patch capture mistake its trajectory for
    # a model edit.
    out_path = Path(output_file).expanduser().resolve()
    unique_instances = unique_instances_by_id(instances)
    input_hashes = {
        inst["instance_id"]: inference_input_hash(inst) for inst in unique_instances
    }
    existing_ids: set[str] = set()
    retained_records: list[dict] = []
    for row in read_prediction_rows(out_path):
        if prediction_matches_backend(
            row,
            AGENT_BACKEND,
            model_name,
            eval_mode=eval_mode,
            input_hash=input_hashes.get(row.get("instance_id")),
        ):
            if (row.get("model_patch") or "").strip() or not retry_empty_predictions:
                existing_ids.add(row["instance_id"])
                retained_records.append(row)
            else:
                logger.info(
                    "[%s] retrying prior empty mini-swe-agent prediction",
                    row.get("instance_id"),
                )
        else:
            retained_records.append(row)

    todo = [
        inst for inst in unique_instances if inst["instance_id"] not in existing_ids
    ]
    duplicate_count = len(instances) - len(unique_instances)
    if existing_ids:
        logger.info(
            "Resuming mini-swe-agent: %d predictions already written", len(existing_ids)
        )
    if duplicate_count:
        logger.info(
            "Skipping %d duplicate instance row(s) before mini-swe-agent inference",
            duplicate_count,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if retry_empty_predictions and out_path.exists():
        write_prediction_rows(out_path, retained_records)

    logs_dir = out_path.parent / "mini_swe_agent_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    worktree_root = inference_worktree_root(AGENT_BACKEND)
    config_root = inference_worktree_root(f"{AGENT_BACKEND}-config")
    global_config_dir = Path(tempfile.mkdtemp(prefix="mswea_config_", dir=config_root))
    effective_hidden_paths = guarded_hidden_paths(
        network_policy, out_path, hidden_paths or []
    )
    write_lock = threading.Lock()
    executable = _mini_swe_agent_bin()
    secret_to_redact = api_key or os.environ.get("OPENAI_API_KEY")

    def _process_one(instance: dict) -> None:
        instance_id = instance["instance_id"]
        repo_dir: Path | None = None
        started = time.perf_counter()
        trajectory_path = logs_dir / f"{instance_id}.traj.json"
        stdout_path = logs_dir / f"{instance_id}.stdout.log"
        stderr_path = logs_dir / f"{instance_id}.stderr.log"
        stdout_path.write_text("")
        stderr_path.write_text("")
        trajectory: dict[str, Any] = {}
        error = ""
        patch = ""
        try:
            repo_dir = _clone_repo_at_commit(
                instance["repo"],
                instance["base_commit"],
                github_token,
                tmp_root=worktree_root,
            )
            if eval_mode == "coverage_generation":
                from swebench.eval_pipeline.coverage_adapters import (
                    install_coverage_runner,
                )

                install_coverage_runner(repo_dir, instance)
            command = _command(
                executable=executable,
                repo_dir=repo_dir,
                prompt=_mini_problem_text(instance, eval_mode),
                trajectory_path=trajectory_path,
                model_name=model_name,
                config_path=config_path,
                command_timeout=command_timeout,
                cost_limit=cost_limit,
                api_base=api_base,
            )
            command = guard_command(
                command,
                policy=network_policy,
                endpoint=api_base,
                hidden_paths=effective_hidden_paths,
            )
            env = dict(os.environ)
            env.update(
                {
                    "MSWEA_GLOBAL_CONFIG_DIR": str(global_config_dir),
                    "MSWEA_CONFIGURED": "true",
                    "MSWEA_SILENT_STARTUP": "1",
                }
            )
            if api_key:
                env["OPENAI_API_KEY"] = api_key
            result = subprocess.run(
                command,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            stdout_path.write_text(_redact(result.stdout or "", secret_to_redact))
            stderr_path.write_text(_redact(result.stderr or "", secret_to_redact))
            if result.returncode:
                error = f"mini-swe-agent exited with code {result.returncode}"
                logger.warning("[%s] %s", instance_id, error)
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else (exc.stdout or b"").decode(errors="replace")
            )
            stderr = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr or b"").decode(errors="replace")
            )
            stdout_path.write_text(_redact(stdout, secret_to_redact))
            stderr_path.write_text(_redact(stderr, secret_to_redact))
            error = "timeout"
            logger.error(
                "[%s] mini-swe-agent timed out after %ss", instance_id, timeout
            )
        except Exception as exc:
            error = str(exc)
            stderr_path.write_text(
                _redact(f"{type(exc).__name__}: {exc}\n", secret_to_redact)
            )
            logger.error("Error on %s: %s", instance_id, exc)
            traceback.print_exc()
        finally:
            trajectory = _load_trajectory(trajectory_path, secret_to_redact)
            if not trajectory:
                if not error:
                    error = "mini-swe-agent did not write a trajectory"
                trajectory = {
                    "info": {
                        "mini_version": _installed_mini_version(),
                        "harness_error": _redact(error, secret_to_redact),
                    },
                    "messages": [],
                    "trajectory_format": "swebench-mini-swe-agent-error-1",
                }
                trajectory_path.write_text(json.dumps(trajectory, indent=2))
            if repo_dir:
                try:
                    patch = _repair_patch(
                        _clean_patch(
                            _strip_generated_artifact_diff_blocks(
                                _capture_patch(
                                    repo_dir,
                                    instance.get("coverage_language") == "cpp",
                                )
                            )
                        )
                    )
                except Exception as exc:
                    error = error or f"patch capture failed: {exc}"
                shutil.rmtree(repo_dir, ignore_errors=True)

        record = {
            "instance_id": instance_id,
            "model_patch": patch,
            "model_name_or_path": model_name,
            "agent_backend": AGENT_BACKEND,
            "eval_mode": eval_mode,
            "inference_input_hash": input_hashes[instance_id],
            "metrics": with_wall_time(
                _trajectory_metrics(trajectory), time.perf_counter() - started
            ),
        }
        if error:
            record["error"] = _redact(error, secret_to_redact)
        logger.info("[%s] mini-swe-agent patch_len=%d", instance_id, len(patch))
        with write_lock:
            with out_path.open("a") as output:
                print(json.dumps(record), file=output, flush=True)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_process_one, instance): instance for instance in todo
            }
            with tqdm(
                total=len(todo), desc=f"mini-swe-agent inference ({model_name})"
            ) as progress:
                for future in as_completed(futures):
                    future.result()
                    progress.update(1)
    finally:
        shutil.rmtree(global_config_dir, ignore_errors=True)
