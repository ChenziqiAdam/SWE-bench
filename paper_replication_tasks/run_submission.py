#!/usr/bin/env python3
"""Execute one submission independently for every public and hidden v4 case."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _submission(path: Path, task_id: str) -> list[str]:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("submission.json is too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "task_id", "entrypoint"}:
        raise ValueError("submission.json fields are invalid")
    if value["schema_version"] != 4 or value["task_id"] != task_id:
        raise ValueError("submission schema/task mismatch")
    command = value["entrypoint"]
    if isinstance(command, str):
        command = shlex.split(command)
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("entrypoint must be a non-empty string or string array")
    return command


def _safe_output(root: Path, output: Path) -> bool:
    cursor = root
    try:
        relative = output.relative_to(root)
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                return False
        output.resolve(strict=True).relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return output.is_file()


def execute(submission_dir: Path, task_dir: Path, report_path: Path, timeout: float) -> dict[str, Any]:
    submission_dir = submission_dir.resolve()
    task_dir = task_dir.resolve()
    report_path = report_path.resolve()
    try:
        report_path.relative_to(submission_dir)
    except ValueError:
        pass
    else:
        raise ValueError("trusted report must be outside the submission directory")
    command = _submission(submission_dir / "submission.json", task_dir.name)
    output_root = report_path.parent / f"{report_path.stem}_case_outputs"
    if output_root.exists():
        raise ValueError(f"trusted output root already exists: {output_root}")
    output_root.mkdir(parents=True)
    rows: dict[str, list[dict[str, Any]]] = {"public": [], "hidden": []}
    for split in rows:
        for case_dir in sorted(path for path in (task_dir / split / "cases").iterdir() if path.is_dir()):
            output_dir = output_root / split / case_dir.name
            output_dir.mkdir(parents=True)
            with tempfile.TemporaryDirectory(prefix="scibench_case_") as temporary:
                isolated_input = Path(temporary) / "input.json"
                shutil.copyfile(case_dir / "input.json", isolated_input)
                started = time.monotonic()
                timed_out = False
                try:
                    completed = subprocess.run(
                        [*command, "--input", str(isolated_input), "--output", str(output_dir)],
                        cwd=submission_dir,
                        env={**os.environ, "SCIBENCH_TASK_ID": task_dir.name, "SCIBENCH_CASE_ID": case_dir.name},
                        shell=False,
                        timeout=timeout,
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    exit_code = completed.returncode
                except subprocess.TimeoutExpired:
                    exit_code, timed_out = 124, True
                wall = time.monotonic() - started
            output = output_dir / "output.json"
            safe_output = _safe_output(output_root, output)
            rows[split].append({
                "case_id": case_dir.name,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "wall_seconds": wall,
                "output_dir": output_dir.relative_to(report_path.parent).as_posix(),
                "output_sha256": _hash(output) if safe_output else None,
            })
    return {"schema_version": 4, "task_id": task_dir.name, "entrypoint": command, "cases": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("timeout must be positive")
    try:
        result = execute(args.submission_dir, args.task_dir, args.output, args.timeout_seconds)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
