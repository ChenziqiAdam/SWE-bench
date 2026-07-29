"""Stage 4 (agentic, Codex backend): invoke local Codex CLI per instance."""
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
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json, with_wall_time
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

AGENT_BACKEND = "codex"
_CODEX_TIMEOUT = 900
_CODEX_PROVIDER_ID = "eval_pipeline"
_CODEX_PROVIDER_KEY_ENV = "CODEX_EVAL_PIPELINE_API_KEY"


def _codex_bin() -> str:
    """Return path to Codex CLI."""
    import sys

    found = shutil.which("codex")
    if found:
        return found

    venv_bin = Path(sys.executable).parent / "codex"
    if venv_bin.exists():
        return str(venv_bin)

    repo_root = Path(os.path.abspath(__file__)).parent.parent.parent
    for candidate in [
        repo_root / ".venv" / "bin" / "codex",
        repo_root / "venv" / "bin" / "codex",
    ]:
        if candidate.exists():
            return str(candidate)

    return "codex"


def _codex_problem_text(instance: dict, eval_mode: str = "fix") -> str:
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


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _write_endpoint_config(
    codex_home: Path,
    model_name: str,
    api_base: str,
    has_api_key: bool,
    profile: Optional[str] = None,
) -> Path:
    """Write a temporary Codex config/profile for a custom endpoint."""
    codex_home.mkdir(parents=True, exist_ok=True)
    lines = [
        f"model = {_toml_string(model_name)}",
        f"model_provider = {_toml_string(_CODEX_PROVIDER_ID)}",
        "",
        f"[model_providers.{_CODEX_PROVIDER_ID}]",
        'name = "Eval pipeline provider"',
        f"base_url = {_toml_string(api_base.rstrip('/'))}",
        'wire_api = "responses"',
    ]
    if has_api_key:
        lines.append(f"env_key = {_toml_string(_CODEX_PROVIDER_KEY_ENV)}")
    content = "\n".join(lines) + "\n"
    cfg_path = codex_home / (f"{profile}.config.toml" if profile else "config.toml")
    cfg_path.write_text(content)
    return cfg_path


def run_codex_inference(
    instances: list[dict],
    output_file: str,
    model_name: str,
    github_token: Optional[str] = None,
    max_workers: int = 2,
    timeout: int = _CODEX_TIMEOUT,
    sandbox: str = "workspace-write",
    profile: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    retry_empty_predictions: bool = False,
    eval_mode: str = "fix",
    network_policy: str = "unrestricted",
) -> None:
    """Run Codex inference for all instances. Writes standard prediction JSONL."""
    validate_network_policy(
        network_policy,
        api_base or "https://api.openai.com",
    )
    codex_home = None
    endpoint_config_path = None
    if api_base:
        codex_home = Path(tempfile.mkdtemp(prefix="codex_home_"))
        endpoint_config_path = _write_endpoint_config(
            codex_home,
            model_name=model_name,
            api_base=api_base,
            has_api_key=bool(api_key),
            profile=profile,
        )
        logger.info(
            f"Using temporary Codex provider config for endpoint {api_base} "
            f"({endpoint_config_path})"
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
                logger.info(f"[{obj.get('instance_id')}] retrying prior empty Codex prediction")
        else:
            retained_records.append(obj)

    if existing_ids:
        logger.info(f"Resuming Codex: {len(existing_ids)} predictions already written")

    unique_instances = unique_instances_by_id(instances)
    skipped_duplicates = len(instances) - len(unique_instances)
    if skipped_duplicates:
        logger.info(f"Skipping {skipped_duplicates} duplicate instance row(s) before Codex inference")

    todo = [i for i in unique_instances if i["instance_id"] not in existing_ids]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if retry_empty_predictions and out_path.exists():
        write_prediction_rows(out_path, retained_records)

    logs_dir = out_path.parent / "codex_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = out_path.parent / "tmp" / AGENT_BACKEND
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
            prompt = _codex_problem_text(inst, eval_mode=eval_mode)
            cmd = [
                _codex_bin(),
                "exec",
                "--sandbox",
                sandbox,
                "--cd",
                str(repo_dir),
                "--model",
                model_name,
                "--json",
                "--ephemeral",
            ]
            if profile:
                cmd.extend(["--profile", profile])
            cmd.append(prompt)
            cmd = guard_command(
                cmd,
                policy=network_policy,
                endpoint=api_base or "https://api.openai.com",
            )

            env = dict(os.environ)
            if codex_home:
                env["CODEX_HOME"] = str(codex_home)
            if api_key:
                env[_CODEX_PROVIDER_KEY_ENV] = api_key
            result = subprocess.run(
                cmd,
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
                f"=== exit code: {result.returncode} ===\n"
                "=== STDERR ===\n"
                + (result.stderr or "")
            )
            if result.returncode != 0:
                logger.warning(
                    f"[{instance_id}] codex exited with code {result.returncode}. "
                    f"stderr: {(result.stderr or '')[-500:]}"
                )

            patch = _repair_patch(_clean_patch(_capture_patch(
                repo_dir, inst.get("coverage_language") == "cpp"
            )))
            logger.info(
                f"[{instance_id}] codex exit={result.returncode}, "
                f"patch_len={len(patch)}, log={stderr_path}"
            )
            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "agent_backend": AGENT_BACKEND,
                "eval_mode": eval_mode,
                "metrics": with_wall_time(
                    metrics_from_stream_json(stream_output), time.perf_counter() - started
                ),
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
            logger.error(f"[{instance_id}] codex timed out after {timeout}s")
            record = {
                "instance_id": instance_id,
                "model_patch": "",
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

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_process_one, inst): inst for inst in todo}
            with tqdm(total=len(todo), desc=f"Codex inference ({model_name})") as pbar:
                for fut in as_completed(futs):
                    fut.result()
                    pbar.update(1)
    finally:
        if codex_home:
            shutil.rmtree(codex_home, ignore_errors=True)
