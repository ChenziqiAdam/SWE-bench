"""Stage 4 (agentic): Multi-turn tool-use agent that explores a cloned repo and produces a patch.

The agent receives the issue description (L2 style) and tools to read/search/write files
in a temporary clone of the repo at base_commit. When done it calls submit_patch() which
captures `git diff HEAD` as the unified diff.

Output format is identical to inference.py so Stage 5 (Docker eval) is unchanged.
"""
from __future__ import annotations

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
from typing import Optional

from tqdm.auto import tqdm

from swebench.eval_pipeline.constants import MODEL_COST_PER_INPUT, MODEL_COST_PER_OUTPUT
from swebench.eval_pipeline.inference import _calc_cost, _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import with_wall_time
from swebench.eval_pipeline.media_assets import format_issue_media_for_prompt
from swebench.eval_pipeline.network_isolation import (
    guard_command,
    validate_network_policy,
)
from swebench.eval_pipeline.prediction_utils import prediction_matches_backend, unique_instances_by_id
from swebench.eval_pipeline.prompt_builder import (
    _coverage_generation_instruction,
    _problem_text,
    _test_generation_instruction,
)

logger = logging.getLogger(__name__)
AGENT_BACKEND = "builtin"

SYSTEM_PROMPT = (
    "You are an expert software engineer working on a real codebase. "
    "You have been given a GitHub issue to resolve. "
    "Use the provided tools to explore the repository, understand the code, "
    "and implement a fix. When your changes are complete, call submit_patch()."
)

TEST_GENERATION_SYSTEM_PROMPT = (
    "You are an expert software engineer working on a real codebase. "
    "You have been given a GitHub issue and must add or modify tests only. "
    "Do not fix implementation code. When your test changes are complete, "
    "call submit_patch()."
)

COVERAGE_GENERATION_SYSTEM_PROMPT = (
    "You are an expert software engineer improving tests in a real codebase. "
    "There is no issue to resolve and production code must not be changed. "
    "Use the supplied repository-wide baseline coverage report to choose poorly "
    "tested production modules, run tests and coverage, add meaningful tests, "
    "and call submit_patch() when complete."
)

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from repo root"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and directories at a path in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from repo root (default '.')"},
            },
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a text pattern in the repository using grep. Returns matching lines with file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pattern to search for"},
                "path": {"type": "string", "description": "Subdirectory to search in (default '.')"},
                "file_pattern": {"type": "string", "description": "Glob pattern to filter files, e.g. '*.py'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the repository, for tests, coverage, or inspection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (overwrite) a file in the repository with new content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from repo root"},
                "content": {"type": "string", "description": "Full new content of the file"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "submit_patch",
        "description": "Signal that your edits are complete. This captures git diff and ends the session.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

_MAX_READ_CHARS = 50_000
_MAX_SEARCH_CHARS = 5_000


def _redact_secret(text: object, secret: Optional[str]) -> str:
    value = str(text)
    if secret:
        value = value.replace(secret, "<redacted>")
    return value


def _clone_repo_at_commit(
    repo: str,
    base_commit: str,
    github_token: Optional[str],
    tmp_root: str | Path | None = None,
) -> Path:
    """Create a history-isolated checkout containing only ``base_commit``.

    A full clone followed by ``git reset`` is unsafe for benchmark inference:
    later commits remain readable through remote refs and ``git log --all``.
    Fetch the exact base commit with depth one and fail closed if the resulting
    repository contains any reachable parent history.
    """
    root = Path(tmp_root or os.environ.get("SWE_AGENT_TMPDIR") or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="sweagent_", dir=str(root)))
    if "://" in repo or repo.startswith("git@"):
        url = repo
        if github_token and url.startswith("https://github.com/"):
            url = url.replace("https://", f"https://{github_token}@", 1)
    else:
        token_prefix = f"{github_token}@" if github_token else ""
        repo_name = repo[:-4] if repo.endswith(".git") else repo
        url = f"https://{token_prefix}github.com/{repo_name}.git"
    try:
        subprocess.run(
            ["git", "init", "--quiet", str(tmpdir)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", url],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "fetch",
                "--quiet",
                "--depth=1",
                "--no-tags",
                "origin",
                base_commit,
            ],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "benchmark-base", "HEAD"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "remote", "remove", "origin"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "reflog", "expire", "--expire=now", "--all"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "gc", "--quiet", "--prune=now"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        reachable = subprocess.run(
            ["git", "rev-list", "--count", "--all"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        remotes = subprocess.run(
            ["git", "remote"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if reachable != "1" or remotes:
            raise RuntimeError(
                "history isolation failed: expected one reachable commit and no remotes"
            )

        # FETCH_HEAD can disclose the authenticated source URL. It is not needed
        # after the detached checkout and should not be visible to the agent.
        (tmpdir / ".git" / "FETCH_HEAD").unlink(missing_ok=True)
    except RuntimeError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raw_stderr = e.stderr or ""
        if isinstance(raw_stderr, bytes):
            raw_stderr = raw_stderr.decode(errors="replace")
        stderr = _redact_secret(raw_stderr, github_token)
        raise RuntimeError(
            f"git {' '.join(e.cmd[:2])} failed with exit code {e.returncode}"
            + (f": {stderr[-500:]}" if stderr else "")
        ) from e
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return tmpdir


def _execute_tool(
    tool_name: str,
    tool_input: dict,
    repo_dir: Path,
    network_policy: str = "unrestricted",
) -> str:
    """Execute a tool call and return its string result."""
    if tool_name == "read_file":
        path = repo_dir / tool_input["path"]
        try:
            content = path.read_text(errors="replace")
            if len(content) > _MAX_READ_CHARS:
                content = content[:_MAX_READ_CHARS] + "\n... [truncated]"
            return content
        except FileNotFoundError:
            return f"Error: file not found: {tool_input['path']}"
        except Exception as e:
            return f"Error reading file: {e}"

    elif tool_name == "list_dir":
        path = repo_dir / tool_input.get("path", ".")
        try:
            entries = sorted(os.listdir(path))
            return "\n".join(entries) if entries else "(empty directory)"
        except FileNotFoundError:
            return f"Error: path not found: {tool_input.get('path', '.')}"
        except Exception as e:
            return f"Error listing directory: {e}"

    elif tool_name == "search_code":
        query = tool_input["query"]
        search_path = tool_input.get("path", ".")
        file_pattern = tool_input.get("file_pattern")
        if file_pattern:
            cmd = ["grep", "-r", "-n", f"--include={file_pattern}", query, search_path]
        else:
            cmd = ["grep", "-r", "-n", query, search_path]
        try:
            result = subprocess.run(
                cmd, cwd=repo_dir, capture_output=True, text=True, timeout=15,
            )
            output = result.stdout or "(no matches)"
            if len(output) > _MAX_SEARCH_CHARS:
                output = output[:_MAX_SEARCH_CHARS] + "\n... [truncated]"
            return output
        except subprocess.TimeoutExpired:
            return "Error: search timed out"
        except Exception as e:
            return f"Error searching: {e}"

    elif tool_name == "write_file":
        path = repo_dir / tool_input["path"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tool_input["content"])
            return f"Written: {tool_input['path']}"
        except Exception as e:
            return f"Error writing file: {e}"

    elif tool_name == "run_command":
        try:
            command = guard_command(
                ["/bin/bash", "-lc", tool_input["command"]],
                policy=network_policy,
            )
            result = subprocess.run(
                command,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=180,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return f"exit_code={result.returncode}\n{output[-20_000:]}"
        except subprocess.TimeoutExpired:
            return "Error: command timed out after 180 seconds"

    elif tool_name == "submit_patch":
        return "SUBMIT"

    return f"Error: unknown tool {tool_name}"


def _build_issue_prompt(instance: dict, eval_mode: str = "fix") -> str:
    """Build the initial user message from instance (issue description only)."""
    repo = instance["repo"]
    problem = _problem_text(instance)

    media_ctx = format_issue_media_for_prompt(instance)
    if eval_mode == "coverage_generation":
        issue_context = (
            f"Background issue context:\n<issue>\n{problem}\n</issue>\n\n"
            if problem else ""
        )
        return (
            f"Repository: {repo}\n\n"
            f"{_coverage_generation_instruction(instance)}\n\n"
            f"{media_ctx}{issue_context}"
            f"Explore the repository using the provided tools and call submit_patch() "
            f"when the test patch is complete."
        )
    if eval_mode == "test_generation":
        return (
            f"Repository: {repo}\n\n"
            f"Here is the issue that needs a regression test:\n"
            f"<issue>\n{problem}\n</issue>\n\n"
            f"{media_ctx}"
            f"{_test_generation_instruction()}\n"
            f"Explore the repository using the provided tools and call submit_patch() "
            f"when the test patch is complete."
        )

    return (
        f"Repository: {repo}\n\n"
        f"Here is the issue that needs to be resolved:\n"
        f"<issue>\n{problem}\n</issue>\n\n"
        f"{media_ctx}"
        f"Explore the repository using the provided tools, implement the fix, "
        f"and call submit_patch() when your changes are complete."
    )


def _run_agentic_loop(
    instance: dict,
    anthropic_client,
    model: str,
    repo_dir: Path,
    max_turns: int,
    eval_mode: str = "fix",
    network_policy: str = "unrestricted",
) -> tuple[str, dict]:
    """Run multi-turn tool-use loop. Return the patch and API usage metrics."""
    messages = [{"role": "user", "content": _build_issue_prompt(instance, eval_mode=eval_mode)}]
    if eval_mode == "coverage_generation":
        system_prompt = COVERAGE_GENERATION_SYSTEM_PROMPT
    elif eval_mode == "test_generation":
        system_prompt = TEST_GENERATION_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    metrics = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "turns": 0,
    }
    has_cost_rate = model in MODEL_COST_PER_INPUT or model in MODEL_COST_PER_OUTPUT
    if has_cost_rate:
        metrics["cost_usd"] = 0.0
    for turn in range(max_turns):
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        metrics["input_tokens"] += input_tokens
        metrics["output_tokens"] += output_tokens
        metrics["cache_read_input_tokens"] += int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        )
        metrics["cache_creation_input_tokens"] += int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        if has_cost_rate:
            metrics["cost_usd"] += _calc_cost(model, input_tokens, output_tokens)
        metrics["turns"] = turn + 1

        # Accumulate assistant message content
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check stop reason
        if response.stop_reason == "end_turn":
            logger.info(f"[{instance['instance_id']}] Agent stopped at turn {turn+1} (end_turn)")
            break

        if response.stop_reason != "tool_use":
            logger.info(f"[{instance['instance_id']}] Unexpected stop_reason={response.stop_reason}")
            break

        # Process all tool calls in this response
        tool_results = []
        submitted = False
        for block in assistant_content:
            if block.type != "tool_use":
                continue
            result = _execute_tool(
                block.name,
                block.input,
                repo_dir,
                network_policy=network_policy,
            )
            if result == "SUBMIT":
                submitted = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Patch submitted.",
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": tool_results})

        if submitted:
            logger.info(f"[{instance['instance_id']}] Agent called submit_patch at turn {turn+1}")
            break
    else:
        logger.warning(f"[{instance['instance_id']}] Reached max_turns={max_turns}")

    # Stage all changes (including new files) then diff against HEAD
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    metrics["total_tokens"] = metrics["input_tokens"] + metrics["output_tokens"]
    return diff_result.stdout or "", metrics


def run_agent_inference_for_level(
    instances: list[dict],
    output_file: str,
    model_name: str,
    anthropic_client,
    github_token: Optional[str] = None,
    max_turns: int = 30,
    max_workers: int = 2,
    eval_mode: str = "fix",
    network_policy: str = "unrestricted",
) -> None:
    """Run agentic inference for all instances. Writes same JSONL format as inference.py."""
    validate_network_policy(network_policy)
    # Resume: skip already-done instances
    existing_ids: set[str] = set()
    out_path = Path(output_file)
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if prediction_matches_backend(
                        obj, AGENT_BACKEND, model_name, eval_mode=eval_mode
                    ):
                        existing_ids.add(obj["instance_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    if existing_ids:
        logger.info(f"Resuming: {len(existing_ids)} predictions already written")

    unique_instances = unique_instances_by_id(instances)
    skipped_duplicates = len(instances) - len(unique_instances)
    if skipped_duplicates:
        logger.info(f"Skipping {skipped_duplicates} duplicate instance row(s) before inference")
    todo = [i for i in unique_instances if i["instance_id"] not in existing_ids]
    tmp_root = out_path.parent / "tmp" / AGENT_BACKEND
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_root.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()

    def _process_one(inst: dict) -> None:
        instance_id = inst["instance_id"]
        repo_dir = None
        started = time.perf_counter()
        try:
            repo_dir = _clone_repo_at_commit(inst["repo"], inst["base_commit"], github_token, tmp_root=tmp_root)
            patch, metrics = _run_agentic_loop(
                inst,
                anthropic_client,
                model_name,
                repo_dir,
                max_turns,
                eval_mode=eval_mode,
                network_policy=network_policy,
            )
            patch = _clean_patch(patch)
            patch = _repair_patch(patch)
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "eval_mode": eval_mode,
                "metrics": with_wall_time(metrics, time.perf_counter() - started),
            }
        except Exception as e:
            logger.error(f"Error on {instance_id}: {e}")
            traceback.print_exc()
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "eval_mode": eval_mode,
                "error": str(e),
                "metrics": with_wall_time({}, time.perf_counter() - started),
            }
        finally:
            if repo_dir:
                shutil.rmtree(repo_dir, ignore_errors=True)

        with write_lock:
            with open(out_path, "a") as f:
                print(json.dumps(record), file=f, flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_process_one, inst): inst for inst in todo}
        with tqdm(total=len(todo), desc=f"Agent inference ({model_name})") as pbar:
            for fut in as_completed(futs):
                fut.result()
                pbar.update(1)
