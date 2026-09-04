#!/usr/bin/env python3
"""Generate a G7 submission in one fresh public-only model context and test it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sobiEquity_core_blind_common import read_env, run_context

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0017_core"
DESTINATION = ROOT / "core_algorithm_audits/0017_core_g7_submission"
WRITE_TOOL = {"type": "function", "function": {"name": "write_solution", "description": "Write the complete generated solution.py submission. This is the only writable path.", "parameters": {"type": "object", "properties": {"source": {"type": "string", "minLength": 1}}, "required": ["source"], "additionalProperties": False}}}


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode()); digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def file_map(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--env-file", type=Path, default=Path(".env")); parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if DESTINATION.exists(): raise RuntimeError("refusing to overwrite an existing blind submission")
    env = read_env(args.env_file); public = TASK / "public"
    with tempfile.TemporaryDirectory(prefix="scibench_0017_core_g7_generation_", dir="/tmp") as temporary:
        stage = Path(temporary); paper_path = stage / "paper.txt"; solution_path = stage / "solution.py"
        subprocess.run(["pdftotext", str(public / "paper.pdf"), str(paper_path)], check=True, timeout=120)
        prompt = ("You are the blind implementation agent for a scientific benchmark. Work only from the complete paper below, the final read-only public bundle exposed by tools, and this generic harness contract. "
                  "Infer the required scientific method and produce a complete solution.py by calling write_solution. The evaluator invokes `python solution.py --input INPUT_JSON --output OUTPUT_DIRECTORY`; your program must write OUTPUT_DIRECTORY/output.json. "
                  "Public data files are copied into a per-case read-only directory whose path is in SCIBENCH_PUBLIC_DATA_DIR. Only standard Python plus numpy/pandas/scipy may be assumed. "
                  "Do not use network access, repositories, curator code, hidden cases, or hard-coded public outputs. Inspect public examples and data as needed, then implement the general method.\n\nCOMPLETE PAPER TEXT\n" + paper_path.read_text(encoding="utf-8"))
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest(); writes = 0
        def write_handler(name: str, arguments: str) -> str:
            nonlocal writes
            if name != "write_solution": raise RuntimeError(f"unexpected tool {name}")
            source = json.loads(arguments)["source"]
            if len(source.encode()) > 1024 * 1024: raise ValueError("solution exceeds 1 MiB")
            solution_path.write_text(source, encoding="utf-8"); writes += 1
            return json.dumps({"written": "solution.py", "sha256": hashlib.sha256(source.encode()).hexdigest()})
        answer, actual_model = run_context(env, prompt, public, args.timeout, [WRITE_TOOL], write_handler)
        if writes == 0 or not solution_path.is_file(): raise RuntimeError("blind agent did not write solution.py")
        source_hash = hashlib.sha256(solution_path.read_bytes()).hexdigest()
        submission = stage / "submission"; submission.mkdir(); shutil.copyfile(solution_path, submission / "solution.py")
        (submission / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK.name, "entrypoint": [sys.executable, "solution.py"]}))
        benchmark = stage / "benchmark"; benchmark.mkdir(); staged_task = benchmark / TASK.name
        shutil.copytree(TASK, staged_task)
        staged_provenance_path = staged_task / "hidden/provenance.json"
        staged_provenance = json.loads(staged_provenance_path.read_text()); staged_provenance["lifecycle"] = "validated"
        staged_provenance_path.write_text(json.dumps(staged_provenance, indent=2, sort_keys=True) + "\n")
        (benchmark / "manifest.json").write_text(json.dumps({"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6}, "tasks": [{"task_id": TASK.name, "lifecycle": "validated", "public_files": file_map(staged_task / "public"), "hidden_files": file_map(staged_task / "hidden")}]}))
        report_path = stage / "execution.json"
        sys.path.insert(0, str(ROOT)); from run_submission import execute
        execution = execute(submission, staged_task, report_path, 120.0); report_path.write_text(json.dumps(execution))
        from evaluation.framework import evaluate
        score = evaluate(staged_task, report_path)
        cases = [{"split": split, "case_id": row["case_id"], "exit_code": row["exit_code"], "timed_out": row["timed_out"]} for split, rows in execution["cases"].items() for row in rows]
        artifact = {"schema_version": 1, "task_id": TASK.name, "generated_at": datetime.now(timezone.utc).isoformat(), "G7": "PASS" if score["full_success"] else "FAIL", "configured_model": env["MODEL_NAME"], "actual_model": actual_model, "independent_contexts": 1, "prompt": prompt, "prompt_sha256": prompt_hash, "public_bundle_sha256": hash_tree(public), "runner_sha256": hashlib.sha256((ROOT / "run_submission.py").read_bytes()).hexdigest(), "solution_sha256": source_hash, "model_final_answer": answer[:4000], "score": score["score"], "public_score": score["public_score"], "hidden_score": score["hidden_score"], "full_success": score["full_success"], "cases": cases, "isolation": {"generation_reads": "path-confined final public bundle only", "generation_writes": "solution.py only", "evaluation_network": "not used; evaluator subprocess receives only copied public data and case input", "official_repository": "not exposed", "curation_and_hidden_data": "not exposed during generation", "temporary_workspace_cleaned": True}, "redaction": "credentials, endpoint, provider IDs, and raw envelopes not retained"}
        DESTINATION.mkdir(parents=True); shutil.copyfile(solution_path, DESTINATION / "solution.py")
        (DESTINATION / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK.name, "entrypoint": [sys.executable, "solution.py"]}, indent=2) + "\n")
        destination_report = ROOT / "curation_reports/0017_core_g7.json"; temporary_report = destination_report.with_suffix(".tmp")
        temporary_report.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n"); os.replace(temporary_report, destination_report)
        if not score["full_success"]: raise RuntimeError(f"G7 blind submission failed: score={score['score']}")


if __name__ == "__main__": main()
