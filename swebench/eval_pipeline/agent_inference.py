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
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from tqdm.auto import tqdm

from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.prediction_utils import prediction_matches_backend, unique_instances_by_id

logger = logging.getLogger(__name__)
AGENT_BACKEND = "builtin"

SYSTEM_PROMPT = (
    "You are an expert software engineer working on a real codebase. "
    "You have been given a GitHub issue to resolve. "
    "Use the provided tools to explore the repository, understand the code, "
    "and implement a fix. When your changes are complete, call submit_patch()."
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
    """Clone repo at base_commit into a temp dir, return the dir path."""
    root = Path(tmp_root or os.environ.get("SWE_AGENT_TMPDIR") or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="sweagent_", dir=str(root)))
    token_prefix = f"{github_token}@" if github_token else ""
    url = f"https://{token_prefix}github.com/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", url, str(tmpdir)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", base_commit],
            cwd=tmpdir, check=True, capture_output=True,
        )
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


def _execute_tool(tool_name: str, tool_input: dict, repo_dir: Path) -> str:
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

    elif tool_name == "submit_patch":
        return "SUBMIT"

    return f"Error: unknown tool {tool_name}"


def _build_issue_prompt(instance: dict) -> str:
    """Build the initial user message from instance (issue description only)."""
    repo = instance["repo"]
    problem = (instance.get("problem_statement") or "").strip()
    if not problem:
        # Fallback: use PR title/body if no issue
        pr_title = (instance.get("pr_title") or "").strip()
        pr_body = (instance.get("pr_body") or "").strip()
        problem = f"{pr_title}\n\n{pr_body}".strip()

    return (
        f"Repository: {repo}\n\n"
        f"Here is the issue that needs to be resolved:\n"
        f"<issue>\n{problem}\n</issue>\n\n"
        f"Explore the repository using the provided tools, implement the fix, "
        f"and call submit_patch() when your changes are complete."
    )


def _run_agentic_loop(
    instance: dict,
    anthropic_client,
    model: str,
    repo_dir: Path,
    max_turns: int,
) -> str:
    """Run multi-turn tool-use loop. Returns unified diff patch string."""
    messages = [{"role": "user", "content": _build_issue_prompt(instance)}]

    for turn in range(max_turns):
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

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
            result = _execute_tool(block.name, block.input, repo_dir)
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
    return diff_result.stdout or ""


def run_agent_inference_for_level(
    instances: list[dict],
    output_file: str,
    model_name: str,
    anthropic_client,
    github_token: Optional[str] = None,
    max_turns: int = 30,
    max_workers: int = 2,
) -> None:
    """Run agentic inference for all instances. Writes same JSONL format as inference.py."""
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
                    if prediction_matches_backend(obj, AGENT_BACKEND, model_name):
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
        try:
            repo_dir = _clone_repo_at_commit(inst["repo"], inst["base_commit"], github_token, tmp_root=tmp_root)
            patch = _run_agentic_loop(inst, anthropic_client, model_name, repo_dir, max_turns)
            patch = _clean_patch(patch)
            patch = _repair_patch(patch)
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
            }
        except Exception as e:
            logger.error(f"Error on {instance_id}: {e}")
            traceback.print_exc()
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "error": str(e),
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
