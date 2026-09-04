#!/usr/bin/env python3
"""Run a native Codex CLI blind implementation in an OS-isolated workspace."""

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
TASK = ROOT / "scibench_replication_0017_core"
DESTINATION = ROOT / "core_algorithm_audits/0017_core_g7_submission"


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def file_map(root: Path) -> dict[str, str]: return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def tree_hash(root: Path) -> str:
    return hashlib.sha256(json.dumps(file_map(root), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--model", default="gpt-5.6-sol"); parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    if DESTINATION.exists(): raise RuntimeError("refusing to overwrite existing blind submission")
    prompt = (
        "Act as the blind implementation agent for this scientific benchmark. You may use only this directory, which contains the final public bundle; no repository, curator code, hidden cases, or network research is permitted. "
        "Infer the required method from public/paper.pdf and the public numeric I/O. Implement the general solution in solution.py only. "
        "The generic evaluator runs `python solution.py --input INPUT_JSON --output OUTPUT_DIRECTORY`; write OUTPUT_DIRECTORY/output.json. "
        "The output JSON must reproduce every key, identifier array, numeric array, ordering, and length visible in the public outputs; test the complete JSON with the benchmark comparator, not a single selected field. "
        "At evaluation time the public data directory is copied per case and exposed via SCIBENCH_PUBLIC_DATA_DIR. Standard Python, NumPy, pandas, and SciPy are available. "
        "You may inspect and test against public cases. Do not hard-code public outputs. Finish only after solution.py passes all public cases."
    )
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="scibench_0017_core_codex_g7_", dir="/tmp") as temporary:
        stage = Path(temporary); workspace = stage / "workspace"; workspace.mkdir()
        shutil.copytree(TASK / "public", workspace / "public")
        profile = stage / "profile.sb"
        profile.write_text('(version 1)\n(allow default)\n' + f'(deny file-read* (subpath "{ROOT.parent}"))\n', encoding="utf-8")
        events = stage / "events.jsonl"; final = stage / "final.txt"
        command = ["/usr/bin/sandbox-exec", "-f", str(profile), "codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "-m", args.model, "-c", 'model_reasoning_effort="high"', "-C", str(workspace), "--json", "-o", str(final), prompt]
        completed = subprocess.run(command, cwd=workspace, timeout=args.timeout, capture_output=True, text=True)
        events.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0: raise RuntimeError(f"Codex G7 failed: {completed.stderr[-2000:]}")
        solution = workspace / "solution.py"
        if not solution.is_file() or not solution.read_text(encoding="utf-8").strip(): raise RuntimeError("Codex did not create solution.py")
        # Hidden data enters the temporary workspace only after the agent exits.
        benchmark = stage / "benchmark"; staged_task = benchmark / TASK.name; shutil.copytree(TASK, staged_task)
        provenance_path = staged_task / "hidden/provenance.json"; provenance = json.loads(provenance_path.read_text()); provenance["lifecycle"] = "validated"; provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        benchmark.mkdir(exist_ok=True)
        (benchmark / "manifest.json").write_text(json.dumps({"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6}, "tasks": [{"task_id": TASK.name, "lifecycle": "validated", "public_files": file_map(staged_task / "public"), "hidden_files": file_map(staged_task / "hidden")}]}))
        submission = stage / "submission"; submission.mkdir(); shutil.copyfile(solution, submission / "solution.py")
        (submission / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK.name, "entrypoint": [sys.executable, "solution.py"]}))
        sys.path.insert(0, str(ROOT)); from run_submission import execute
        execution_path = stage / "execution.json"; execution = execute(submission, staged_task, execution_path, 120.0); execution_path.write_text(json.dumps(execution))
        from evaluation.framework import evaluate
        score = evaluate(staged_task, execution_path)
        event_rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        usage = next((row.get("usage") for row in reversed(event_rows) if row.get("usage")), None)
        report = {"schema_version": 1, "task_id": TASK.name, "generated_at": datetime.now(timezone.utc).isoformat(), "G7": "PASS" if score["full_success"] else "FAIL", "model": args.model, "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(), "prompt": prompt, "prompt_sha256": prompt_hash, "public_bundle_sha256": tree_hash(TASK / "public"), "runner_sha256": sha(ROOT / "run_submission.py"), "solution_sha256": sha(solution), "usage": usage, "model_final_answer": final.read_text(encoding="utf-8")[:4000] if final.is_file() else "", "score": score["score"], "public_score": score["public_score"], "hidden_score": score["hidden_score"], "full_success": score["full_success"], "cases": [{"split": split, "case_id": row["case_id"], "exit_code": row["exit_code"], "timed_out": row["timed_out"]} for split, rows in execution["cases"].items() for row in rows], "isolation": {"agent_workspace": "temporary copy of final public bundle", "repository_reads": "denied by macOS sandbox-exec", "hidden_and_curator_data": "copied only after agent process exited", "codex_session": "ephemeral; user config and project rules ignored", "temporary_workspace_cleaned": True}, "environment": {"python": platform.python_version(), "platform": platform.platform()}, "failed_preflight_attempts": ["chat-completions attempt 1: evaluator manifest absent after generation", "chat-completions attempt 2: staged provenance remained candidate_revise", "chat-completions attempt 3: 30 read-tool-call limit", "chat-completions attempt 4: 100 read-tool-call limit"]}
        DESTINATION.mkdir(parents=True); shutil.copyfile(solution, DESTINATION / "solution.py")
        (DESTINATION / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK.name, "entrypoint": [sys.executable, "solution.py"]}, indent=2) + "\n")
        report_path = ROOT / "curation_reports/0017_core_g7.json"; temporary_report = report_path.with_suffix(".tmp"); temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n"); os.replace(temporary_report, report_path)
        if not score["full_success"]: raise RuntimeError(f"blind Codex submission failed: score={score['score']}")


if __name__ == "__main__": main()
