"""Stage 4 (agentic, Claude Code backend): invoke local Claude CLI per instance."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from tqdm.auto import tqdm

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.prediction_utils import (
    prediction_matches_backend,
    read_prediction_rows,
    write_prediction_rows,
)

logger = logging.getLogger(__name__)

AGENT_BACKEND = "claude_code"
_CLAUDE_CODE_TIMEOUT = 900


def _claude_bin() -> str:
    """Return path to Claude Code CLI."""
    import sys

    found = shutil.which("claude")
    if found:
        return found

    venv_bin = Path(sys.executable).parent / "claude"
    if venv_bin.exists():
        return str(venv_bin)

    repo_root = Path(os.path.abspath(__file__)).parent.parent.parent
    for candidate in [
        repo_root / ".venv" / "bin" / "claude",
        repo_root / "venv" / "bin" / "claude",
    ]:
        if candidate.exists():
            return str(candidate)

    return "claude"


def _claude_problem_text(instance: dict) -> str:
    problem = (instance.get("problem_statement") or "").strip()
    if not problem:
        pr_title = (instance.get("pr_title") or "").strip()
        pr_body = (instance.get("pr_body") or "").strip()
        problem = f"{pr_title}\n\n{pr_body}".strip()

    file_contents = instance.get("file_contents") or {}
    target_files = sorted(file_contents)
    f2p = instance.get("FAIL_TO_PASS") or []

    guidance = [
        "Resolve this SWE-bench scientific software issue in the local repository.",
        "Make the smallest source change needed to address the issue.",
        "Do not refactor unrelated code or rewrite generated files.",
        "Prefer targeted inspection of relevant files over broad repository scans.",
        "When finished, leave the edits in the working tree; the evaluator will capture git diff.",
    ]
    if target_files:
        guidance.append("Relevant base-commit files from instance construction:")
        guidance.extend(f"- {path}" for path in target_files[:12])
    if f2p:
        guidance.append("Mined FAIL_TO_PASS tests used for scoring:")
        guidance.extend(f"- {test}" for test in f2p[:12])

    repo = instance["repo"]
    return (
        f"Repository: {repo}\n\n"
        + "\n".join(guidance)
        + "\n\nIssue:\n"
        + problem
    )


def _capture_patch(repo_dir: Path) -> str:
    subprocess.run(["git", "add", "-N", "."], cwd=repo_dir, capture_output=True)
    result = subprocess.run(
        ["git", "-c", "core.fileMode=false", "diff", "--binary", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return result.stdout or ""


def run_claude_code_inference(
    instances: list[dict],
    output_file: str,
    model_name: str,
    github_token: Optional[str] = None,
    max_workers: int = 2,
    timeout: int = _CLAUDE_CODE_TIMEOUT,
    permission_mode: str = "acceptEdits",
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    retry_empty_predictions: bool = False,
    max_turns: Optional[int] = None,
) -> None:
    """Run Claude Code inference for all instances. Writes standard prediction JSONL."""
    if api_base:
        logger.info(
            "Using ANTHROPIC_BASE_URL for Claude Code endpoint %s. "
            "Endpoint must be Anthropic-compatible.",
            api_base,
        )

    out_path = Path(output_file)
    existing_ids: set[str] = set()
    retained_records: list[dict] = []
    for obj in read_prediction_rows(out_path):
        if prediction_matches_backend(obj, AGENT_BACKEND, model_name):
            has_patch = bool((obj.get("model_patch") or "").strip())
            if has_patch or not retry_empty_predictions:
                existing_ids.add(obj["instance_id"])
                retained_records.append(obj)
            else:
                logger.info(f"[{obj.get('instance_id')}] retrying prior empty Claude Code prediction")
        else:
            retained_records.append(obj)

    if existing_ids:
        logger.info(f"Resuming Claude Code: {len(existing_ids)} predictions already written")

    todo = [i for i in instances if i["instance_id"] not in existing_ids]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if retry_empty_predictions and out_path.exists():
        write_prediction_rows(out_path, retained_records)

    logs_dir = out_path.parent / "claude_code_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()

    def _process_one(inst: dict) -> None:
        instance_id = inst["instance_id"]
        repo_dir = None
        try:
            repo_dir = _clone_repo_at_commit(inst["repo"], inst["base_commit"], github_token)
            prompt = _claude_problem_text(inst)
            cmd = [
                _claude_bin(),
                "-p",
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                permission_mode,
                "--model",
                model_name,
                prompt,
            ]

            env = dict(os.environ)
            if api_base:
                env["ANTHROPIC_BASE_URL"] = api_base.rstrip("/")
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            if max_turns is not None:
                env["CLAUDE_CODE_MAX_TURNS"] = str(max_turns)

            result = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                env=env,
            )

            stdout_path = logs_dir / f"{instance_id}.jsonl"
            stderr_path = logs_dir / f"{instance_id}.log"
            stdout_path.write_text(result.stdout or "")
            stderr_path.write_text(
                f"=== command ===\n{json.dumps(cmd[:-1] + ['<prompt>'])}\n"
                f"=== cwd ===\n{repo_dir}\n"
                f"=== exit code: {result.returncode} ===\n"
                "=== STDERR ===\n"
                + (result.stderr or "")
            )
            if result.returncode != 0:
                logger.warning(
                    f"[{instance_id}] claude exited with code {result.returncode}. "
                    f"stderr: {(result.stderr or '')[-500:]}"
                )

            patch = _repair_patch(_clean_patch(_capture_patch(repo_dir)))
            logger.info(
                f"[{instance_id}] claude_code exit={result.returncode}, "
                f"patch_len={len(patch)}, log={stderr_path}"
            )
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
            }
        except subprocess.TimeoutExpired as te:
            stdout = te.stdout if isinstance(te.stdout, str) else (te.stdout or b"").decode(errors="replace")
            stderr = te.stderr if isinstance(te.stderr, str) else (te.stderr or b"").decode(errors="replace")
            try:
                (logs_dir / f"{instance_id}.jsonl").write_text(stdout or "")
                (logs_dir / f"{instance_id}.log").write_text(
                    f"=== TIMEOUT after {timeout}s ===\n"
                    "=== STDERR ===\n"
                    + (stderr or "")
                )
            except Exception:
                pass
            logger.error(f"[{instance_id}] claude_code timed out after {timeout}s")
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "error": "timeout",
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
        with tqdm(total=len(todo), desc=f"Claude Code inference ({model_name})") as pbar:
            for fut in as_completed(futs):
                fut.result()
                pbar.update(1)
