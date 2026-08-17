"""Exploratory, audited Claude Code CLI pilot for Issues_No_Tests cases.

This mirrors offline_codex_pilot.py's prefetch-then-isolate design but shells
out to the local `claude` CLI (subscription login, no per-token API billing)
instead of Codex. It is NOT a drop-in replacement for the formal Codex pilot:
on macOS, sandbox-exec's `remote ip` predicate only accepts `localhost`, so
the outer OS-level network guard cannot allow-list the real
api.anthropic.com endpoint without a local loopback proxy. This script runs
with network_policy="unrestricted" (no OS-level network deny around the
`claude` subprocess) and instead relies on: (1) history-isolated checkouts
with no remote, so the model cannot fetch the golden patch/newer commits,
and (2) the same post-hoc trajectory + patch-path audit used by the Codex
pilot, adapted to Claude Code's stream-json event schema. Treat results as
exploratory signal, not as satisfying the same isolation guarantee as the
Codex offline pilot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.claude_code_inference import _capture_patch, _claude_bin
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json, with_wall_time
from swebench.eval_pipeline.inference_security import (
    inference_input_hash,
    inference_worktree_root,
)
from swebench.eval_pipeline.prompt_builder import _test_generation_instruction

MODEL = "claude-sonnet-4-5-20250929"
TIMEOUT = 900
EVAL_MODE = "test_generation"
AGENT_BACKEND = "claude_code_offline_pilot"
NETWORK_ISOLATION_LABEL = "unrestricted_no_os_sandbox_history_isolated_only"

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
            # Only flag a URL when it appears as an argument to a command that
            # actually fetches over the network. A bare https?://... substring
            # also matches license headers, doc comments, and other static
            # text an agent may legitimately write into a source/test file
            # (e.g. via `cat > file << EOF`), which is not network access.
            r"(?:^|[;&|\s])(?:/[^\s;&|]+/)?"
            r"(?:curl|wget|fetch|axel|aria2c)\s+[^;&|\n]*(?:https?|ftp)://",
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

# WebSearch/WebFetch are Claude Code's built-in web tools; disallow them
# explicitly via --disallowedTools in addition to auditing for their use.
DISALLOWED_TOOLS = ("WebSearch", "WebFetch")


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


def select_pilot_instances(instances_path: Path, instance_ids: list[str]) -> list[dict]:
    by_id = {row.get("instance_id"): row for row in _jsonl_rows(instances_path)}
    selected = []
    for instance_id in instance_ids:
        instance = by_id.get(instance_id)
        if instance is None:
            raise ValueError(f"instance not found: {instance_id}")
        if not re.fullmatch(r"[0-9a-f]{40}", str(instance.get("base_commit", ""))):
            raise ValueError(f"invalid base_commit for {instance_id}")
        if not (instance.get("problem_statement") or "").strip():
            raise ValueError(f"missing issue content for {instance_id}")
        selected.append(instance)
    return selected


def build_pilot_prompt(instance: dict) -> str:
    """Use issue text and base identity, without golden patch or mined test hints."""
    return (
        "You are running an offline scientific test-generation benchmark.\n"
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


def claude_command(model: str = MODEL) -> list[str]:
    return [
        _claude_bin(),
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--model",
        model,
        "--disallowedTools",
        ",".join(DISALLOWED_TOOLS),
    ]


def _tool_payload(event: dict) -> tuple[str, str] | None:
    """Return (tool name, auditable input) for a Claude Code stream tool-use event."""
    message = event.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    parts = []
    tool_name = ""
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "tool_use":
            tool_name = str(item.get("name") or "")
            parts.append(json.dumps(item.get("input"), sort_keys=True))
    if not tool_name:
        return None
    return tool_name, "\n".join(parts)


def audit_trajectory(text: str) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    seen: set[tuple[str, str]] = set()
    for line_number, raw in enumerate(text.splitlines(), 1):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payload = _tool_payload(event)
        if payload is None:
            continue
        tool_name, tool_input = payload
        lowered_name = tool_name.lower()
        if any(marker in lowered_name for marker in ("websearch", "webfetch", "mcp", "browser", "computer")):
            key = ("forbidden_tool", tool_input)
            if key not in seen:
                seen.add(key)
                findings.append(AuditFinding("forbidden_tool", line_number, f"{tool_name}: {tool_input}"))
        if lowered_name in {"bash", "bashoutput"}:
            for kind, pattern in _NETWORK_COMMAND_PATTERNS:
                if pattern.search(tool_input):
                    key = (kind, tool_input)
                    if key not in seen:
                        seen.add(key)
                        findings.append(AuditFinding(kind, line_number, tool_input))
    return findings


# Loose diff/patch files are never legitimate test edits: they are scratch
# artifacts the agent wrote while drafting a patch (observed in pilot runs),
# and if left in model_patch they get git-applied as new files during
# evaluation, bloating the diff with duplicated content.
_SCRATCH_PATCH_EXTENSIONS = (".patch", ".diff")
_BUILD_ARTIFACT_DIR_PATTERNS = ("build", "build-", "cmake-build-", "_build")
_BYTECODE_SUFFIXES = (".pyc", ".pyo")


def _untracked_root_scratch_paths(repo_dir: Path) -> set[str]:
    """Return new root-level patch/diff files created during this agent run.

    Limiting cleanup to untracked repository-root files protects existing patch
    fixtures and tracked files from being silently removed or altered.
    """
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
        and path.lower().endswith(_SCRATCH_PATCH_EXTENSIONS)
    }


def _is_build_artifact_path(parts: list[str], filename: str) -> bool:
    """Recognize generated build-directory/bytecode noise from running or
    compiling the codebase (e.g. `cmake -B build-regression`, `__pycache__`),
    which is not an agent-authored content change and must not veto an
    otherwise in-scope patch."""
    if "__pycache__" in parts or filename.endswith(_BYTECODE_SUFFIXES):
        return True
    return any(
        part == pattern or part.startswith(pattern)
        for part in parts[:-1]
        for pattern in _BUILD_ARTIFACT_DIR_PATTERNS
    )


def _strip_build_artifact_diff_blocks(
    patch: str, scratch_paths: set[str] | None = None
) -> str:
    """Drop generated build noise and known root-level scratch diff blocks.

    `_capture_patch` runs `git diff` after `git add -N .`, which also
    captures untracked build output (e.g. `cmake -B build-regression`,
    `__pycache__/*.pyc`) left over from the agent compiling/running its own
    test. That noise is not an authored content change and must not be
    scored, inflate the patch, or trigger the scope guard below.
    """
    if not patch:
        return patch
    scratch_paths = scratch_paths or set()
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
    kept = []
    for block in blocks:
        header = block[0]
        path = header.split(" b/", 1)[-1].strip()
        parts = path.lower().split("/")
        filename = parts[-1]
        if path in scratch_paths or _is_build_artifact_path(parts, filename):
            continue
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
        lowered = path.lower()
        parts = lowered.split("/")
        filename = parts[-1]
        if path in scratch_paths:
            continue
        if _is_build_artifact_path(parts, filename):
            continue
        if filename.endswith(_SCRATCH_PATCH_EXTENSIONS):
            disallowed.append(path)
            continue
        # Require an actual tests-directory component, not just a "test"
        # substring anywhere in the filename: a same-named scratch script
        # sitting at repo root (e.g. validate_test.py) is not a test file
        # just because the agent named it that way.
        testish = (
            "tests" in parts[:-1]
            or "test" in parts[:-1]
            or "unittest" in parts[:-1]
            or "unittests" in parts[:-1]
            or any(part in {"testdata", "test_data", "fixtures"} for part in parts[:-1])
            or (
                ("test" in filename or "tests" in filename)
                and (len(parts) > 1 or filename in {"cmakelists.txt", "meson.build"})
            )
        )
        if not testish:
            disallowed.append(path)
    return paths, disallowed


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def detect_rate_limit(stdout: str) -> bool:
    """Detect a subscription session-limit rejection in a Claude CLI stream.

    Claude Code emits a ``rate_limit_event`` on every turn (even successful
    ones, with ``status: "allowed"``), so presence of that event type alone
    is not a signal. A rejection is only real when the event reports
    ``status: "rejected"``, corroborated by the terminal ``result`` event
    reporting ``api_error_status: 429`` / ``error: "rate_limit"``. Checking
    both avoids both false negatives (a differently-worded future message)
    and false positives (a benign "allowed" event mentioning the word).
    """
    saw_rejected_status = False
    saw_result_rate_limit = False
    for raw in stdout.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info")
            if isinstance(info, dict) and info.get("status") == "rejected":
                saw_rejected_status = True
        if event.get("type") == "result" and (
            event.get("error") == "rate_limit" or event.get("api_error_status") == 429
        ):
            saw_result_rate_limit = True
    return saw_rejected_status or saw_result_rate_limit


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
    command = claude_command(model=model)
    command_path.write_text(json.dumps(command, indent=2) + "\n")
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
            input=prompt,
            timeout=timeout,
            env=dict(os.environ),
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode
        if exit_code:
            error = f"claude_exit_{exit_code}"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        error = "timeout"
    except OSError as exc:
        stderr = f"{type(exc).__name__}: {exc}\n"
        error = "process_error"

    trajectory_path.write_text(stdout)
    stderr_path.write_text(stderr)
    trajectory_hash = hashlib.sha256(stdout.encode()).hexdigest()
    if error and detect_rate_limit(stdout):
        error = "rate_limit"
    findings = audit_trajectory(stdout)
    scratch_paths = _untracked_root_scratch_paths(repo_dir)
    patch = _repair_patch(
        _clean_patch(
            _strip_build_artifact_diff_blocks(
                _capture_patch(repo_dir), scratch_paths=scratch_paths
            )
        )
    )
    changed_paths, disallowed_paths = audit_patch_paths(
        repo_dir, scratch_paths=scratch_paths
    )

    if findings:
        error = "attempted_network"
        patch = ""
    elif disallowed_paths:
        error = "disallowed_patch_scope"
        patch = ""

    audit = {
        "status": "failed" if error else "passed",
        "network_isolation": NETWORK_ISOLATION_LABEL,
        "network_findings": [finding.as_dict() for finding in findings],
        "changed_paths": changed_paths,
        "disallowed_paths": disallowed_paths,
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


def run_pilot(
    instances: list[dict],
    output_dir: Path,
    *,
    model: str = MODEL,
    timeout: int = TIMEOUT,
    github_token: str | None = None,
    workers: int = 3,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "trajectories").mkdir()
    _write_jsonl(output_dir / "instances.jsonl", instances)
    _write_jsonl(
        output_dir / "agent_prompts.jsonl",
        ({"instance_id": i["instance_id"], "prompt": build_pilot_prompt(i)} for i in instances),
    )

    private_root = inference_worktree_root("claude-offline-pilot")
    checkout_root = Path(tempfile.mkdtemp(prefix="run_", dir=private_root))
    worktrees: dict[str, Path] = {}
    try:
        # Finish every allowed network fetch before any agent is launched.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _clone_repo_at_commit,
                    instance["repo"],
                    instance["base_commit"],
                    github_token,
                    checkout_root,
                ): instance
                for instance in instances
            }
            for future in as_completed(futures):
                instance = futures[future]
                worktrees[instance["instance_id"]] = future.result()

        results: dict[str, tuple[dict, dict]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _run_one,
                    instance,
                    worktrees[instance["instance_id"]],
                    output_dir,
                    model,
                    timeout,
                ): instance["instance_id"]
                for instance in instances
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        ordered = [results[i["instance_id"]] for i in instances]
        predictions = [item[0] for item in ordered]
        _write_jsonl(output_dir / "agent_predictions.jsonl", predictions)
        (output_dir / "offline_audit.json").write_text(
            json.dumps(
                {
                    "model": model,
                    "timeout_seconds": timeout,
                    "tool_network": NETWORK_ISOLATION_LABEL,
                    "cases": [item[1] for item in ordered],
                    "manual_review_required": True,
                },
                indent=2,
            )
            + "\n"
        )
        return predictions
    finally:
        shutil.rmtree(checkout_root, ignore_errors=True)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instance-ids", nargs="+", required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate selection and print the frozen manifest without fetching or inference.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.timeout > TIMEOUT or args.timeout <= 0:
        raise SystemExit(f"timeout must be in 1..{TIMEOUT}")
    if args.workers < 1:
        raise SystemExit("workers must be >= 1")
    instances = select_pilot_instances(args.instances, args.instance_ids)
    if args.dry_run:
        print(
            json.dumps(
                [
                    {
                        "instance_id": i["instance_id"],
                        "repo": i["repo"],
                        "base_commit": i["base_commit"],
                    }
                    for i in instances
                ],
                indent=2,
            )
        )
        return 0
    run_pilot(
        instances,
        args.output_dir,
        model=args.model,
        timeout=args.timeout,
        github_token=args.github_token,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
