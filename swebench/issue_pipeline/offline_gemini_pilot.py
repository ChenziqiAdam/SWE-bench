"""Audited Antigravity CLI runner using Gemini for regression-test generation.

The model connection itself remains available for inference. Terminal commands
run in Antigravity's native sandbox and every streamed tool event is audited,
while a single-commit checkout with no remotes prevents history access. Built-in
web tools cannot currently be removed from Antigravity, so this runner is not
described as fully network-disabled and rejects any trajectory that uses them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from swebench.eval_pipeline.claude_code_inference import _capture_patch
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json, with_wall_time
from swebench.eval_pipeline.inference_security import inference_input_hash
from swebench.eval_pipeline.prompt_builder import _test_generation_instruction


MODEL = "gemini-3.6-flash-high"
CLI_VERSION = "1.1.15"
TIMEOUT = 900
EVAL_MODE = "test_generation"
AGENT_BACKEND = "antigravity_cli"
NETWORK_ISOLATION_LABEL = (
    "history_isolated_terminal_sandbox_audited_not_fully_network_disabled"
)

SAFE_CORE_TOOLS = (
    "grep_search",
    "list_dir",
    "multi_replace_file_content",
    "replace_file_content",
    "run_command",
    "sed_file",
    "view_file",
    "write_to_file",
    "command_status",
    "send_command_input",
    "finish",
    "manage_task",
    "wait",
    "wait_5_seconds",
)
FORBIDDEN_TOOLS = (
    "browser_*",
    "call_mcp_tool",
    "define_subagent",
    "execute_browser_javascript",
    "invoke_subagent",
    "open_browser_url",
    "read_url_content",
    "search_web",
)

_NETWORK_COMMAND_PATTERNS = (
    ("curl", re.compile(r"(?:^|[;&|\s])(?:/[^\s;&|]+/)?curl(?:\s|$)", re.I)),
    ("wget", re.compile(r"(?:^|[;&|\s])(?:/[^\s;&|]+/)?wget(?:\s|$)", re.I)),
    (
        "network_git",
        re.compile(
            r"(?:^|[;&|\s])(?:/[^\s;&|]+/)?git\s+"
            r"(?:clone|fetch|pull|push|ls-remote|remote\s+update)(?:\s|$)",
            re.I,
        ),
    ),
    (
        "git_submodule_network",
        re.compile(r"(?:^|[;&|\s])git\s+submodule\s+(?:update|add)(?:\s|$)", re.I),
    ),
    (
        "package_install",
        re.compile(
            r"(?:^|[;&|\s])(?:(?:python3?|/[^\s;&|]*/python3?)\s+-m\s+pip|"
            r"pip3?|uv\s+pip|conda|mamba|npm|pnpm|yarn|apt(?:-get)?|dnf|yum|"
            r"brew|cargo|go)\s+(?:[^;&|\n]*\s)?(?:install|add)(?:\s|$)",
            re.I,
        ),
    ),
    (
        "url_fetch",
        re.compile(
            r"(?:^|[;&|\s])(?:/[^\s;&|]+/)?(?:curl|wget|fetch|axel|aria2c)"
            r"\s+[^;&|\n]*(?:https?|ftp)://",
            re.I,
        ),
    ),
    (
        "socket_client",
        re.compile(
            r"(?:socket\.(?:socket|create_connection)|urllib\.request|requests\."
            r"(?:get|post|put|delete)|httpx\.|aiohttp\.|(?:^|\s)(?:nc|netcat|"
            r"telnet|ssh|scp)(?:\s|$))",
            re.I,
        ),
    ),
)

_BUILD_ARTIFACT_DIR_PATTERNS = ("build", "build-", "cmake-build-", "_build")
_BYTECODE_SUFFIXES = (".pyc", ".pyo")
_ROOT_SCRATCH_SUFFIXES = (".diff", ".patch")
_ROOT_SCRATCH_NAME_PREFIXES = (
    "analysis",
    "debug",
    "notes",
    "repro",
    "scratch",
    "temp",
    "test_patch",
    "tmp",
    "validate",
    "verify",
)
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:^|_)(?:API_?KEY|AUTH|CREDENTIALS?|KEY|PASSWORD|SECRET|TOKEN)(?:_|$)",
    re.I,
)


@dataclass(frozen=True)
class AuditFinding:
    kind: str
    event_line: int
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "event_line": self.event_line,
            "evidence": self.evidence[:500],
        }


def _jsonl_rows(path: Path) -> list[dict]:
    rows = []
    with path.open() as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL in {path} at line {line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"non-object JSONL row in {path} at line {line_number}")
            rows.append(row)
    return rows


def build_pilot_prompt(instance: dict) -> str:
    """Build only from issue text and base identity; ignore all mined/gold fields."""
    return (
        "You are running a scientific regression-test generation benchmark.\n"
        f"Repository: {instance['repo']}\n"
        f"Base commit: {instance['base_commit']}\n\n"
        "Network access from tools is forbidden. Do not use web/browser tools, URLs, "
        "curl, wget, networked git commands, package installation, or sockets. Do not "
        "download dependencies. You may inspect the checkout, edit tests, and run "
        "already-available focused tests.\n\n"
        "Issue:\n"
        f"{instance['problem_statement'].strip()}\n\n"
        f"{_test_generation_instruction()}"
    )


def _antigravity_bin() -> str:
    """Find Antigravity CLI without inspecting authentication files."""
    found = shutil.which("agy")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "agy"
    if candidate.exists():
        return str(candidate)
    candidate = Path(sys.executable).parent / "agy"
    return str(candidate) if candidate.exists() else "agy"


def validate_antigravity_cli(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, str]:
    """Require the frozen CLI, selected model, and an empty plugin inventory."""
    executable = _antigravity_bin()
    common = {"capture_output": True, "text": True, "timeout": 30, "check": True}
    version = runner([executable, "--version"], **common).stdout.strip()
    if version != CLI_VERSION:
        raise RuntimeError(
            f"formal run requires Antigravity CLI {CLI_VERSION}; found {version or 'unknown'}"
        )
    plugins = runner([executable, "plugins", "list"], **common).stdout.strip()
    if plugins != "No imported plugins.":
        raise RuntimeError("formal run requires no imported Antigravity plugins")
    models = runner([executable, "models"], **common).stdout.splitlines()
    slugs = {line.split("\t", 1)[0].strip() for line in models if line.strip()}
    if MODEL not in slugs:
        raise RuntimeError(f"Antigravity model is unavailable: {MODEL}")
    return {"executable": executable, "version": version, "plugins": "none"}


def safety_settings() -> dict[str, Any]:
    """Frozen Antigravity controls and explicit observability limitations."""
    return {
        "cli": "agy",
        "cli_version": CLI_VERSION,
        "flags": {
            "new_project": True,
            "terminal_sandbox": True,
            "auto_approve_in_sandbox": True,
            "disable_slash_commands_and_skills": True,
            "mode": "accept-edits",
            "output_format": "stream-json",
        },
        "plugins_required": "none_imported",
        "trajectory_policy": {
            "allowed_tools": list(SAFE_CORE_TOOLS),
            "forbidden_tools": list(FORBIDDEN_TOOLS),
            "reject_network_and_package_shell_commands": True,
            "reject_unknown_tools": True,
            "post_run_stream_json_audit": True,
        },
        "limitation": (
            "Antigravity advertises built-in web/browser/subagent tools; the CLI "
            "has no per-run tool-removal flag. The prompt forbids them and their "
            "use is rejected from the complete stream-json trajectory."
        ),
    }


def safety_settings_hash(settings: dict[str, Any] | None = None) -> str:
    data = json.dumps(
        settings or safety_settings(), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(data).hexdigest()


def gemini_command(prompt: str, model: str = MODEL, timeout: int = TIMEOUT) -> list[str]:
    return [
        _antigravity_bin(),
        "--new-project",
        "--sandbox",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
        "--mode",
        "accept-edits",
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--print-timeout",
        f"{timeout}s",
        "--print",
        prompt,
    ]


def _gemini_env() -> dict[str, str]:
    """Pass normal process context without copying credential-valued variables."""
    env = {
        name: os.environ[name]
        for name in os.environ
        if not _SENSITIVE_ENV_NAME.search(name)
    }
    return env


def _tool_payload(event: dict) -> tuple[str, str] | None:
    if event.get("event") == "step_update":
        update = event.get("step_update")
        if not isinstance(update, dict) or update.get("step_type") != "tool":
            return None
        tool_info = update.get("tool_info")
        tool_info = tool_info if isinstance(tool_info, dict) else {}
        name = str(update.get("tool_name") or tool_info.get("name") or "")
        parameters = tool_info.get("parameters", {})
    elif event.get("type") == "tool_use":
        # Retain compatibility with the former Gemini stream schema so old
        # trajectories remain auditable.
        name = str(event.get("tool_name") or event.get("name") or "")
        parameters = event.get("parameters", event.get("input", {}))
    else:
        return None
    if name.lower() in {"run_command", "run_shell_command", "shell", "bash"} and isinstance(
        parameters, dict
    ):
        command = (
            parameters.get("CommandLine")
            or parameters.get("command")
            or parameters.get("cmd")
        )
        if isinstance(command, str):
            return name, command
    return name, json.dumps(parameters, sort_keys=True)


def audit_trajectory(text: str) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    seen: set[tuple[str, str]] = set()
    for line_number, raw in enumerate(text.splitlines(), 1):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        payload = _tool_payload(event)
        if payload is None:
            continue
        tool_name, tool_input = payload
        lowered = tool_name.lower()
        if (
            lowered not in SAFE_CORE_TOOLS
            or any(x in lowered for x in ("web", "browser", "mcp", "agent", "skill"))
        ):
            key = ("forbidden_tool", f"{tool_name}: {tool_input}")
            if key not in seen:
                seen.add(key)
                findings.append(AuditFinding(key[0], line_number, key[1]))
        if lowered in {"run_command", "run_shell_command", "shell", "bash"}:
            for kind, pattern in _NETWORK_COMMAND_PATTERNS:
                if pattern.search(tool_input):
                    key = (kind, tool_input)
                    if key not in seen:
                        seen.add(key)
                        findings.append(AuditFinding(kind, line_number, tool_input))
    return findings


def detect_quota_limit(stdout: str, stderr: str = "") -> bool:
    """Recognize structured 429/resource-exhausted and common quota messages."""
    for raw in stdout.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        result = event.get("result") if event.get("event") == "result" else None
        error = result.get("error") if isinstance(result, dict) else event.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            kind = str(error.get("type") or error.get("status") or "").lower()
            message = str(error.get("message") or "")
            if code == 429 or "resource_exhausted" in kind or _quota_text(message):
                return True
        elif isinstance(error, str) and _quota_text(error):
            return True
    return _quota_text(stdout) or _quota_text(stderr)


def _terminal_error(stdout: str) -> bool:
    for raw in reversed(stdout.splitlines()):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("event") != "result":
            continue
        result = event.get("result")
        return isinstance(result, dict) and str(result.get("status", "")).upper() != "SUCCESS"
    return False


def _quota_text(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in (
            "quota exceeded",
            "quota reached",
            "rate limit exceeded",
            "resource_exhausted",
            "too many requests",
            "capacity exhausted",
        )
    )


def _untracked_root_scratch_paths(repo_dir: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        path
        for path in result.stdout.split("\0")
        if path
        and "/" not in path
        and (
            path.lower().endswith(_ROOT_SCRATCH_SUFFIXES)
            or (
                path.lower().endswith((".md", ".py", ".sh"))
                and Path(path).stem.lower().startswith(_ROOT_SCRATCH_NAME_PREFIXES)
            )
        )
    }


def _is_build_artifact_path(parts: list[str], filename: str) -> bool:
    if "__pycache__" in parts or filename.endswith(_BYTECODE_SUFFIXES):
        return True
    return any(
        part == pattern or part.startswith(pattern)
        for part in parts[:-1]
        for pattern in _BUILD_ARTIFACT_DIR_PATTERNS
    )


def _strip_artifact_diff_blocks(patch: str, scratch_paths: set[str]) -> str:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    kept: list[str] = []
    for block in blocks:
        path = block[0].split(" b/", 1)[-1].strip()
        parts = path.lower().split("/")
        if path not in scratch_paths and not _is_build_artifact_path(parts, parts[-1]):
            kept.extend(block)
    return "".join(kept)


def audit_patch_paths(
    repo_dir: Path, scratch_paths: set[str] | None = None
) -> tuple[list[str], list[str]]:
    scratch_paths = scratch_paths or set()
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [line for line in result.stdout.splitlines() if line]
    disallowed = []
    for path in paths:
        parts = path.lower().split("/")
        filename = parts[-1]
        if path in scratch_paths or _is_build_artifact_path(parts, filename):
            continue
        testish = (
            any(part in {"test", "tests", "unittest", "unittests"} for part in parts[:-1])
            or any(part in {"testdata", "test_data", "fixtures"} for part in parts[:-1])
            or (("test" in filename or "tests" in filename) and len(parts) > 1)
            or (
                filename in {"cmakelists.txt", "meson.build"}
                and any("test" in part for part in parts[:-1])
            )
        )
        if not testish:
            disallowed.append(path)
    return paths, disallowed


def _run_one(
    instance: dict,
    repo_dir: Path,
    output_dir: Path,
    model: str,
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[dict, dict]:
    instance_id = instance["instance_id"]
    trajectory_path = output_dir / "trajectories" / f"{instance_id}.jsonl"
    stderr_path = output_dir / "trajectories" / f"{instance_id}.stderr.log"
    command_path = output_dir / "trajectories" / f"{instance_id}.command.json"
    prompt = build_pilot_prompt(instance)
    command = gemini_command(prompt, model=model, timeout=timeout)
    settings = safety_settings()
    settings_hash = safety_settings_hash(settings)
    audited_command = list(command)
    audited_command[-1] = "<redacted_issue_prompt>"
    command_path.write_text(
        json.dumps(
            {
                "argv": audited_command,
                "prompt_delivery": "redacted_argv",
                "safety_settings": settings,
                "safety_settings_sha256": settings_hash,
                "network_isolation": NETWORK_ISOLATION_LABEL,
            },
            indent=2,
        )
        + "\n"
    )
    started = time.perf_counter()
    stdout = ""
    stderr = ""
    error: str | None = None
    exit_code: int | None = None
    try:
        result = runner(
            command,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_gemini_env(),
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode
        if exit_code:
            error = f"antigravity_exit_{exit_code}"
        elif _terminal_error(stdout):
            error = "antigravity_result_error"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        error = "timeout"
    except OSError as exc:
        stderr = f"{type(exc).__name__}: {exc}\n"
        error = "process_error"

    if detect_quota_limit(stdout, stderr):
        error = "quota_limit"
    trajectory_path.write_text(stdout)
    stderr_path.write_text(stderr)
    trajectory_hash = hashlib.sha256(stdout.encode()).hexdigest()
    findings = audit_trajectory(stdout)
    scratch_paths = _untracked_root_scratch_paths(repo_dir)
    patch = _repair_patch(
        _clean_patch(_strip_artifact_diff_blocks(_capture_patch(repo_dir), scratch_paths))
    )
    changed_paths, disallowed_paths = audit_patch_paths(repo_dir, scratch_paths)
    if findings and error != "quota_limit":
        error = "attempted_network"
    elif disallowed_paths and error != "quota_limit":
        error = "disallowed_patch_scope"
    if error:
        patch = ""

    audit = {
        "status": "failed" if error else "passed",
        "network_isolation": NETWORK_ISOLATION_LABEL,
        "network_findings": [finding.as_dict() for finding in findings],
        "changed_paths": changed_paths,
        "disallowed_paths": disallowed_paths,
        "safety_settings_sha256": settings_hash,
        "trajectory_path": str(trajectory_path.relative_to(output_dir)),
        "trajectory_sha256": trajectory_hash,
        "manual_review": "pending",
    }
    record = {
        "instance_id": instance_id,
        "model_patch": patch,
        "model_name_or_path": model,
        "agent_backend": AGENT_BACKEND,
        "eval_mode": EVAL_MODE,
        "inference_input_hash": inference_input_hash(instance),
        "offline_audit": audit,
        "trajectory_sha256": trajectory_hash,
        "metrics": with_wall_time(
            metrics_from_stream_json(stdout), time.perf_counter() - started
        ),
    }
    if error:
        record["error"] = error
    return record, {"instance_id": instance_id, **audit, "exit_code": exit_code}
