#!/usr/bin/env python3
"""End-to-end formal evaluation pipeline for v4 paper-replication tasks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .evaluation.framework import EvaluationInputError, read_json
    from .task_registry import select_validated
except ImportError:  # Direct script execution.
    from evaluation.framework import EvaluationInputError, read_json  # type: ignore
    from task_registry import select_validated  # type: ignore

from swebench.eval_pipeline.claude_code_inference import _extract_claude_error
from swebench.eval_pipeline.inference_metrics import (
    metrics_from_stream_json,
    with_wall_time,
)
try:
    from .container_runtime import (
        ContainerRuntimeError,
        local_image_identity,
        podman_client,
        run_podman_container,
    )
except ImportError:  # Direct script execution.
    from container_runtime import (  # type: ignore
        ContainerRuntimeError,
        local_image_identity,
        podman_client,
        run_podman_container,
    )


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parent
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "paper_replication"
_PROGRESS_LOCK = threading.Lock()
PROMPT = """\
You are reproducing one scientific paper task in a clean-room, offline workspace.
Only the files in this workspace are public benchmark inputs. Do not seek or use
the original paper repository, hidden reference values, evaluator code, or any
files outside this workspace.

Read task.md, paper.pdf, and interface.schema.json. Look at every
cases/case_NN/input.json and cases/case_NN/output.json pair for concrete worked
examples of the exact input/output contract. Implement the complete requested
method from scratch, offline, using only locally installed dependencies. Your
solution must be deterministic and rerunnable offline.

Before finishing, run your implementation against every public case and confirm
your output.json matches. Leave all source code in this workspace and write
submission.json at the workspace root:

  {"schema_version": 4, "task_id": "<task_id>", "entrypoint": ["python", "solution.py"]}

The entrypoint must be a direct executable command (no shell) that a trusted
runner invokes once per case as:

  <entrypoint> --input <input.json> --output <output_directory>

Each invocation must create <output_directory>/output.json from a clean copy of
this workspace, without relying on files written by a previous invocation.
"""


def progress(task_id: str | None, message: str) -> None:
    """Write one atomic, immediately flushed human-readable progress line."""
    scope = task_id or "pipeline"
    with _PROGRESS_LOCK:
        print(f"[{utc_timestamp()}] [{scope}] {message}", flush=True)


def compact_value(value: Any, limit: int = 180) -> str:
    rendered = json.dumps(json_safe(value), separators=(",", ":"), sort_keys=True)
    return rendered if len(rendered) <= limit else rendered[: limit - 3] + "..."


def failed_check_summary(check: dict[str, Any]) -> str:
    diagnostics = check.get("diagnostics") or {}
    parts = [f"check={check.get('id')}", f"split={check.get('split')}"]
    for key in ("max_abs", "rmse", "structural_errors", "error"):
        if key in diagnostics:
            parts.append(f"{key}={compact_value(diagnostics[key])}")
    return " ".join(parts)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def redact(value: Any, secrets: list[str]) -> Any:
    """Recursively redact credentials before persistence."""
    active = [secret for secret in secrets if secret]
    if isinstance(value, str):
        for secret in active:
            value = value.replace(secret, "<redacted>")
        return value
    if isinstance(value, dict):
        return {str(key): redact(item, active) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, active) for item in value]
    return value


def redact_tree_credentials(root: Path, secrets: list[str]) -> None:
    """Remove literal credentials from persisted submission files."""
    replacements = [
        (secret.encode(), b"<redacted>")
        for secret in secrets
        if secret
    ]
    if not replacements:
        return
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        cleaned = data
        for secret, replacement in replacements:
            cleaned = cleaned.replace(secret, replacement)
        if cleaned != data:
            path.write_bytes(cleaned)


def json_safe(value: Any) -> Any:
    """Represent non-finite and non-scalar diagnostics in valid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def public_bundle_manifest(public_dir: Path) -> dict[str, str]:
    """Return a stable manifest while rejecting links and non-regular inputs."""
    if not public_dir.is_dir():
        raise ValueError(f"public bundle is missing: {public_dir}")
    manifest: dict[str, str] = {}
    for path in sorted(public_dir.rglob("*")):
        relative = path.relative_to(public_dir).as_posix()
        if path.is_symlink():
            raise ValueError(f"public bundle contains a symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"public bundle contains a special file: {relative}")
        manifest[relative] = hash_file(path)
    if not manifest:
        raise ValueError(f"public bundle is empty: {public_dir}")
    return manifest


def public_bundle_fingerprint(manifest: dict[str, str]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def create_agent_workspace(public_dir: Path, destination: Path) -> None:
    """Copy exactly the public bundle into a fresh workspace."""
    manifest = public_bundle_manifest(public_dir)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for relative in manifest:
        source = public_dir / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def validate_loopback_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("--endpoint must be a credential-free HTTP(S) URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(
            parsed.hostname, port, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise ValueError(f"cannot resolve endpoint host {parsed.hostname!r}") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses or not all(ipaddress.ip_address(item).is_loopback for item in addresses):
        raise ValueError("--endpoint must resolve only to loopback addresses")
    return endpoint.rstrip("/")


def _command_for_backend(model: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Bash,Edit,Write,Read",
        "--model",
        model,
        PROMPT,
    ]


def run_agent(
    *,
    model: str,
    endpoint: str,
    api_key: str | None,
    claude_oauth_token: str | None,
    workspace: Path,
    task_dir: Path,
    timeout: float,
    retries: int,
    container_image: str,
    container_python: str,
    container_memory: str | None,
    container_cpus: float | None,
    container_pids: int,
    container_tmpfs_size: str,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    aggregate: dict[str, float] = {}
    runtime_dir = task_dir / "agent" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "container_proxy.py", runtime_dir / "container_proxy.py")
    runtime_home = task_dir / "agent" / "container_home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": "/agent-home",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "ANTHROPIC_BASE_URL": endpoint,
    }
    secrets = [api_key or "", claude_oauth_token or ""]
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
    if claude_oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = claude_oauth_token

    final_exit: int | None = None
    error: str | None = None
    timed_out = False
    client = podman_client()
    image_identity = local_image_identity(client, container_image)
    try:
        for index in range(retries + 1):
            command = _command_for_backend(model)
            started = time.perf_counter()
            stdout = ""
            stderr = ""
            try:
                result = run_podman_container(
                    client=client,
                    image=container_image,
                    command=command,
                    workspace=workspace,
                    runtime_dir=runtime_dir,
                    runtime_home=runtime_home,
                    environment=env,
                    timeout=timeout,
                    container_python=container_python,
                    gateway_endpoint=endpoint,
                    memory=container_memory,
                    cpus=container_cpus,
                    pids_limit=container_pids,
                    tmpfs_size=container_tmpfs_size,
                )
                stdout, stderr = result["stdout"], result["stderr"]
                final_exit = result["exit_code"]
                timed_out = result["timed_out"]
                if final_exit == 0:
                    error = None
                else:
                    error = (
                        f"agent exited with code {final_exit}: "
                        f"{_extract_claude_error(stdout, stderr)}"
                    )
            except ContainerRuntimeError as exc:
                final_exit = None
                timed_out = False
                error = str(exc)
                stderr = str(exc)
            elapsed = time.perf_counter() - started
            metrics = with_wall_time(metrics_from_stream_json(stdout), elapsed)
            for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"):
                value = metrics.get(key)
                if isinstance(value, (int, float)):
                    aggregate[key] = aggregate.get(key, 0) + value
            attempts.append(
                {
                    "attempt": index + 1,
                    "command": redact(command[:-1] + ["<prompt>"], secrets),
                    "exit_code": final_exit,
                    "timed_out": timed_out,
                    "metrics": metrics,
                }
            )
            log_dir = task_dir / "agent"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"attempt-{index + 1}.jsonl").write_text(
                redact(stdout, secrets), encoding="utf-8"
            )
            (log_dir / f"attempt-{index + 1}.stderr.log").write_text(
                redact(stderr, secrets), encoding="utf-8"
            )
            if final_exit == 0 or final_exit is None:
                break
    finally:
        client.close()
    redact_tree_credentials(runtime_home, secrets)

    aggregate["wall_time_seconds"] = sum(
        float(row["metrics"].get("wall_time_seconds", 0)) for row in attempts
    )
    aggregate["turns"] = sum(
        int(row["metrics"].get("turns", 0)) for row in attempts
    )
    return {
        "backend": "claude_code",
        "model": model,
        "exit_code": final_exit,
        "timed_out": timed_out,
        "error": redact(error, secrets),
        "container_image": image_identity,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "usage": aggregate,
    }


def run_trusted_execution(
    *,
    task_id: str,
    submission_dir: Path,
    manifest_path: Path,
    timeout: float,
    container_image: str,
    container_python: str,
    container_memory: str | None,
    container_cpus: float | None,
    container_pids: int,
    container_tmpfs_size: str,
) -> dict[str, Any]:
    runtime_dir = manifest_path.parent / "trusted_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "run_submission.py", runtime_dir / "run_submission.py")
    shutil.copytree(ROOT / task_id, runtime_dir / task_id)
    manifest_path.unlink(missing_ok=True)
    runtime_home = manifest_path.parent / "trusted_output"
    runtime_home.mkdir(parents=True, exist_ok=True)
    container_report = runtime_home / "execution_report.json"
    container_report.unlink(missing_ok=True)
    command = [
        container_python,
        "/runner/run_submission.py",
        "--submission-dir",
        "/workspace",
        "--task-dir",
        f"/runner/{task_id}",
        "--output",
        "/agent-home/execution_report.json",
        "--timeout-seconds",
        str(timeout),
    ]
    client = podman_client()
    try:
        container_result = run_podman_container(
            client=client,
            image=container_image,
            command=command,
            workspace=submission_dir,
            runtime_dir=runtime_dir,
            runtime_home=runtime_home,
            environment={"HOME": "/tmp"},
            timeout=timeout + min(30.0, max(5.0, timeout * 0.1)),
            container_python=container_python,
            gateway_endpoint=None,
            memory=container_memory,
            cpus=container_cpus,
            pids_limit=container_pids,
            tmpfs_size=container_tmpfs_size,
            workspace_mode="ro,Z",
        )
        result = {
            "runner_exit_code": container_result["exit_code"],
            "stderr": container_result["stderr"],
            "timed_out": container_result["timed_out"],
            "container_id": container_result["container_id"],
        }
    finally:
        client.close()
    if container_report.is_file():
        shutil.copy2(container_report, manifest_path)
        result["report"] = read_json(manifest_path)
        container_case_outputs = runtime_home / "execution_report_case_outputs"
        host_case_outputs = manifest_path.parent / "execution_report_case_outputs"
        if host_case_outputs.exists():
            shutil.rmtree(host_case_outputs)
        if container_case_outputs.is_dir():
            shutil.copytree(container_case_outputs, host_case_outputs)
    return result


def run_evaluator(
    task_id: str,
    manifest_path: Path,
    output_path: Path,
    timeout: float,
    *,
    container_image: str,
    container_python: str,
    container_memory: str | None,
    container_cpus: float | None,
    container_pids: int,
    container_tmpfs_size: str,
) -> dict[str, Any]:
    output_path.unlink(missing_ok=True)
    runtime_dir = output_path.parent / "evaluator_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True)
    shutil.copytree(ROOT / "evaluation", runtime_dir / "evaluation")
    shutil.copytree(ROOT / task_id, runtime_dir / task_id)
    shutil.copy2(ROOT / "manifest.json", runtime_dir / "manifest.json")
    shutil.copy2(manifest_path, runtime_dir / "execution_report.json")
    case_outputs = manifest_path.parent / f"{manifest_path.stem}_case_outputs"
    if case_outputs.is_dir():
        shutil.copytree(case_outputs, runtime_dir / f"{manifest_path.stem}_case_outputs")
    runtime_home = output_path.parent / "evaluator_output"
    runtime_home.mkdir(parents=True, exist_ok=True)
    container_output = runtime_home / "evaluation.json"
    container_output.unlink(missing_ok=True)
    command = [
        container_python,
        "-m",
        "evaluation.cli",
        "--task-dir",
        f"/runner/{task_id}",
        "--execution-report",
        "/runner/execution_report.json",
        "--output",
        "/agent-home/evaluation.json",
    ]
    client = podman_client()
    try:
        container_result = run_podman_container(
            client=client,
            image=container_image,
            command=command,
            workspace=runtime_dir,
            runtime_dir=runtime_dir,
            runtime_home=runtime_home,
            environment={"HOME": "/tmp", "PYTHONPATH": "/runner"},
            timeout=timeout,
            container_python=container_python,
            gateway_endpoint=None,
            memory=container_memory,
            cpus=container_cpus,
            pids_limit=container_pids,
            tmpfs_size=container_tmpfs_size,
            workspace_mode="ro,Z",
        )
        result = {
            "exit_code": container_result["exit_code"],
            "stderr": container_result["stderr"],
            "timed_out": container_result["timed_out"],
            "container_id": container_result["container_id"],
        }
    finally:
        client.close()
    if container_output.is_file():
        shutil.copy2(container_output, output_path)
        result["report"] = read_json(output_path)
    return result


def fingerprint_record(
    task_id: str,
    model: str,
    public_fingerprint: str,
    container_image_digest: str,
) -> dict[str, str]:
    return {
        "task_id": task_id,
        "backend": "claude_code",
        "model": model,
        "public_bundle_fingerprint": public_fingerprint,
        "container_image_digest": container_image_digest,
    }


def resume_matches(record: dict[str, Any], expected: dict[str, str]) -> bool:
    return all(record.get(key) == value for key, value in expected.items())


def _base_record(
    task_id: str,
    model: str,
    fingerprint: str,
    container_image_digest: str,
) -> dict[str, Any]:
    return {
        **fingerprint_record(task_id, model, fingerprint, container_image_digest),
        "schema_version": 1,
        "started_at": utc_timestamp(),
        "status": "infrastructure_failure",
        "failure_type": None,
    }


def process_task(args: argparse.Namespace, run_dir: Path, task_id: str) -> dict[str, Any]:
    task_dir = run_dir / "tasks" / task_id
    record_path = task_dir / "record.json"
    public_dir = ROOT / task_id / "public"
    public_manifest = public_bundle_manifest(public_dir)
    bundle_hash = public_bundle_fingerprint(public_manifest)
    expected = fingerprint_record(
        task_id, args.model, bundle_hash, args.container_image_identity["digest"]
    )
    prior: dict[str, Any] | None = None
    if record_path.is_file():
        try:
            prior = read_json(record_path)
        except EvaluationInputError:
            prior = None
    if (
        args.resume
        and prior
        and resume_matches(prior, expected)
        and not args.force_inference
        and not args.force_evaluation
        and prior.get("stage") == "evaluated"
    ):
        progress(
            task_id,
            f"resume: reusing completed result score={prior.get('score')} "
            f"full_success={prior.get('full_success')}",
        )
        prior_checks = ((prior.get("evaluator") or {}).get("report") or {}).get("checks") or []
        for check in prior_checks:
            if not check.get("passed"):
                progress(task_id, f"resume: FAIL {failed_check_summary(check)}")
        return prior

    task_dir.mkdir(parents=True, exist_ok=True)
    submission_dir = task_dir / "raw_submission"
    record = _base_record(task_id, args.model, bundle_hash, args.container_image_identity["digest"])
    record["public_bundle"] = public_manifest
    record["agent"] = prior.get("agent") if prior else None
    secrets = [args.api_key or "", args.claude_oauth_token or ""]

    reuse_inference = (
        args.resume
        and prior is not None
        and resume_matches(prior, expected)
        and submission_dir.is_dir()
        and not args.force_inference
    )
    try:
        progress(
            task_id,
            f"start model={args.model} bundle={bundle_hash[:12]} "
            f"image={expected['container_image_digest']}",
        )
        if not reuse_inference:
            progress(
                task_id,
                f"inference: starting timeout={args.agent_timeout:g}s "
                f"retries={args.agent_retries}",
            )
            with tempfile.TemporaryDirectory(
                prefix=f"{task_id}-", dir=args.workspace_root
            ) as temporary:
                workspace = Path(temporary) / "workspace"
                create_agent_workspace(public_dir, workspace)
                record["agent"] = run_agent(
                    model=args.model,
                    endpoint=args.endpoint,
                    api_key=args.api_key,
                    claude_oauth_token=args.claude_oauth_token,
                    workspace=workspace,
                    task_dir=task_dir,
                    timeout=args.agent_timeout,
                    retries=args.agent_retries,
                    container_image=args.container_image,
                    container_python=args.container_python,
                    container_memory=args.container_memory,
                    container_cpus=args.container_cpus,
                    container_pids=args.container_pids,
                    container_tmpfs_size=args.container_tmpfs_size,
                )
                usage = record["agent"].get("usage") or {}
                progress(
                    task_id,
                    "inference: finished "
                    f"exit={record['agent'].get('exit_code')} "
                    f"attempts={record['agent'].get('attempt_count')} "
                    f"wall={usage.get('wall_time_seconds', 0):.3f}s "
                    f"tokens={usage.get('total_tokens', 0)} "
                    f"cost_usd={usage.get('cost_usd', 0):.6f}",
                )
                redact_tree_credentials(workspace, secrets)
                if submission_dir.exists():
                    shutil.rmtree(submission_dir)
                shutil.copytree(workspace, submission_dir, symlinks=True)
            record["stage"] = "inference"
            write_json(record_path, redact(record, secrets))
        else:
            progress(task_id, "inference: reusing matching raw submission")

        if not submission_dir.is_dir():
            raise EvaluationInputError("agent did not produce a submission workspace")
        if (
            (record.get("agent") or {}).get("exit_code") != 0
            and not (submission_dir / "submission.json").is_file()
        ):
            record["failure_type"] = "inference"
            record["error"] = (record.get("agent") or {}).get("error")
            raise RuntimeError("agent inference failed")

        manifest_path = task_dir / "execution_report.json"
        progress(
            task_id,
            f"execution: starting per-case trusted rerun timeout={args.execution_timeout:g}s",
        )
        execution = run_trusted_execution(
            task_id=task_id,
            submission_dir=submission_dir,
            manifest_path=manifest_path,
            timeout=args.execution_timeout,
            container_image=args.container_image,
            container_python=args.container_python,
            container_memory=args.container_memory,
            container_cpus=args.container_cpus,
            container_pids=args.container_pids,
            container_tmpfs_size=args.container_tmpfs_size,
        )
        record["execution"] = execution
        record["stage"] = "execution"
        progress(
            task_id,
            "execution: finished "
            f"runner_exit={execution.get('runner_exit_code')} "
            f"timed_out={execution.get('timed_out')}",
        )
        if execution.get("runner_exit_code") != 0 or not manifest_path.is_file():
            record["failure_type"] = "execution"
            record["error"] = execution.get("stderr") or "trusted runner failed"
            raise RuntimeError("trusted execution failed")

        evaluation_path = task_dir / "evaluation.json"
        progress(
            task_id,
            f"evaluation: starting hidden evaluator timeout={args.evaluator_timeout:g}s",
        )
        evaluation = run_evaluator(
            task_id,
            manifest_path,
            evaluation_path,
            args.evaluator_timeout,
            container_image=args.container_image,
            container_python=args.container_python,
            container_memory=args.container_memory,
            container_cpus=args.container_cpus,
            container_pids=args.container_pids,
            container_tmpfs_size=args.container_tmpfs_size,
        )
        record["evaluator"] = evaluation
        if evaluation.get("exit_code") != 0 or "report" not in evaluation:
            record["failure_type"] = "format" if evaluation.get("exit_code") == 2 else "evaluator"
            record["error"] = evaluation.get("stderr") or "evaluator failed"
            progress(
                task_id,
                "evaluation: failed "
                f"exit={evaluation.get('exit_code')} "
                f"error={compact_value(record['error'])}",
            )
        else:
            report = evaluation["report"]
            record["score"] = report.get("score")
            record["full_success"] = report.get("full_success")
            record["valid_execution"] = report.get("valid_execution")
            checks = report.get("checks") or []
            failed = [check for check in checks if not check.get("passed")]
            progress(
                task_id,
                "evaluation: finished "
                f"score={record['score']} full_success={record['full_success']} "
                f"valid_execution={record['valid_execution']} "
                f"checks_passed={len(checks) - len(failed)}/{len(checks)}",
            )
            for check in failed:
                progress(task_id, f"evaluation: FAIL {failed_check_summary(check)}")
            if report.get("valid_execution") is True:
                record["status"] = "completed"
                record["failure_type"] = None
            else:
                record["failure_type"] = "execution"
                record["error"] = "trusted execution did not produce a valid fresh submission"
        record["stage"] = "evaluated"
    except EvaluationInputError as exc:
        record["failure_type"] = "format"
        record["error"] = str(exc)
        record["stage"] = record.get("stage", "inference")
        progress(task_id, f"format failure: {exc}")
    except (ContainerRuntimeError, OSError, subprocess.SubprocessError) as exc:
        record["failure_type"] = record.get("failure_type") or "infrastructure"
        record["error"] = str(exc)
        progress(task_id, f"infrastructure failure: {exc}")
    except Exception as exc:
        record["failure_type"] = record.get("failure_type") or "infrastructure"
        record["error"] = record.get("error") or f"{type(exc).__name__}: {exc}"
        progress(
            task_id,
            f"{record['failure_type']} failure: {compact_value(record['error'])}",
        )
    record["ended_at"] = utc_timestamp()
    clean = redact(record, secrets)
    write_json(record_path, clean)
    progress(
        task_id,
        f"done status={clean.get('status')} failure_type={clean.get('failure_type')} "
        f"score={clean.get('score')} full_success={clean.get('full_success')}",
    )
    return clean


def _diagnostic_value(diagnostics: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in diagnostics:
            return diagnostics[name]
    return None


def write_reports(run_dir: Path, records: list[dict[str, Any]]) -> None:
    ordered = sorted(records, key=lambda row: row["task_id"])
    with (run_dir / "task_results.jsonl").open("w", encoding="utf-8") as handle:
        for record in ordered:
            handle.write(json.dumps(json_safe(record), sort_keys=True, allow_nan=False) + "\n")

    result_fields = [
        "task_id", "model", "status", "failure_type", "score",
        "full_success", "valid_execution", "public_score", "hidden_score",
        "input_tokens", "output_tokens", "total_tokens", "cost_usd",
        "agent_wall_seconds",
    ]
    with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=result_fields)
        writer.writeheader()
        for record in ordered:
            usage = (record.get("agent") or {}).get("usage") or {}
            report = ((record.get("evaluator") or {}).get("report") or {})
            writer.writerow({
                "task_id": record["task_id"],
                "model": record["model"],
                "status": record.get("status"),
                "failure_type": record.get("failure_type"),
                "score": record.get("score"),
                "full_success": record.get("full_success"),
                "valid_execution": record.get("valid_execution"),
                "public_score": report.get("public_score"),
                "hidden_score": report.get("hidden_score"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_usd": usage.get("cost_usd"),
                "agent_wall_seconds": usage.get("wall_time_seconds"),
            })

    difference_fields = [
        "task_id", "check_id", "split", "passed", "critical",
        "max_abs", "rmse", "structural_errors", "error",
    ]
    with (run_dir / "difference_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=difference_fields)
        writer.writeheader()
        for record in ordered:
            checks = ((record.get("evaluator") or {}).get("report") or {}).get("checks") or []
            for check in checks:
                diagnostics = json_safe(check.get("diagnostics") or {})
                writer.writerow({
                    "task_id": record["task_id"],
                    "check_id": check.get("id"),
                    "split": check.get("split"),
                    "passed": check.get("passed"),
                    "critical": check.get("critical"),
                    "max_abs": _diagnostic_value(diagnostics, "max_abs"),
                    "rmse": _diagnostic_value(diagnostics, "rmse"),
                    "structural_errors": json.dumps(
                        _diagnostic_value(diagnostics, "structural_errors") or []
                    ),
                    "error": _diagnostic_value(diagnostics, "error"),
                })

    completed = [row for row in ordered if row.get("status") == "completed"]
    scores = [float(row["score"]) for row in completed if isinstance(row.get("score"), (int, float))]
    failure_counts: dict[str, int] = {}
    for row in ordered:
        failure = row.get("failure_type")
        if failure:
            failure_counts[str(failure)] = failure_counts.get(str(failure), 0) + 1
    total_usage: dict[str, float] = {}
    for row in ordered:
        usage = (row.get("agent") or {}).get("usage") or {}
        for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "wall_time_seconds"):
            if isinstance(usage.get(key), (int, float)):
                total_usage[key] = total_usage.get(key, 0) + usage[key]
    write_json(run_dir / "summary.json", {
        "schema_version": 1,
        "task_count": len(ordered),
        "completed_count": len(completed),
        "mean_score": sum(scores) / len(scores) if scores else None,
        "full_success_rate": (
            sum(bool(row.get("full_success")) for row in completed) / len(completed)
            if completed else None
        ),
        "failure_counts": failure_counts,
        "total_agent_usage": total_usage,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("claude_code",), default="claude_code")
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key")
    parser.add_argument(
        "--claude-oauth-token",
        help="Claude Code OAuth token; preferably supply CLAUDE_CODE_OAUTH_TOKEN in the environment",
    )
    parser.add_argument(
        "--container-image",
        default="scibench-paper-agent:py310",
        help="Prebuilt local Podman image containing the claude CLI and scientific dependencies",
    )
    parser.add_argument("--container-python", default="python3")
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--container-cpus", type=float, default=4.0)
    parser.add_argument("--container-pids", type=int, default=512)
    parser.add_argument("--container-tmpfs-size", default="4g")
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--agent-timeout", type=float, default=3600)
    parser.add_argument("--execution-timeout", type=float, default=86400)
    parser.add_argument("--evaluator-timeout", type=float, default=3600)
    parser.add_argument("--agent-retries", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force-inference", action="store_true")
    parser.add_argument("--force-evaluation", action="store_true")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.task_ids = select_validated(args.task_ids)
        args.endpoint = validate_loopback_endpoint(args.endpoint)
    except ValueError as exc:
        parser.error(str(exc))
    if args.workers <= 0:
        parser.error("--workers must be positive")
    args.auth_source = None
    if args.api_key:
        args.auth_source = "--api-key"
    else:
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            value = os.environ.get(name)
            if value:
                args.api_key = value
                args.auth_source = name
                break
    if args.claude_oauth_token:
        args.auth_source = args.auth_source or "--claude-oauth-token"
    elif os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        args.claude_oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
        args.auth_source = args.auth_source or "CLAUDE_CODE_OAUTH_TOKEN"
    if not args.api_key and not args.claude_oauth_token:
        parser.error(
            "Claude Code container authentication requires --api-key, "
            "ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, "
            "--claude-oauth-token, or CLAUDE_CODE_OAUTH_TOKEN; host "
            "~/.claude login state is not mounted"
        )
    if args.container_cpus <= 0:
        parser.error("--container-cpus must be positive")
    if args.container_pids <= 0:
        parser.error("--container-pids must be positive")
    if (
        not args.run_id
        or args.run_id in {".", ".."}
        or Path(args.run_id).name != args.run_id
        or "/" in args.run_id
        or "\\" in args.run_id
    ):
        parser.error("--run-id must be one safe path component")
    if args.agent_retries < 0:
        parser.error("--agent-retries cannot be negative")
    if min(args.agent_timeout, args.execution_timeout, args.evaluator_timeout) <= 0:
        parser.error("all timeouts must be positive")
    args.output_root = args.output_root.resolve()
    args.workspace_root = (
        args.workspace_root.resolve() if args.workspace_root else None
    )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    progress(
        None,
        f"initializing run_id={args.run_id} model={args.model} "
        f"tasks={len(args.task_ids)} workers={args.workers}",
    )
    client = None
    try:
        client = podman_client()
        args.container_image_identity = local_image_identity(
            client, args.container_image
        )
    except ContainerRuntimeError as exc:
        print(f"Podman isolation unavailable: {exc}", file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()

    run_dir = args.output_root / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    existing_config_path = run_dir / "run_config.json"
    if existing_config_path.is_file():
        try:
            existing_config = read_json(existing_config_path)
        except EvaluationInputError as exc:
            print(f"invalid existing run configuration: {exc}", file=sys.stderr)
            return 2
        identity = ("run_id", "model", "endpoint", "container_image_digest")
        requested_identity = {
            "run_id": args.run_id,
            "model": args.model,
            "endpoint": args.endpoint,
            "container_image_digest": args.container_image_identity["digest"],
        }
        if any(
            existing_config.get(key) != requested_identity[key] for key in identity
        ):
            print(
                "existing run ID belongs to a different model, endpoint, "
                "or container image",
                file=sys.stderr,
            )
            return 2
    public_bundles = {}
    for task_id in args.task_ids:
        files = public_bundle_manifest(ROOT / task_id / "public")
        public_bundles[task_id] = {
            "fingerprint": public_bundle_fingerprint(files),
            "files": files,
        }
    config = {
        "schema_version": 1,
        "run_id": args.run_id,
        "created_at": utc_timestamp(),
        "backend": "claude_code",
        "model": args.model,
        "endpoint": args.endpoint,
        "auth_source": args.auth_source,
        "container_image": args.container_image_identity,
        "container_image_digest": args.container_image_identity["digest"],
        "task_ids": list(args.task_ids),
        "public_bundles": public_bundles,
        "workers": args.workers,
        "agent_timeout": args.agent_timeout,
        "execution_timeout": args.execution_timeout,
        "evaluator_timeout": args.evaluator_timeout,
        "agent_retries": args.agent_retries,
        "container_limits": {
            "memory": args.container_memory,
            "cpus": args.container_cpus,
            "pids": args.container_pids,
            "tmpfs_size": args.container_tmpfs_size,
        },
        "isolation": {
            "engine": "rootless-podman",
            "network": "none with Unix-socket loopback gateway relay during inference",
            "root_filesystem": "read-only",
            "capabilities": "all dropped",
            "trusted_execution_network": "none",
        },
    }
    write_json(run_dir / "run_config.json", config)
    progress(
        None,
        f"run configured output={run_dir} image={args.container_image_identity['digest']}",
    )

    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_task, args, run_dir, task_id): task_id
            for task_id in args.task_ids
        }
        for future in as_completed(futures):
            records.append(future.result())
    write_reports(run_dir, records)
    failures = sum(row.get("status") != "completed" for row in records)
    successful = sum(bool(row.get("full_success")) for row in records)
    scores = [
        float(row["score"])
        for row in records
        if isinstance(row.get("score"), (int, float))
    ]
    progress(
        None,
        f"finished tasks={len(records)} completed={len(records) - failures} "
        f"full_success={successful} mean_score="
        f"{(sum(scores) / len(scores)) if scores else 'n/a'} "
        f"failures={failures} output={run_dir}",
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
