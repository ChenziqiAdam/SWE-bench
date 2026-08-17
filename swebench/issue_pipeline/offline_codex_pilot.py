"""Strictly audited, offline-tool Codex pilot for Issues_No_Tests cases."""
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

import openpyxl

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.codex_inference import _capture_patch, _codex_bin
from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json, with_wall_time
from swebench.eval_pipeline.inference_security import (
    inference_input_hash,
    inference_worktree_root,
)
from swebench.eval_pipeline.prompt_builder import _test_generation_instruction


MODEL = "gpt-5.6-sol"
TIMEOUT = 900
EVAL_MODE = "test_generation"
PILOT_CASES = {
    "openmm__openmm-4161": ("openmm/openmm", 4152, 4161, "Batch 2"),
    "openmm__openmm-5302": ("openmm/openmm", 5300, 5302, "Batch 1"),
    "rdkit__rdkit-7990": ("rdkit/rdkit", 7989, 7990, "Batch 2"),
}

# These are disabled explicitly in addition to --ignore-user-config. This makes the
# intended tool surface reviewable in the saved command log and independent of a
# researcher's personal Codex configuration.
DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "plugins",
    "plugin_sharing",
    "remote_plugin",
    "skill_search",
    "standalone_web_search",
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
    ("url", re.compile(r"(?:https?|ftp)://", re.I)),
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


def select_pilot_instances(excel_path: Path, instances_path: Path) -> list[dict]:
    """Cross-check the fixed pilot cases against the workbook and instance JSONL."""
    workbook = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    found: dict[str, tuple[str, int, int, str]] = {}
    try:
        for sheet in workbook:
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows)
            for values in rows:
                row = dict(zip(headers, values))
                if not row.get("Repo") or not row.get("Closing PR #"):
                    continue
                instance_id = (
                    str(row["Repo"]).replace("/", "__", 1)
                    + f"-{int(row['Closing PR #'])}"
                )
                if instance_id in PILOT_CASES:
                    found[instance_id] = (
                        str(row["Repo"]),
                        int(row["Issue Number"]),
                        int(row["Closing PR #"]),
                        sheet.title,
                    )
    finally:
        workbook.close()

    for instance_id, expected in PILOT_CASES.items():
        if found.get(instance_id) != expected:
            raise ValueError(
                f"spreadsheet mismatch for {instance_id}: expected {expected}, "
                f"found {found.get(instance_id)}"
            )

    by_id = {row.get("instance_id"): row for row in _jsonl_rows(instances_path)}
    selected = []
    for instance_id, (repo, _issue, _pr, _sheet) in PILOT_CASES.items():
        instance = by_id.get(instance_id)
        if instance is None:
            raise ValueError(f"instance not found: {instance_id}")
        if instance.get("repo") != repo:
            raise ValueError(f"repository mismatch for {instance_id}")
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


def codex_command(repo_dir: Path, prompt: str, model: str = MODEL) -> list[str]:
    command = [
        _codex_bin(),
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(repo_dir),
        "--model",
        model,
        "--json",
        "--ephemeral",
        "--config",
        'approval_policy="never"',
        "--config",
        "sandbox_workspace_write.network_access=false",
        "--config",
        "mcp_servers={}",
    ]
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    command.append(prompt)
    return command


def _tool_payload(event: dict) -> tuple[str, str] | None:
    """Return (tool type, auditable input) for a Codex stream tool event."""
    item = event.get("item")
    if not isinstance(item, dict):
        item = event.get("data") if isinstance(event.get("data"), dict) else event
    tool_type = str(item.get("type") or event.get("type") or "").lower()
    if not any(
        marker in tool_type
        for marker in ("command", "shell", "exec", "mcp", "web", "browser", "computer")
    ):
        return None
    values = []
    for key in ("command", "cmd", "arguments", "input", "query", "url", "name"):
        value = item.get(key)
        if value is not None:
            values.append(value if isinstance(value, str) else json.dumps(value, sort_keys=True))
    return tool_type, "\n".join(values)


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
        tool_type, tool_input = payload
        if any(marker in tool_type for marker in ("mcp", "web", "browser", "computer")):
            key = ("forbidden_tool", tool_input)
            if key not in seen:
                seen.add(key)
                findings.append(AuditFinding("forbidden_tool", line_number, f"{tool_type}: {tool_input}"))
        if any(marker in tool_type for marker in ("command", "shell", "exec")):
            for kind, pattern in _NETWORK_COMMAND_PATTERNS:
                if pattern.search(tool_input):
                    key = (kind, tool_input)
                    if key not in seen:
                        seen.add(key)
                        findings.append(AuditFinding(kind, line_number, tool_input))
    return findings


_BUILD_ARTIFACT_DIR_PATTERNS = ("build", "build-", "cmake-build-", "_build")
_BYTECODE_SUFFIXES = (".pyc", ".pyo")
_SCRATCH_PATCH_EXTENSIONS = (".patch", ".diff")


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
        testish = (
            "test" in filename
            or any(part in {"test", "tests", "unittest", "unittests"} for part in parts)
            or any(part in {"testdata", "test_data", "fixtures"} for part in parts)
            or (filename in {"cmakelists.txt", "meson.build"} and any("test" in p for p in parts[:-1]))
        )
        if not testish:
            disallowed.append(path)
    return paths, disallowed


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


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
    command = codex_command(repo_dir, prompt, model=model)
    command_path.write_text(json.dumps(command[:-1] + ["<prompt>"], indent=2) + "\n")
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
            env=dict(os.environ),
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode
        if exit_code:
            error = f"codex_exit_{exit_code}"
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
    findings = audit_trajectory(stdout)
    scratch_paths = _untracked_root_scratch_paths(repo_dir)
    patch = _repair_patch(
        _clean_patch(
            _strip_build_artifact_diff_blocks(
                _capture_patch(repo_dir), scratch_paths=scratch_paths
            )
        )
    )
    # _capture_patch first marks untracked files with intent-to-add, ensuring
    # scope validation cannot overlook a newly created production file.
    changed_paths, disallowed_paths = audit_patch_paths(
        repo_dir, scratch_paths=scratch_paths
    )

    if findings:
        error = "attempted_network"
    elif disallowed_paths:
        error = "disallowed_patch_scope"
    # A timeout, failed Codex process, network/tool attempt, or scope violation is
    # a finalized empty prediction. Partial patches are retained only in the
    # isolated checkout/trajectory evidence and are never scored.
    if error:
        patch = ""

    audit = {
        "status": "failed" if error else "passed",
        "network_isolation": "codex_workspace_write_network_disabled",
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
        "agent_backend": "codex",
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

    private_root = inference_worktree_root("codex-offline-pilot")
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
                    "tool_network": "disabled",
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
    parser.add_argument("--excel", type=Path, default=Path("Issues_No_Tests_split.xlsx"))
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
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
    if args.model != MODEL:
        raise SystemExit(f"formal pilot requires --model {MODEL}")
    if args.timeout > TIMEOUT or args.timeout <= 0:
        raise SystemExit(f"timeout must be in 1..{TIMEOUT}")
    if args.workers < 1 or args.workers > len(PILOT_CASES):
        raise SystemExit(f"workers must be in 1..{len(PILOT_CASES)}")
    instances = select_pilot_instances(args.excel, args.instances)
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
