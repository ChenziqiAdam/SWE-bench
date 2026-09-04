#!/usr/bin/env python3
"""Generate and offline-test one fresh public-only 0011_core G7 submission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from sobiEquity_core_blind_common import read_env, run_context

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0011_core"
DESTINATION = ROOT / "core_algorithm_audits/0011_core_g7_submission"
WRITE_TOOL = {"type": "function", "function": {"name": "write_solution",
    "description": "Write the complete generated solution.py submission. This is the only writable path.",
    "parameters": {"type": "object", "properties": {"source": {"type": "string", "minLength": 1}},
                   "required": ["source"], "additionalProperties": False}}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_map(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def tree_hash(root: Path) -> str:
    return hashlib.sha256(json.dumps(file_map(root), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def generate(env: dict[str, str], prompt: str, public: Path, timeout: float, tools: list[dict], handler,
             written_path: Path):
    failures = []
    models = [env["MODEL_NAME"]]
    fallback = env.get("FALLBACK_MODEL_NAME")
    if fallback and fallback != models[0]:
        models.append(fallback)
    for model_index, model in enumerate(models):
        attempts = 1 if model_index == 0 and len(models) > 1 else 6
        for attempt in range(1, attempts + 1):
            try:
                answer, actual = run_context({**env, "MODEL_NAME": model}, prompt, public, timeout, tools, handler)
                return answer, model, actual, failures
            except RuntimeError as error:
                if str(error) == "model returned no final content" and written_path.is_file() and written_path.stat().st_size:
                    return "solution.py was written before the model returned an empty final response", model, model, failures
                if str(error) == "model returned no final content":
                    failures.append(f"model {model}: attempt {attempt}: empty_final")
                    final_attempt = model_index == len(models) - 1 and attempt == attempts
                    if not final_attempt:
                        if attempt < attempts:
                            time.sleep(min(5 * attempt, 30))
                        continue
                error.g7_requested_model = model
                error.g7_transient_failures = failures
                raise
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None
                if status != 429:
                    raise
                failures.append(f"model {model}: attempt {attempt}: upstream_429")
                if written_path.is_file() and written_path.stat().st_size:
                    return "solution.py was written before an upstream 429 ended the final response", model, model, failures
                if model_index == len(models) - 1 and attempt == attempts:
                    error.g7_requested_model = model
                    error.g7_transient_failures = failures
                    raise
                if attempt < attempts:
                    time.sleep(min(5 * attempt, 30))
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if DESTINATION.exists():
        raise RuntimeError("refusing to overwrite an existing blind submission")
    env = read_env(args.env_file); public = TASK / "public"
    with tempfile.TemporaryDirectory(prefix="scibench_0011_core_g7_", dir="/tmp") as temporary:
        stage = Path(temporary); paper_text = stage / "paper.txt"; solution_path = stage / "solution.py"
        subprocess.run(["pdftotext", str(public / "paper.pdf"), str(paper_text)], check=True, timeout=120)
        prompt = (
            "You are the blind implementation agent for a scientific benchmark. Work only from the complete paper below, "
            "the final read-only public bundle exposed by tools, and this generic harness contract. Infer the required scientific "
            "method and produce a complete solution.py by calling write_solution. The evaluator invokes "
            "`python solution.py --input INPUT_JSON --output OUTPUT_DIRECTORY`; your program must write "
            "OUTPUT_DIRECTORY/output.json. Only standard Python plus NumPy and SciPy may be assumed. Do not use network access, "
            "repositories, curator code, hidden cases, or hard-coded public outputs. Inspect all public numeric examples as needed, "
            "implement the general method, and ensure the complete output JSON schema matches the examples.\n\nCOMPLETE PAPER TEXT\n"
            + paper_text.read_text(encoding="utf-8"))
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest(); writes = 0

        def write_handler(name: str, arguments: str) -> str:
            nonlocal writes
            if name != "write_solution":
                raise RuntimeError(f"unexpected tool {name}")
            source = json.loads(arguments)["source"]
            if len(source.encode()) > 1024 * 1024:
                raise ValueError("solution exceeds 1 MiB")
            solution_path.write_text(source, encoding="utf-8"); writes += 1
            return json.dumps({"written": "solution.py", "sha256": hashlib.sha256(source.encode()).hexdigest()})

        try:
            answer, requested, actual, transient = generate(
                env, prompt, public, args.timeout, [WRITE_TOOL], write_handler, solution_path)
        except (requests.HTTPError, RuntimeError) as error:
            status = error.response.status_code if isinstance(error, requests.HTTPError) and error.response is not None else None
            blocked = {"schema_version": 1, "task_id": TASK.name,
                       "generated_at": datetime.now(timezone.utc).isoformat(), "G7": "BLOCKED",
                       "configured_model": env["MODEL_NAME"], "fallback_model": env.get("FALLBACK_MODEL_NAME"),
                       "requested_model_at_failure": getattr(error, "g7_requested_model", None),
                       "error_type": type(error).__name__,
                       "error_summary": str(error),
                       "http_status": status, "transient_failures": getattr(error, "g7_transient_failures", []),
                       "prompt": prompt, "prompt_sha256": prompt_hash, "public_bundle_sha256": tree_hash(public),
                       "runner_sha256": sha(ROOT / "run_submission.py"),
                       "generation_writes": writes,
                       "redaction": "credentials, endpoint, provider/request/response IDs, and raw envelopes not retained"}
            report_path = ROOT / "curation_reports/0011_core_g7.json"; report_tmp = report_path.with_suffix(".tmp")
            report_tmp.write_text(json.dumps(blocked, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            os.replace(report_tmp, report_path)
            raise RuntimeError(f"G7 externally blocked: {type(error).__name__}, HTTP {status}") from error
        if writes == 0 or not solution_path.is_file():
            raise RuntimeError("blind agent did not write solution.py")

        benchmark = stage / "benchmark"; staged_task = benchmark / TASK.name; shutil.copytree(TASK, staged_task)
        provenance_path = staged_task / "hidden/provenance.json"; provenance = json.loads(provenance_path.read_text())
        provenance["lifecycle"] = "validated"; provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        write_manifest = {"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6},
                          "tasks": [{"task_id": TASK.name, "lifecycle": "validated",
                                     "public_files": file_map(staged_task / "public"),
                                     "hidden_files": file_map(staged_task / "hidden")} ]}
        (benchmark / "manifest.json").write_text(json.dumps(write_manifest, indent=2, sort_keys=True) + "\n")

        profile = stage / "offline.sb"
        profile.write_text('(version 1)\n(allow default)\n(deny network*)\n' +
                           f'(deny file-read* (subpath "{ROOT.parent}"))\n', encoding="utf-8")
        submission = stage / "submission"; submission.mkdir(); shutil.copyfile(solution_path, submission / "solution.py")
        entrypoint = ["/usr/bin/sandbox-exec", "-f", str(profile), sys.executable, "solution.py"]
        (submission / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK.name,
                                                                  "entrypoint": entrypoint}))
        sys.path.insert(0, str(ROOT)); from run_submission import execute
        execution_path = stage / "execution.json"; execution = execute(submission, staged_task, execution_path, 120.0)
        execution_path.write_text(json.dumps(execution))
        from evaluation.framework import evaluate
        score = evaluate(staged_task, execution_path)
        checks = [{"id": row["id"], "passed": row["passed"], "diagnostics": row["diagnostics"]}
                  for row in score["checks"]]
        report = {"schema_version": 1, "task_id": TASK.name, "generated_at": datetime.now(timezone.utc).isoformat(),
                  "G7": "PASS" if score["full_success"] else "FAIL", "configured_model": env["MODEL_NAME"],
                  "fallback_model": env.get("FALLBACK_MODEL_NAME"), "requested_model": requested, "actual_model": actual,
                  "independent_contexts": 1, "prompt": prompt, "prompt_sha256": prompt_hash,
                  "public_bundle_sha256": tree_hash(public), "runner_sha256": sha(ROOT / "run_submission.py"),
                  "solution_sha256": sha(solution_path), "model_final_answer": answer[:4000],
                  "transient_failures": transient, "score": score["score"], "public_score": score["public_score"],
                  "hidden_score": score["hidden_score"], "full_success": score["full_success"], "checks": checks,
                  "isolation": {"generation_reads": "path-confined final public bundle only",
                      "generation_writes": "solution.py only", "evaluation_network": "denied by macOS sandbox-exec",
                      "evaluation_repository_reads": "denied by macOS sandbox-exec",
                      "official_repository": "not exposed", "curation_and_hidden_data": "not exposed during generation",
                      "temporary_workspace_cleaned": True},
                  "redaction": "credentials, endpoint, provider/request/response IDs, and raw envelopes not retained"}
        DESTINATION.mkdir(parents=True); shutil.copyfile(solution_path, DESTINATION / "solution.py")
        (DESTINATION / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK.name,
                                                                  "entrypoint": [sys.executable, "solution.py"]}, indent=2) + "\n")
        report_path = ROOT / "curation_reports/0011_core_g7.json"; report_tmp = report_path.with_suffix(".tmp")
        report_tmp.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"); os.replace(report_tmp, report_path)
        if not score["full_success"]:
            raise RuntimeError(f"G7 blind submission failed: score={score['score']}")


if __name__ == "__main__":
    main()
