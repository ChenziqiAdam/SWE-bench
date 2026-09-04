#!/usr/bin/env python3
"""Run the 0018_core Codex blind implementation and hidden evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
DESTINATION = ROOT / "core_algorithm_audits/0018_core_g7_submission"
REPORT = ROOT / "curation_reports/0018_core_g7.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_map(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def tree_hash(root: Path) -> str:
    payload = json.dumps(file_map(root), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    if DESTINATION.exists():
        raise RuntimeError("refusing to overwrite existing blind submission")
    if REPORT.exists():
        previous = json.loads(REPORT.read_text())
        if previous.get("G7") == "PASS":
            raise RuntimeError("refusing to overwrite passing G7 evidence")
        failed = ROOT / "curation_reports/official_runs/0018_core/failed_g7"
        failed.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(REPORT.read_bytes()).hexdigest()[:12] + ".json"
        shutil.copyfile(REPORT, failed / name)
    prompt = (
        "Act as the blind implementation agent for this scientific benchmark. Use only this "
        "directory, which contains the final public bundle. Do not access the benchmark "
        "repository, curator code, hidden cases, prior conversations, or network research. "
        "Infer the complete paper method from public/paper.pdf and public numeric I/O, then "
        "implement the general solution in solution.py only. The evaluator runs `python "
        "solution.py --input INPUT_JSON --output OUTPUT_DIRECTORY`; write "
        "OUTPUT_DIRECTORY/output.json. Reproduce every output key, array, ordering, and length "
        "shown by public cases. Standard Python, NumPy, pandas, and SciPy are installed. You may "
        "run local tests against public cases. Do not hard-code case outputs. Finish only after "
        "all three public cases pass."
    )
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="scibench_0018_core_g7_", dir="/tmp") as temporary:
        stage = Path(temporary)
        workspace = stage / "workspace"
        workspace.mkdir()
        shutil.copytree(TASK / "public", workspace / "public")
        profile = stage / "profile.sb"
        profile.write_text(
            "(version 1)\n(allow default)\n"
            f'(deny file-read* (subpath "{ROOT}"))\n', encoding="utf-8")
        events = stage / "events.jsonl"
        final = stage / "final.txt"
        command = [
            "/usr/bin/sandbox-exec", "-f", str(profile), "codex", "exec",
            "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
            "-m", args.model, "-c", 'model_reasoning_effort="high"',
            "-C", str(workspace), "--json", "-o", str(final), prompt,
        ]
        completed = subprocess.run(command, cwd=workspace, timeout=args.timeout,
                                   capture_output=True, text=True)
        events.write_text(completed.stdout, encoding="utf-8")
        solution = workspace / "solution.py"
        if completed.returncode != 0 or not solution.is_file() or not solution.read_text().strip():
            failure = {
                "schema_version": 1, "task_id": TASK.name, "G7": "FAIL",
                "generated_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
                "prompt": prompt, "prompt_sha256": prompt_hash,
                "codex_exit_code": completed.returncode,
                "stderr_tail": completed.stderr[-2000:],
                "public_bundle_sha256": tree_hash(TASK / "public"),
            }
            REPORT.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n")
            raise RuntimeError("Codex did not produce solution.py")

        # Hidden data is copied only after the blind agent process has exited.
        benchmark = stage / "benchmark"
        staged_task = benchmark / TASK.name
        shutil.copytree(TASK, staged_task)
        provenance_path = staged_task / "hidden/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["lifecycle"] = "validated"
        provenance["gold_source"] = "pinned_official_checkout"
        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        (benchmark / "manifest.json").write_text(json.dumps({
            "schema_version": 4,
            "scoring": {"public_weight": .4, "hidden_weight": .6},
            "tasks": [{"task_id": TASK.name, "lifecycle": "validated",
                       "public_files": file_map(staged_task / "public"),
                       "hidden_files": file_map(staged_task / "hidden")}],
        }, indent=2, sort_keys=True) + "\n")
        submission = stage / "submission"
        submission.mkdir()
        shutil.copyfile(solution, submission / "solution.py")
        (submission / "submission.json").write_text(json.dumps({
            "schema_version": 4, "task_id": TASK.name,
            "entrypoint": [sys.executable, "solution.py"],
        }, indent=2, sort_keys=True) + "\n")
        sys.path.insert(0, str(ROOT))
        from run_submission import execute
        from evaluation.framework import evaluate
        execution_path = stage / "execution.json"
        execution = execute(submission, staged_task, execution_path, 600.0)
        execution_path.write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
        score = evaluate(staged_task, execution_path)
        event_rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        usage = next((row.get("usage") for row in reversed(event_rows) if row.get("usage")), None)
        report = {
            "schema_version": 1,
            "task_id": TASK.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "G7": "PASS" if score["full_success"] else "FAIL",
            "model": args.model,
            "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
            "prompt": prompt,
            "prompt_sha256": prompt_hash,
            "public_bundle_sha256": tree_hash(TASK / "public"),
            "runner_sha256": sha(ROOT / "run_submission.py"),
            "solution_sha256": sha(solution),
            "usage": usage,
            "model_final_answer": final.read_text(encoding="utf-8")[:4000] if final.is_file() else "",
            "score": score["score"], "public_score": score["public_score"],
            "hidden_score": score["hidden_score"], "full_success": score["full_success"],
            "cases": [{"split": split, "case_id": row["case_id"],
                       "exit_code": row["exit_code"], "timed_out": row["timed_out"],
                       "wall_seconds": row["wall_seconds"]}
                      for split, rows in execution["cases"].items() for row in rows],
            "isolation": {
                "agent_workspace": "temporary copy of final public bundle",
                "repository_reads": "denied by macOS sandbox-exec",
                "hidden_and_curator_data": "copied only after agent process exited",
                "codex_session": "ephemeral; user config and project rules ignored",
                "temporary_workspace_cleaned": True,
            },
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "redaction": "credentials, endpoint, provider/user/request IDs, and raw envelopes not retained",
        }
        DESTINATION.mkdir(parents=True)
        shutil.copyfile(solution, DESTINATION / "solution.py")
        shutil.copyfile(submission / "submission.json", DESTINATION / "submission.json")
        temporary_report = REPORT.with_suffix(".tmp")
        temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        os.replace(temporary_report, REPORT)
        if not score["full_success"]:
            raise RuntimeError(f"blind Codex submission failed: score={score['score']}")


if __name__ == "__main__":
    main()
