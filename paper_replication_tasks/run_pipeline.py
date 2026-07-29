#!/usr/bin/env python3
"""End-to-end formal evaluation pipeline for paper-replication tasks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import math
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .evaluation.framework import (
        EvaluationInputError,
        _validate_results,
        read_json,
        safe_submission_path,
    )
    from .task_registry import select_validated
except ImportError:  # Direct script execution.
    from evaluation.framework import (  # type: ignore
        EvaluationInputError,
        _validate_results,
        read_json,
        safe_submission_path,
    )
    from task_registry import select_validated  # type: ignore

from swebench.eval_pipeline.codex_inference import _write_endpoint_config
from swebench.eval_pipeline.claude_code_inference import _extract_claude_error
from swebench.eval_pipeline.inference_metrics import (
    metrics_from_stream_json,
    with_wall_time,
)
from paper_replication_tasks.container_runtime import (
    ContainerRuntimeError,
    local_image_identity,
    podman_client,
    run_podman_container,
)


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parent
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "paper_replication"
MAX_ENTRYPOINT_ARGUMENTS = 256
PROMPT = """\
You are reproducing one scientific paper task in a clean-room, offline workspace.
Only the files in this workspace are public benchmark inputs. Do not seek or use
the original paper repository, hidden reference values, evaluator code, or any
files outside this workspace.

Read task.md, input.json, submission_schema.json, and masked_paper.pdf. Implement
the complete requested method from scratch using only locally installed
dependencies. Your solution must be deterministic and rerunnable offline.

Before finishing, run your implementation. Leave all source code in this
workspace and write results.json at the workspace root with every required
artifact. The entrypoint in results.json must be the shell-style command that a
trusted runner can parse and execute directly without a shell. That entrypoint
must recreate results.json and all declared artifacts from a clean copy.
"""


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


def parse_entrypoint(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError("results.json entrypoint must be a non-empty string")
    try:
        command = shlex.split(value, posix=True)
    except ValueError as exc:
        raise EvaluationInputError(f"invalid entrypoint quoting: {exc}") from exc
    if not command or len(command) > MAX_ENTRYPOINT_ARGUMENTS:
        raise EvaluationInputError("entrypoint has an invalid number of arguments")
    if "\x00" in value or any("\x00" in item for item in command):
        raise EvaluationInputError("entrypoint contains a null byte")
    return command


def validate_initial_results(submission: Path, task_id: str) -> tuple[dict, list[str]]:
    results = read_json(submission / "results.json")
    artifacts = _validate_results(task_id, results, submission)
    command = parse_entrypoint(results["entrypoint"])
    for row in artifacts.values():
        path = safe_submission_path(submission, row["path"])
        if path.is_symlink():
            raise EvaluationInputError(f"artifact is a symlink: {row['path']}")
    return results, command


def prepare_execution_copy(raw_submission: Path, destination: Path, results: dict) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(raw_submission, destination, symlinks=True)
    for row in results["artifacts"]:
        artifact = safe_submission_path(destination, row["path"])
        if artifact.is_symlink():
            raise EvaluationInputError(f"artifact is a symlink: {row['path']}")
        if artifact.exists():
            if not artifact.is_file():
                raise EvaluationInputError(f"artifact is not a regular file: {row['path']}")
            artifact.unlink()
    (destination / "results.json").unlink(missing_ok=True)


def _command_for_backend(
    backend: str,
    model: str,
) -> list[str]:
    if backend == "codex":
        return [
            "codex",
            "exec",
            "--sandbox",
            "workspace-write",
            "--cd",
            "/workspace",
            "--model",
            model,
            "--json",
            "--ephemeral",
            PROMPT,
        ]
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
    backend: str,
    model: str,
    endpoint: str,
    api_key: str | None,
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
    }
    if backend == "codex":
        _write_endpoint_config(runtime_home, model, endpoint, bool(api_key))
        env["CODEX_HOME"] = "/agent-home"
        if api_key:
            env["CODEX_EVAL_PIPELINE_API_KEY"] = api_key
    else:
        env["ANTHROPIC_BASE_URL"] = endpoint
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
            env["ANTHROPIC_AUTH_TOKEN"] = api_key

    final_exit: int | None = None
    error: str | None = None
    timed_out = False
    client = podman_client()
    image_identity = local_image_identity(client, container_image)
    try:
        for index in range(retries + 1):
            command = _command_for_backend(backend, model)
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
                elif backend == "claude_code":
                    error = (
                        f"agent exited with code {final_exit}: "
                        f"{_extract_claude_error(stdout, stderr)}"
                    )
                else:
                    detail = (stderr or stdout).strip()[-500:]
                    error = (
                        f"agent exited with code {final_exit}"
                        + (f": {detail}" if detail else "")
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
                    "command": redact(command[:-1] + ["<prompt>"], [api_key or ""]),
                    "exit_code": final_exit,
                    "timed_out": timed_out,
                    "metrics": metrics,
                }
            )
            log_dir = task_dir / "agent"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"attempt-{index + 1}.jsonl").write_text(
                redact(stdout, [api_key or ""]), encoding="utf-8"
            )
            (log_dir / f"attempt-{index + 1}.stderr.log").write_text(
                redact(stderr, [api_key or ""]), encoding="utf-8"
            )
            if final_exit == 0 or final_exit is None:
                break
    finally:
        client.close()
    redact_tree_credentials(runtime_home, [api_key or ""])

    aggregate["wall_time_seconds"] = sum(
        float(row["metrics"].get("wall_time_seconds", 0)) for row in attempts
    )
    aggregate["turns"] = sum(
        int(row["metrics"].get("turns", 0)) for row in attempts
    )
    return {
        "backend": backend,
        "model": model,
        "exit_code": final_exit,
        "timed_out": timed_out,
        "error": redact(error, [api_key or ""]),
        "container_image": image_identity,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "usage": aggregate,
    }


def run_trusted_execution(
    *,
    task_id: str,
    execution_dir: Path,
    command: list[str],
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
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runner_copy = runtime_dir / "trusted_runner.py"
    shutil.copy2(ROOT / "run_submission.py", runner_copy)
    manifest_path.unlink(missing_ok=True)
    runtime_home = manifest_path.parent / "trusted_output"
    runtime_home.mkdir(parents=True, exist_ok=True)
    container_manifest = runtime_home / "execution_manifest.json"
    container_manifest.unlink(missing_ok=True)
    invocation = [
        container_python,
        "/runner/trusted_runner.py",
        "--submission-dir",
        "/workspace",
        "--task-id",
        task_id,
        "--output",
        "/agent-home/execution_manifest.json",
        "--timeout-seconds",
        str(timeout),
        "--",
        *command,
    ]
    client = podman_client()
    try:
        container_result = run_podman_container(
            client=client,
            image=container_image,
            command=invocation,
            workspace=execution_dir,
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
        )
        result = {
            "runner_exit_code": container_result["exit_code"],
            "stderr": container_result["stderr"],
            "timed_out": container_result["timed_out"],
            "container_id": container_result["container_id"],
        }
    finally:
        client.close()
    if container_manifest.is_file():
        shutil.copy2(container_manifest, manifest_path)
        result["manifest"] = read_json(manifest_path)
    return result


def run_evaluator(
    task_id: str,
    execution_dir: Path,
    manifest_path: Path,
    output_path: Path,
    timeout: float,
) -> dict[str, Any]:
    hidden = ROOT / task_id / "hidden"
    output_path.unlink(missing_ok=True)
    command = [
        sys.executable,
        str(hidden / "evaluator.py"),
        "--submission-dir",
        str(execution_dir),
        "--gold",
        str(hidden / "gold_output.json"),
        "--run-manifest",
        str(manifest_path),
        "--output",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        result = {
            "exit_code": completed.returncode,
            "stderr": completed.stderr or "",
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "exit_code": 124,
            "stderr": (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr or b"").decode(errors="replace")
            ),
            "timed_out": True,
        }
    if output_path.is_file():
        result["report"] = read_json(output_path)
    return result


def fingerprint_record(
    task_id: str,
    backend: str,
    model: str,
    public_fingerprint: str,
    container_image_digest: str,
) -> dict[str, str]:
    return {
        "task_id": task_id,
        "backend": backend,
        "model": model,
        "public_bundle_fingerprint": public_fingerprint,
        "container_image_digest": container_image_digest,
    }


def resume_matches(record: dict[str, Any], expected: dict[str, str]) -> bool:
    return all(record.get(key) == value for key, value in expected.items())


def _base_record(
    task_id: str,
    backend: str,
    model: str,
    fingerprint: str,
    container_image_digest: str,
) -> dict[str, Any]:
    return {
        **fingerprint_record(
            task_id, backend, model, fingerprint, container_image_digest
        ),
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
        task_id,
        args.backend,
        args.model,
        bundle_hash,
        args.container_image_identity["digest"],
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
        return prior

    task_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = task_dir / "raw_submission"
    execution_dir = task_dir / "executed_submission"
    record = _base_record(
        task_id,
        args.backend,
        args.model,
        bundle_hash,
        args.container_image_identity["digest"],
    )
    record["public_bundle"] = public_manifest
    record["agent"] = prior.get("agent") if prior else None
    secrets = [args.api_key or ""]

    reuse_inference = (
        args.resume
        and prior is not None
        and resume_matches(prior, expected)
        and raw_dir.is_dir()
        and not args.force_inference
    )
    try:
        if not reuse_inference:
            with tempfile.TemporaryDirectory(
                prefix=f"{task_id}-", dir=args.workspace_root
            ) as temporary:
                workspace = Path(temporary) / "workspace"
                create_agent_workspace(public_dir, workspace)
                record["agent"] = run_agent(
                    backend=args.backend,
                    model=args.model,
                    endpoint=args.endpoint,
                    api_key=args.api_key,
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
                redact_tree_credentials(workspace, secrets)
                if raw_dir.exists():
                    shutil.rmtree(raw_dir)
                shutil.copytree(workspace, raw_dir, symlinks=True)
            record["stage"] = "inference"
            write_json(record_path, redact(record, secrets))

        if not raw_dir.is_dir():
            raise EvaluationInputError("agent did not produce a submission workspace")
        if (
            (record.get("agent") or {}).get("exit_code") != 0
            and not (raw_dir / "results.json").is_file()
        ):
            record["failure_type"] = "inference"
            record["error"] = (record.get("agent") or {}).get("error")
            raise RuntimeError("agent inference failed")
        initial_results, entrypoint = validate_initial_results(raw_dir, task_id)
        prepare_execution_copy(raw_dir, execution_dir, initial_results)
        manifest_path = task_dir / "execution_manifest.json"
        execution = run_trusted_execution(
            task_id=task_id,
            execution_dir=execution_dir,
            command=entrypoint,
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
        if execution.get("runner_exit_code") != 0 or not manifest_path.is_file():
            record["failure_type"] = "execution"
            record["error"] = execution.get("stderr") or "trusted runner failed"
            raise RuntimeError("trusted execution failed")
        execution_valid = execution["manifest"].get("exit_code") == 0

        evaluation_path = task_dir / "evaluation.json"
        evaluation = run_evaluator(
            task_id,
            execution_dir,
            manifest_path,
            evaluation_path,
            args.evaluator_timeout,
        )
        record["evaluator"] = evaluation
        if evaluation.get("exit_code") != 0 or "report" not in evaluation:
            record["failure_type"] = (
                "format" if evaluation.get("exit_code") == 2 else "evaluator"
            )
            record["error"] = evaluation.get("stderr") or "evaluator failed"
        else:
            report = evaluation["report"]
            record["score"] = report.get("score")
            record["full_success"] = report.get("full_success")
            record["valid_execution"] = report.get("valid_execution")
            if execution_valid and report.get("valid_execution") is True:
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
    except (ContainerRuntimeError, OSError, subprocess.SubprocessError) as exc:
        record["failure_type"] = record.get("failure_type") or "infrastructure"
        record["error"] = str(exc)
    except Exception as exc:
        record["failure_type"] = record.get("failure_type") or "infrastructure"
        record["error"] = record.get("error") or f"{type(exc).__name__}: {exc}"
    record["ended_at"] = utc_timestamp()
    clean = redact(record, secrets)
    write_json(record_path, clean)
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
        "task_id", "backend", "model", "status", "failure_type", "score",
        "full_success", "valid_execution", "completeness", "input_tokens",
        "output_tokens", "total_tokens", "cost_usd", "agent_wall_seconds",
        "execution_wall_seconds", "cpu_seconds", "peak_memory_bytes",
    ]
    with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=result_fields)
        writer.writeheader()
        for record in ordered:
            usage = (record.get("agent") or {}).get("usage") or {}
            manifest = (record.get("execution") or {}).get("manifest") or {}
            resource = manifest.get("resource_usage") or {}
            checks = ((record.get("evaluator") or {}).get("report") or {}).get("checks") or []
            artifact_checks = [row for row in checks if row.get("category") == "artifacts"]
            completeness = (
                sum(bool(row.get("passed")) for row in artifact_checks) / len(artifact_checks)
                if artifact_checks else 0.0
            )
            writer.writerow({
                "task_id": record["task_id"],
                "backend": record["backend"],
                "model": record["model"],
                "status": record.get("status"),
                "failure_type": record.get("failure_type"),
                "score": record.get("score"),
                "full_success": record.get("full_success"),
                "valid_execution": record.get("valid_execution"),
                "completeness": completeness,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_usd": usage.get("cost_usd"),
                "agent_wall_seconds": usage.get("wall_time_seconds"),
                "execution_wall_seconds": resource.get("wall_seconds"),
                "cpu_seconds": resource.get("cpu_seconds"),
                "peak_memory_bytes": resource.get("peak_memory_bytes"),
            })

    difference_fields = [
        "task_id", "check_id", "category", "passed", "critical", "message",
        "max_abs", "rmse", "expected", "actual", "absolute_tolerance",
        "relative_tolerance", "max_abs_tolerance", "rmse_tolerance",
        "tolerance", "diagnostics_json",
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
                    "category": check.get("category"),
                    "passed": check.get("passed"),
                    "critical": check.get("critical"),
                    "message": check.get("message"),
                    "max_abs": _diagnostic_value(
                        diagnostics,
                        "max_abs",
                        "max_absolute_error",
                        "maximum_absolute_error",
                        "best_max_abs",
                        "symmetry_max_abs",
                    ),
                    "rmse": _diagnostic_value(
                        diagnostics, "rmse", "root_mean_square_error"
                    ),
                    "expected": json.dumps(
                        _diagnostic_value(diagnostics, "expected", "recomputed"),
                        allow_nan=False,
                    ),
                    "actual": json.dumps(
                        _diagnostic_value(diagnostics, "actual", "reported"),
                        allow_nan=False,
                    ),
                    "absolute_tolerance": _diagnostic_value(
                        diagnostics, "absolute_tolerance", "atol"
                    ),
                    "relative_tolerance": _diagnostic_value(
                        diagnostics, "relative_tolerance", "rtol"
                    ),
                    "max_abs_tolerance": _diagnostic_value(
                        diagnostics, "max_abs_limit"
                    ),
                    "rmse_tolerance": _diagnostic_value(
                        diagnostics, "rmse_limit"
                    ),
                    "tolerance": _diagnostic_value(diagnostics, "limit"),
                    "diagnostics_json": json.dumps(
                        diagnostics, sort_keys=True, allow_nan=False
                    ),
                })

    completed = [row for row in ordered if row.get("status") == "completed"]
    scores = [float(row["score"]) for row in completed if isinstance(row.get("score"), (int, float))]
    failure_counts: dict[str, int] = {}
    for row in ordered:
        failure = row.get("failure_type")
        if failure:
            failure_counts[str(failure)] = failure_counts.get(str(failure), 0) + 1
    total_usage: dict[str, float] = {}
    total_execution = {
        "cpu_seconds": 0.0,
        "wall_seconds": 0.0,
        "peak_memory_bytes_max": 0,
    }
    for row in ordered:
        usage = (row.get("agent") or {}).get("usage") or {}
        for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "wall_time_seconds"):
            if isinstance(usage.get(key), (int, float)):
                total_usage[key] = total_usage.get(key, 0) + usage[key]
        resource = ((row.get("execution") or {}).get("manifest") or {}).get(
            "resource_usage"
        ) or {}
        for key in ("cpu_seconds", "wall_seconds"):
            if isinstance(resource.get(key), (int, float)):
                total_execution[key] += resource[key]
        peak = resource.get("peak_memory_bytes")
        if isinstance(peak, (int, float)):
            total_execution["peak_memory_bytes_max"] = max(
                total_execution["peak_memory_bytes_max"], int(peak)
            )
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
        "total_execution_resource_usage": total_execution,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("codex", "claude_code"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key")
    parser.add_argument(
        "--container-image",
        required=True,
        help="Prebuilt local Podman image containing the agent CLI and scientific dependencies",
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
        identity = (
            "run_id",
            "backend",
            "model",
            "endpoint",
            "container_image_digest",
        )
        requested_identity = {
            "run_id": args.run_id,
            "backend": args.backend,
            "model": args.model,
            "endpoint": args.endpoint,
            "container_image_digest": args.container_image_identity["digest"],
        }
        if any(
            existing_config.get(key) != requested_identity[key] for key in identity
        ):
            print(
                "existing run ID belongs to a different backend, model, endpoint, "
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
        "backend": args.backend,
        "model": args.model,
        "endpoint": args.endpoint,
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
    print(f"wrote {len(records)} task result(s) to {run_dir}; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
