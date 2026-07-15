"""Stage 4 (agentic, Claude Code backend): invoke local Claude CLI per instance."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from tqdm.auto import tqdm

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json, with_wall_time
from swebench.eval_pipeline.media_assets import format_issue_media_for_prompt
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


def _claude_problem_text(instance: dict, eval_mode: str = "fix") -> str:
    problem = _problem_text(instance)

    file_contents = instance.get("file_contents") or {}
    target_files = sorted(file_contents)
    f2p = instance.get("FAIL_TO_PASS") or []

    if eval_mode == "coverage_generation":
        guidance = [
            _coverage_generation_instruction(instance),
            "Inspect the target modules and existing tests, and run tests/coverage while iterating.",
            "When finished, leave the test edits in the working tree; the evaluator captures git diff.",
        ]
    elif eval_mode == "test_generation":
        guidance = [
            "Write a minimal regression test patch for this SWE-bench issue.",
            "Do not fix the bug or modify implementation/source files.",
            "Only add or modify tests and small test data files required by those tests.",
            "Prefer targeted inspection of relevant tests over broad repository scans.",
            "When finished, leave the test edits in the working tree; the evaluator will capture git diff.",
            _test_generation_instruction(),
        ]
    else:
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
    media_ctx = format_issue_media_for_prompt(instance)
    issue_text = ("\n\nIssue:\n" + problem) if problem else ""
    return (
        f"Repository: {repo}\n\n"
        + "\n".join(guidance)
        + "\n\n"
        + media_ctx
        + issue_text
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


def _format_hunk_range(start: int, count: int) -> str:
    return str(start) if count == 1 else f"{start},{count}"


def _capture_structured_patch_from_stream(stdout: str, repo_dir: Path) -> str:
    """Recover Claude Code Edit-tool patches from stream-json output."""
    hunks_by_path: dict[str, list[str]] = {}
    repo_dir = repo_dir.resolve()

    for line in (stdout or "").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        result = obj.get("tool_use_result")
        if not isinstance(result, dict):
            continue
        file_path = result.get("filePath")
        structured = result.get("structuredPatch")
        if not isinstance(file_path, str) or not isinstance(structured, list):
            continue

        try:
            rel_path = Path(file_path).resolve().relative_to(repo_dir).as_posix()
        except (OSError, ValueError):
            continue

        new_hunks = []
        for hunk in structured:
            if not isinstance(hunk, dict):
                continue
            lines = hunk.get("lines")
            if not isinstance(lines, list):
                continue
            old_start = int(hunk.get("oldStart", 0))
            old_lines = int(hunk.get("oldLines", 0))
            new_start = int(hunk.get("newStart", 0))
            new_lines = int(hunk.get("newLines", 0))
            new_hunks.append(
                f"@@ -{_format_hunk_range(old_start, old_lines)} "
                f"+{_format_hunk_range(new_start, new_lines)} @@\n"
            )
            new_hunks.extend(line if line.endswith("\n") else line + "\n" for line in lines)
        if new_hunks:
            hunks_by_path.setdefault(rel_path, []).extend(new_hunks)

    patch_parts = []
    for rel_path, hunks in hunks_by_path.items():
        patch_parts.append(
            f"diff --git a/{rel_path} b/{rel_path}\n"
            f"--- a/{rel_path}\n"
            f"+++ b/{rel_path}\n"
            + "".join(hunks)
        )
    return "\n".join(patch_parts)


def _extract_claude_error(stdout: str, stderr: str) -> str:
    """Return a concise Claude Code failure reason from stream-json output."""
    if stderr.strip():
        return stderr[-500:]

    fallback = stdout[-500:] if stdout else ""
    saw_json = False
    last_event = ""
    for line in reversed((stdout or "").splitlines()):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            text = line.strip()
            if text and not saw_json:
                return text[-500:]
            continue

        saw_json = True
        event_type = obj.get("type")
        event_subtype = obj.get("subtype")
        if not last_event:
            last_event = (
                f"type={event_type or 'unknown'}"
                + (f", subtype={event_subtype}" if event_subtype else "")
            )

        result = obj.get("result")
        if isinstance(result, str) and result.strip():
            return result.strip()[-500:]

        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                texts = [
                    item.get("text", "").strip()
                    for item in content
                    if (
                        isinstance(item, dict)
                        and item.get("type") == "text"
                        and isinstance(item.get("text"), str)
                    )
                ]
                text = "\n".join(t for t in texts if t)
                if text:
                    return text[-500:]

        error = obj.get("error")
        if isinstance(error, str) and error.strip() and error != "unknown":
            return error.strip()[-500:]

    if saw_json:
        suffix = f"; last event: {last_event}" if last_event else ""
        return f"no actionable Claude Code error detail in stream-json output{suffix}"

    return fallback or "no stderr/stdout"


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
    eval_mode: str = "fix",
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
        if prediction_matches_backend(obj, AGENT_BACKEND, model_name, eval_mode=eval_mode):
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

    unique_instances = unique_instances_by_id(instances)
    skipped_duplicates = len(instances) - len(unique_instances)
    if skipped_duplicates:
        logger.info(f"Skipping {skipped_duplicates} duplicate instance row(s) before Claude Code inference")

    todo = [i for i in unique_instances if i["instance_id"] not in existing_ids]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if retry_empty_predictions and out_path.exists():
        write_prediction_rows(out_path, retained_records)

    logs_dir = out_path.parent / "claude_code_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = out_path.parent / "tmp" / AGENT_BACKEND
    tmp_root.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()

    def _process_one(inst: dict) -> None:
        instance_id = inst["instance_id"]
        repo_dir = None
        started = time.perf_counter()
        try:
            repo_dir = _clone_repo_at_commit(inst["repo"], inst["base_commit"], github_token, tmp_root=tmp_root)
            prompt = _claude_problem_text(inst, eval_mode=eval_mode)
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
            ]
            if eval_mode == "coverage_generation":
                # Coverage agents must run setup, tests, and coverage in their
                # disposable clone. In noninteractive print mode acceptEdits
                # alone otherwise denies every Bash invocation.
                cmd += ["--allowedTools", "Bash"]
            cmd.append(prompt)

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
                + "\n=== STDOUT tail ===\n"
                + (result.stdout or "")[-4000:]
            )
            error = ""
            if result.returncode != 0:
                detail = _extract_claude_error(result.stdout or "", result.stderr or "")
                error = f"claude exited with code {result.returncode}: {detail}"
                logger.warning(
                    f"[{instance_id}] claude exited with code {result.returncode}. "
                    f"detail: {detail}"
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
                "eval_mode": eval_mode,
                "metrics": with_wall_time(
                    metrics_from_stream_json(result.stdout or ""),
                    time.perf_counter() - started,
                ),
            }
            if error:
                record["error"] = error
        except subprocess.TimeoutExpired as te:
            stdout = te.stdout if isinstance(te.stdout, str) else (te.stdout or b"").decode(errors="replace")
            stderr = te.stderr if isinstance(te.stderr, str) else (te.stderr or b"").decode(errors="replace")
            patch = ""
            if repo_dir:
                try:
                    patch = _repair_patch(_clean_patch(_capture_patch(repo_dir)))
                    if not patch:
                        patch = _repair_patch(
                            _clean_patch(_capture_structured_patch_from_stream(stdout, repo_dir))
                        )
                        if patch:
                            logger.info(
                                f"[{instance_id}] recovered timeout patch from Claude Code stream-json"
                            )
                except Exception as patch_error:
                    logger.warning(f"[{instance_id}] failed to capture timeout patch: {patch_error}")
            try:
                (logs_dir / f"{instance_id}.jsonl").write_text(stdout or "")
                (logs_dir / f"{instance_id}.log").write_text(
                    f"=== TIMEOUT after {timeout}s ===\n"
                    f"=== recovered patch bytes: {len(patch)} ===\n"
                    "=== STDERR ===\n"
                    + (stderr or "")
                    + "\n=== STDOUT tail ===\n"
                    + (stdout or "")[-4000:]
                )
            except Exception:
                pass
            logger.error(f"[{instance_id}] claude_code timed out after {timeout}s")
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "eval_mode": eval_mode,
                "error": "timeout",
                "metrics": with_wall_time(
                    metrics_from_stream_json(stdout), time.perf_counter() - started
                ),
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
        with tqdm(total=len(todo), desc=f"Claude Code inference ({model_name})") as pbar:
            for fut in as_completed(futs):
                fut.result()
                pbar.update(1)
