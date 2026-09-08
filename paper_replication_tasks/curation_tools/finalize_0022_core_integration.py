#!/usr/bin/env python3
"""Refresh promoted 0022_core provenance and manifest hashes atomically."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];TASK_ID="scibench_replication_0022_core"
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def atomic_json(path,value):
    fd,name=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle: handle.write(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+"\n")
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

task=ROOT/TASK_ID;provenance_path=task/"hidden/provenance.json";provenance=json.loads(provenance_path.read_text())
adapter_hash=sha(ROOT/"curation_tools/ssarnoldi_core_adapter.py");environment_hash=sha(ROOT/"curation_tools/environments/0022-octave-environment.yml");run_hashes=provenance["official_reproduction"]["run_hashes"]
provenance["official_adapter_sha256"]=adapter_hash;provenance["construction_script_sha256"]=sha(ROOT/"curation_tools/build_ssarnoldi_core_task.py");provenance["dependency_artifact_sha256"]=None
provenance["official_reproduction"].update({"adapter_sha256":adapter_hash,"environment_lock_sha256":environment_hash,"dependency_artifact_sha256":None,"clean_checkout_bundle_sha256":run_hashes,"raw_and_normalized_outputs":"curation_reports/official_runs/0022_core"})
provenance["independent_audit"]["derived_tolerances"]=json.loads((task/"hidden/tolerances.json").read_text())
atomic_json(provenance_path,provenance)
oracle_path=ROOT/"curation_reports/0022_core_oracle.json";oracle=json.loads(oracle_path.read_text());oracle["provenance"]=provenance;atomic_json(oracle_path,oracle)
manifest_path=ROOT/"manifest.json";manifest=json.loads(manifest_path.read_text());rows=[row for row in manifest["tasks"] if row["task_id"]==TASK_ID]
if len(rows)!=1: raise RuntimeError("promoted manifest row missing or duplicated")
rows[0]["public_files"]=files(task/"public");rows[0]["hidden_files"]=files(task/"hidden");atomic_json(manifest_path,manifest)
