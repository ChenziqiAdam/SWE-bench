#!/usr/bin/env python3
"""Fresh public-only Codex G7 generation followed by offline hidden scoring."""

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

ROOT=Path(__file__).resolve().parents[1];TASK=ROOT/"scibench_replication_0022_core";DEST=ROOT/"core_algorithm_audits/0022_core_g7_submission"
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def tree_hash(root): return hashlib.sha256(json.dumps(files(root),sort_keys=True,separators=(",",":")).encode()).hexdigest()


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--model",default="gpt-5.6-sol");parser.add_argument("--timeout",type=float,default=1800);args=parser.parse_args()
    if DEST.exists(): raise RuntimeError("refusing to overwrite blind submission")
    prompt=("Act as the blind implementation agent for this scientific benchmark. You may use only this directory containing the final public bundle; no repository, curator code, hidden cases, prior responses, or network research is permitted. Infer the required method from public/paper.pdf and public numeric I/O. Implement the general solution in solution.py only. The evaluator runs `python solution.py --input INPUT_JSON --output OUTPUT_DIRECTORY`; write OUTPUT_DIRECTORY/output.json. Reproduce every output key, numeric array, ordering, and shape. NumPy and SciPy are available. Inspect and test all public cases; do not hard-code outputs.")
    prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="0022_core_g7_",dir="/tmp") as temporary:
        stage=Path(temporary);workspace=stage/"workspace";workspace.mkdir();shutil.copytree(TASK/"public",workspace/"public")
        profile=stage/"profile.sb";profile.write_text('(version 1)\n(allow default)\n'+f'(deny file-read* (subpath "{ROOT.parent}"))\n')
        final=stage/"final.txt";command=["/usr/bin/sandbox-exec","-f",str(profile),"codex","exec","--ephemeral","--ignore-user-config","--ignore-rules","--skip-git-repo-check","--dangerously-bypass-approvals-and-sandbox","-m",args.model,"-c",'model_reasoning_effort="high"',"-C",str(workspace),"--json","-o",str(final),prompt]
        completed=subprocess.run(command,cwd=workspace,timeout=args.timeout,capture_output=True,text=True)
        if completed.returncode!=0:
            reason="sandbox-exec unavailable" if "Operation not permitted" in completed.stderr else "blind agent process failed"
            report={"schema_version":1,"task_id":TASK.name,"generated_at":datetime.now(timezone.utc).isoformat(),"G7":"FAIL","model":args.model,"prompt":prompt,"prompt_sha256":prompt_hash,"public_bundle_sha256":tree_hash(TASK/"public"),"runner_sha256":sha(ROOT/"run_submission.py"),"solution_sha256":None,"score":0.0,"public_score":0.0,"hidden_score":0.0,"full_success":False,"blocker":reason,"sanitized_stderr":reason,"isolation":{"required":"OS-denied repository reads","established":False}}
            path=ROOT/"curation_reports/0022_core_g7.json";tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");os.replace(tmp,path)
            raise RuntimeError(f"Codex G7 failed: {reason}")
        solution=workspace/"solution.py"
        if not solution.is_file(): raise RuntimeError("blind agent did not create solution.py")
        benchmark=stage/"benchmark";staged=benchmark/TASK.name;shutil.copytree(TASK,staged)
        provenance=json.loads((staged/"hidden/provenance.json").read_text());provenance["lifecycle"]="validated";provenance["gold_source"]="pinned_official_checkout";(staged/"hidden/provenance.json").write_text(json.dumps(provenance))
        benchmark.mkdir(exist_ok=True);(benchmark/"manifest.json").write_text(json.dumps({"schema_version":4,"scoring":{"public_weight":.4,"hidden_weight":.6},"tasks":[{"task_id":TASK.name,"lifecycle":"validated","public_files":files(staged/"public"),"hidden_files":files(staged/"hidden")}]}))
        submission=stage/"submission";submission.mkdir();shutil.copyfile(solution,submission/"solution.py");(submission/"submission.json").write_text(json.dumps({"schema_version":4,"task_id":TASK.name,"entrypoint":[sys.executable,"solution.py"]}))
        sys.path.insert(0,str(ROOT));from run_submission import execute
        execution_path=stage/"execution.json";execution=execute(submission,staged,execution_path,120);execution_path.write_text(json.dumps(execution));from evaluation.framework import evaluate;score=evaluate(staged,execution_path)
        events=[json.loads(line) for line in completed.stdout.splitlines() if line.strip()];usage=next((row.get("usage") for row in reversed(events) if row.get("usage")),None)
        report={"schema_version":1,"task_id":TASK.name,"generated_at":datetime.now(timezone.utc).isoformat(),"G7":"PASS" if score["full_success"] else "FAIL","model":args.model,"codex_version":subprocess.check_output(["codex","--version"],text=True).strip(),"prompt":prompt,"prompt_sha256":prompt_hash,"public_bundle_sha256":tree_hash(TASK/"public"),"runner_sha256":sha(ROOT/"run_submission.py"),"solution_sha256":sha(solution),"usage":usage,"model_final_answer":final.read_text()[:4000] if final.is_file() else "","score":score["score"],"public_score":score["public_score"],"hidden_score":score["hidden_score"],"full_success":score["full_success"],"cases":score["checks"],"isolation":{"agent_workspace":"temporary final-public-bundle copy","repository_reads":"denied by sandbox-exec","hidden_data":"introduced only after agent exit","execution_network":"offline; solution receives only isolated input","network_research":"not requested or permitted","context":"fresh ephemeral"},"environment":{"python":platform.python_version(),"platform":platform.platform()}}
        DEST.mkdir(parents=True);shutil.copyfile(solution,DEST/"solution.py");(DEST/"submission.json").write_text(json.dumps({"schema_version":4,"task_id":TASK.name,"entrypoint":[sys.executable,"solution.py"]},indent=2)+"\n")
        path=ROOT/"curation_reports/0022_core_g7.json";tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");os.replace(tmp,path)
        if not score["full_success"]: raise RuntimeError(f"G7 failed: public={score['public_score']} hidden={score['hidden_score']}")


if __name__=="__main__":main()
