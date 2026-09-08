#!/usr/bin/env python3
"""Fail-closed promotion of 0022_core after all formal gates pass."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];TASK_ID="scibench_replication_0022_core";LEGACY="scibench_replication_0022"
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def atomic(path,text):
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle: handle.write(text)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)
def atomic_json(path,value): atomic(path,json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+"\n")


def main() -> None:
    validation=json.loads((ROOT/"curation_reports/0022_core_validation.json").read_text())
    g6=json.loads((ROOT/"core_algorithm_audits/0022_core_blind.json").read_text())
    g7=json.loads((ROOT/"curation_reports/0022_core_g7.json").read_text())
    oracle=json.loads((ROOT/"curation_reports/0022_core_oracle.json").read_text())
    if validation.get("status")!="ACCEPT" or not all(validation.get("gates",{}).values()) or g6.get("G6")!="PASS" or g6.get("pass_count",0)<2 or g7.get("G7")!="PASS" or oracle.get("G8")!="PASS": raise RuntimeError("G1-G8 are not all passing")
    baseline=json.loads((ROOT/"curation_reports/0022_legacy_preservation.json").read_text())
    if files(ROOT/LEGACY)!=baseline["preserved_files"]: raise RuntimeError("legacy 0022 bytes changed")
    hashes=oracle["provenance"];four=[hashes["official_adapter_sha256"],hashes["independent_implementation_sha256"],hashes["curator_reference_sha256"],hashes["blind_submission_sha256"]]
    if any(not value for value in four) or len(set(four))!=4: raise RuntimeError("four-way implementation provenance is absent or not distinct")
    task=ROOT/TASK_ID;provenance_path=task/"hidden/provenance.json";provenance=json.loads(provenance_path.read_text());provenance["lifecycle"]="validated";provenance["gold_source"]="pinned_official_checkout";provenance["g6_audit"]={"path":"core_algorithm_audits/0022_core_blind.json","model_selection":g6["model_selection"],"configured_model":g6["configured_model"],"pass_count":g6["pass_count"],"independent_contexts":g6["independent_contexts_required"]};provenance["g7_audit"]={"path":"curation_reports/0022_core_g7.json","model":g7["model"],"score":g7["score"],"submission_sha256":g7["solution_sha256"]};atomic_json(provenance_path,provenance)
    manifest_path=ROOT/"manifest.json";manifest=json.loads(manifest_path.read_text())
    if any(row["task_id"]==TASK_ID for row in manifest["tasks"]): raise RuntimeError("task already present in manifest")
    manifest["tasks"].append({"task_id":TASK_ID,"lifecycle":"validated","public_files":files(task/"public"),"hidden_files":files(task/"hidden")})
    registry_path=ROOT/"task_registry.py";registry=registry_path.read_text();marker="}\n\nCANDIDATE_REGISTRY = {}"
    if marker not in registry or TASK_ID in registry: raise RuntimeError("unexpected registry state")
    row=(f'    "{TASK_ID}": {{"status": "validated", "repository": "https://github.com/simunec/sketch-select-arnoldi", "commit": "6e145837e4696bd9e26b3d6160b37f97e4188e10", "environment_file": None, "curator_environment_file": "curation_tools/environments/0022-octave-environment.yml", "adapter_path": "curation_tools/ssarnoldi_core_adapter.py", "adapter_output_is_directory": True, "official_adapter": "pinned paper_ssa_final_test1a.m sketch-and-select pinv recurrence adapted only for explicit dense numeric inputs", "functional_target": "canonical pseudoinverse sketch-and-select Arnoldi basis construction with sparse coefficient support and sketch-norm normalization"}},\n')
    registry=registry.replace(marker,row+marker)
    papers_path=ROOT/"papers.json";papers=json.loads(papers_path.read_text());matches=[row for row in papers["papers"] if row.get("github_url")=="https://github.com/simunec/sketch-select-arnoldi"]
    if len(matches)!=1 or matches[0].get("task_id") is not None: raise RuntimeError("unexpected papers entry")
    matches[0]["task_id"]=TASK_ID;matches[0]["build_status"]="validated";papers["updated_at"]=str(date.today())
    atomic(registry_path,registry);atomic_json(papers_path,papers);atomic_json(manifest_path,manifest)
    print(f"promoted {TASK_ID}; legacy draft remains byte-preserved")


if __name__=="__main__":main()
