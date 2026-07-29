#!/usr/bin/env python3
"""Trusted runner-side execution manifest generator.

Run this program outside the agent-writable workspace and inside the benchmark's
offline OS/container sandbox. It deliberately does not attempt to implement a
security sandbox itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


CHUNK_SIZE = 8 * 1024 * 1024
MAX_RESULTS_BYTES = 2 * 1024 * 1024


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def relative_regular_files(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        hashes[relative] = sha256_file(path)
    return hashes


def safe_artifact_path(root: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        return None
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        return None
    candidate = root.joinpath(*posix.parts)
    current = root
    for part in posix.parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return candidate


def read_artifact_index(root: Path) -> list[dict[str, Any]]:
    results = root / "results.json"
    try:
        if results.stat().st_size > MAX_RESULTS_BYTES:
            return []
        value = json.loads(results.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = value.get("artifacts") if isinstance(value, dict) else None
    return rows if isinstance(rows, list) else []


def execute(
    root: Path,
    task_id: str,
    command: list[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    root = root.resolve()
    before = relative_regular_files(root)
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall_start = time.monotonic()
    started_at = timestamp()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
    ended_at = timestamp()
    wall_seconds = time.monotonic() - wall_start
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    after = relative_regular_files(root)
    artifacts = {}
    for row in read_artifact_index(root):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        path = safe_artifact_path(root, row.get("path"))
        if path is None or not path.is_file():
            continue
        artifacts[row["id"]] = {
            "path": row["path"],
            "sha256": sha256_file(path),
        }
    peak = usage_after.ru_maxrss
    if sys.platform.startswith("linux"):
        peak *= 1024
    return {
        "schema_version": 1,
        "task_id": task_id,
        "attempt_id": str(uuid.uuid4()),
        "command": shlex.join(command),
        "cwd": ".",
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": exit_code,
        "before_files": before,
        "after_files": after,
        "artifacts": artifacts,
        "resource_usage": {
            "cpu_seconds": max(
                0.0,
                (usage_after.ru_utime + usage_after.ru_stime)
                - (usage_before.ru_utime + usage_before.ru_stime),
            ),
            "wall_seconds": wall_seconds,
            "peak_memory_bytes": int(max(0, peak)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=86400)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = args.submission_dir.resolve()
    output = args.output.resolve()
    if not root.is_dir():
        parser.error("submission directory does not exist")
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        parser.error("--output must be outside the agent-writable submission directory")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("an execution command is required after --")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    report = execute(root, args.task_id, command, args.timeout_seconds)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
