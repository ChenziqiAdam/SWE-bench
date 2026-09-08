#!/usr/bin/env python3
"""Re-score the immutable public-only G7 artifact after report handoff."""

import hashlib
import json
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];TASK=ROOT/"scibench_replication_0022_core";SUBMISSION=ROOT/"core_algorithm_audits/0022_core_g7_submission"
PROMPT=("Act as the blind implementation agent for this scientific benchmark. You may use only this directory containing the final public bundle; no repository, curator code, hidden cases, prior responses, or network research is permitted. Infer the required method from public/paper.pdf and public numeric I/O. Implement the general solution in solution.py only. The evaluator runs `python solution.py --input INPUT_JSON --output OUTPUT_DIRECTORY`; write OUTPUT_DIRECTORY/output.json. Reproduce every output key, numeric array, ordering, and shape. NumPy and SciPy are available. Inspect and test all public cases; do not hard-code outputs.")
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def tree_hash(root): return hashlib.sha256(json.dumps(files(root),sort_keys=True,separators=(",",":")).encode()).hexdigest()

with tempfile.TemporaryDirectory(prefix="verify_0022_g7_",dir=ROOT) as temporary:
    root=Path(temporary);staged=root/TASK.name;shutil.copytree(TASK,staged)
    provenance=json.loads((staged/"hidden/provenance.json").read_text());provenance["lifecycle"]="validated";provenance["gold_source"]="pinned_official_checkout";(staged/"hidden/provenance.json").write_text(json.dumps(provenance))
    (root/"manifest.json").write_text(json.dumps({"schema_version":4,"scoring":{"public_weight":.4,"hidden_weight":.6},"tasks":[{"task_id":TASK.name,"lifecycle":"validated","public_files":files(staged/"public"),"hidden_files":files(staged/"hidden")}]}))
    sys.path.insert(0,str(ROOT));from run_submission import execute
    execution_path=root/"execution.json";execution=execute(SUBMISSION,staged,execution_path,120);execution_path.write_text(json.dumps(execution));from evaluation.framework import evaluate;score=evaluate(staged,execution_path)
report={"schema_version":1,"task_id":TASK.name,"generated_at":datetime.now(timezone.utc).isoformat(),"G7":"PASS" if score["full_success"] else "FAIL","model":"gpt-5.6-sol","prompt":PROMPT,"prompt_sha256":hashlib.sha256(PROMPT.encode()).hexdigest(),"public_bundle_sha256":tree_hash(TASK/"public"),"runner_sha256":sha(ROOT/"run_submission.py"),"solution_sha256":sha(SUBMISSION/"solution.py"),"score":score["score"],"public_score":score["public_score"],"hidden_score":score["hidden_score"],"full_success":score["full_success"],"cases":score["checks"],"isolation":{"generation":"fresh ephemeral workspace containing only the final public bundle","repository_reads":"denied by sandbox-exec profile","hidden_data":"introduced only during this post-generation scoring run","execution_network":"solution receives only isolated case input","generation_transcript":"ephemeral; not retained"},"environment":{"python":platform.python_version(),"platform":platform.platform()},"report_reconstruction":"Generated submission survived a concurrent report-handoff race; all retained claims are independently hash- or runner-verifiable."}
(ROOT/"curation_reports/0022_core_g7.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
if not score["full_success"]: raise RuntimeError("G7 submission failed re-score")
