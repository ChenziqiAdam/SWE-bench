"""Stage 4 (agentic, Antigravity backend): invoke local Antigravity CLI (`agy`) per instance."""
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

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference import (
    _clean_patch,
    _repair_patch,
    _strip_generated_artifact_diff_blocks,
)
from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json, with_wall_time
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

AGENT_BACKEND = "agy"
_AGY_TIMEOUT = 900
_AGY_PRINT_TIMEOUT = "15m"


def _agy_bin() -> str:
    """Return path to Antigravity CLI."""
    import sys

    found = shutil.which("agy")
    if found:
        return found

    venv_bin = Path(sys.executable).parent / "agy"
    if venv_bin.exists():
        return str(venv_bin)

    repo_root = Path(os.path.abspath(__file__)).parent.parent.parent
    for candidate in [
        repo_root / ".venv" / "bin" / "agy",
        repo_root / "venv" / "bin" / "agy",
    ]:
        if candidate.exists():
            return str(candidate)

    return "agy"


def _agy_problem_text(instance: dict, eval_mode: str = "fix") -> str:
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


def run_agy_inference(
    instances: list[dict],
    output_file: str,
    model_name: str,
    github_token: Optional[str] = None,
    max_workers: int = 2,
    timeout: int = _AGY_TIMEOUT,
    print_timeout: str = _AGY_PRINT_TIMEOUT,
    effort: Optional[str] = None,
    retry_empty_predictions: bool = False,
    eval_mode: str = "fix",
    network_policy: str = "unrestricted",
    hidden_paths: list[str] | None = None,
) -> None:
    """Run Antigravity CLI inference for all instances. Writes standard prediction JSONL."""
    validate_network_policy(network_policy)

    out_path = Path(output_file)
    unique_instances = unique_instances_by_id(instances)
    input_hashes = {
        inst["instance_id"]: inference_input_hash(inst) for inst in unique_instances
    }
    existing_ids: set[str] = set()
    retained_records: list[dict] = []
    for obj in read_prediction_rows(out_path):
        if prediction_matches_backend(
            obj, AGENT_BACKEND, model_name, eval_mode=eval_mode,
            input_hash=input_hashes.get(obj.get("instance_id")),
        ):
            has_patch = bool((obj.get("model_patch") or "").strip())
            if has_patch or not retry_empty_predictions:
                existing_ids.add(obj["instance_id"])
                retained_records.append(obj)
            else:
                logger.info(f"[{obj.get('instance_id')}] retrying prior empty Antigravity prediction")
        else:
            retained_records.append(obj)

    if existing_ids:
        logger.info(f"Resuming Antigravity: {len(existing_ids)} predictions already written")

    skipped_duplicates = len(instances) - len(unique_instances)
    if skipped_duplicates:
        logger.info(f"Skipping {skipped_duplicates} duplicate instance row(s) before Antigravity inference")

    todo = [i for i in unique_instances if i["instance_id"] not in existing_ids]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if retry_empty_predictions and out_path.exists():
        write_prediction_rows(out_path, retained_records)

    logs_dir = out_path.parent / "agy_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = inference_worktree_root(AGENT_BACKEND)
    effective_hidden_paths = guarded_hidden_paths(
        network_policy, out_path, hidden_paths or []
    )
    tmp_root.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()

    def _process_one(inst: dict) -> None:
        instance_id = inst["instance_id"]
        repo_dir = None
        started = time.perf_counter()
        stream_output = ""
        try:
            repo_dir = _clone_repo_at_commit(inst["repo"], inst["base_commit"], github_token, tmp_root=tmp_root)
            if eval_mode == "coverage_generation":
                from swebench.eval_pipeline.coverage_adapters import install_coverage_runner
                install_coverage_runner(repo_dir, inst)
            prompt = _agy_problem_text(inst, eval_mode=eval_mode)
            cmd = [
                _agy_bin(),
                "-p",
                "--output-format",
                "stream-json",
                "--model",
                model_name,
                "--print-timeout",
                print_timeout,
            ]
            if effort:
                cmd += ["--effort", effort]
            if eval_mode == "coverage_generation":
                # Coverage agents must run setup, tests, and coverage commands in
                # their disposable clone. accept-edits alone only auto-approves
                # file edits, not shell commands, so those need explicit consent.
                cmd.append("--dangerously-skip-permissions")
            else:
                cmd.append("--mode=accept-edits")
            cmd.append(prompt)
            cmd = guard_command(
                cmd,
                policy=network_policy,
                hidden_paths=effective_hidden_paths,
            )

            env = dict(os.environ)

            result = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            stream_output = result.stdout or ""

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
                    f"[{instance_id}] agy exited with code {result.returncode}. "
                    f"stderr: {(result.stderr or '')[-500:]}"
                )

            patch = _repair_patch(_clean_patch(_strip_generated_artifact_diff_blocks(
                _capture_patch(repo_dir, inst.get("coverage_language") == "cpp")
            )))
            logger.info(
                f"[{instance_id}] agy exit={result.returncode}, "
                f"patch_len={len(patch)}, log={stderr_path}"
            )
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "eval_mode": eval_mode,
                "inference_input_hash": input_hashes[instance_id],
                "metrics": with_wall_time(
                    metrics_from_stream_json(stream_output), time.perf_counter() - started
                ),
            }
            if result.returncode != 0:
                record["error"] = f"agy exited with code {result.returncode}"
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
            logger.error(f"[{instance_id}] agy timed out after {timeout}s")
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "eval_mode": eval_mode,
                "inference_input_hash": input_hashes[instance_id],
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
                "inference_input_hash": input_hashes[instance_id],
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
        with tqdm(total=len(todo), desc=f"Antigravity inference ({model_name})") as pbar:
            for fut in as_completed(futs):
                fut.result()
                pbar.update(1)
