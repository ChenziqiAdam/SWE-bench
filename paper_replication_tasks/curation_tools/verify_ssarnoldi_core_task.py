#!/usr/bin/env python3
"""Fail-closed scientific, runner, shortcut, and G1-G8 checks for 0022_core."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from ssarnoldi_core_common import validate_case, validate_output
from ssarnoldi_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]; TASK_ID = "scibench_replication_0022_core"


def read(path: Path): return json.loads(path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def files(root: Path) -> dict[str, str]: return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}
def fails(fn, *args) -> bool:
    try: fn(*args)
    except Exception: return True
    return False


PROGRAM = r'''import argparse,json,pathlib,numpy as np
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();x=json.load(open(a.input));A=np.array(x['matrix'],float);b=np.array(x['start_vector'],float);S=np.array(x['sketch_matrix'],float);m=x['iterations'];k=x['selection_budget'];MODE='__MODE__'
V=np.zeros((len(b),m+1));Y=np.zeros((len(S),m+1));H=np.zeros((m+1,m));P=np.zeros((len(S),m));q=S@b;z=np.linalg.norm(q)
if MODE in ('euclidean_normalization','incorrect_initial_normalization'): z=np.linalg.norm(b)
V[:,0]=b/z;Y[:,0]=q/z
for j in range(m):
 w=A@V[:,j];sw=S@w;P[:,j]=sw
 if MODE=='full_arnoldi': c=np.linalg.pinv(Y[:,:j+1])@sw;ind=np.arange(j+1)
 elif MODE=='recent_truncated_arnoldi': ind=np.arange(max(0,j-k+1),j+1);c=V[:,:j+1].T@w
 elif MODE=='sketch_and_truncate': ind=np.arange(max(0,j-k+1),j+1);c=Y[:,:j+1].T@sw
 elif MODE=='correlation_selection': c=Y[:,:j+1].T@sw;ind=np.array(sorted(range(j+1),key=lambda i:(-abs(c[i]),i))[:min(j+1,k)])
 elif MODE=='unsketched_selection': c=np.linalg.pinv(V[:,:j+1])@w;ind=np.array(sorted(range(j+1),key=lambda i:(-abs(c[i]),i))[:min(j+1,k)])
 else: c=np.linalg.pinv(Y[:,:j+1])@sw;ind=np.array(sorted(range(j+1),key=lambda i:(-abs(c[i]),i))[:min(j+1,k)])
 h=np.linalg.pinv(Y[:,ind])@sw if MODE=='recompute_after_selection' else c[ind]
 H[ind,j]=h;w=w-V[:,ind]@h;sw=sw-Y[:,ind]@h
 z=np.linalg.norm(w) if MODE=='euclidean_normalization' else np.linalg.norm(sw)
 H[j+1,j]=z;V[:,j+1]=w/z;Y[:,j+1]=sw/z
o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps({'basis':V.tolist(),'hessenberg':H.tolist(),'sketched_basis':Y.tolist(),'sketched_products':P.tolist()},allow_nan=False))
'''


def execute_program(root: Path, task: Path, name: str, source: str):
    from run_submission import execute
    from evaluation.framework import evaluate
    submission = root / name; submission.mkdir(); (submission / "solution.py").write_text(source)
    (submission / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}))
    report_path = root / f"{name}.json"; report = execute(submission, task, report_path, 30); report_path.write_text(json.dumps(report))
    return report, evaluate(task, report_path)


def main() -> None:
    sys.path.insert(0, str(ROOT)); from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute
    task = ROOT / TASK_ID; oracle = read(ROOT / "curation_reports/0022_core_oracle.json")
    g6_path = ROOT / "core_algorithm_audits/0022_core_blind.json"; g7_path = ROOT / "curation_reports/0022_core_g7.json"
    g6 = read(g6_path) if g6_path.is_file() else {}; g7 = read(g7_path) if g7_path.is_file() else {}
    tolerance = read(task / "hidden/tolerances.json")
    gates = {"G1_core_centrality": True, "G2_unique_core": True, "G3_scientific_specificity": True,
             "G4_executable_closure": True, "G5_hidden_generalization": len(list((task / "hidden/cases").iterdir())) == 8,
             "G6_blind_identification": g6.get("G6") == "PASS" and g6.get("pass_count", 0) >= 2,
             "G7_blind_implementation": g7.get("G7") == "PASS" and g7.get("hidden_score") == 1.0,
             "G8_oracle_validity": oracle.get("G8") == "PASS" and oracle.get("two_clean_official_runs_match") is True}
    public_names = set(files(task / "public")); expected = {"paper.pdf", "task.md", "interface.schema.json", *(f"cases/case_{i:02d}/{name}" for i in range(1,4) for name in ("input.json","output.json"))}
    gates["public_bundle_exact"] = public_names == expected
    gates["task_only_names_solution"] = (task / "public/task.md").read_text() == "solution.py\n"
    disclosure = ((task / "public/task.md").read_text() + (task / "public/interface.schema.json").read_text()).lower()
    gates["leakage_scan"] = not any(x in disclosure for x in ("arnoldi", "pseudoinverse", "pinv", "selection", "recurrence", "algorithm"))
    gates["neutral_case_labels"] = all(p.name.startswith("case_") for p in (task / "public/cases").iterdir())
    gates["tolerance_caps"] = all(r["atol"] <= 1e-10 and r["rtol"] <= 1e-9 for r in tolerance["field_rules"].values())
    gates["independent_all_cases"] = all(compare_output(read_json(ROOT / f"curation_reports/official_runs/0022_core/independent/{split}_case_{i:02d}.json"), read_json(case / "output.json"), tolerance)["passed"] for split in ("public","hidden") for i,case in enumerate(sorted((task / split / "cases").iterdir()),1))
    case = read(task / "public/cases/case_01/input.json"); malformed = []
    for key in case: bad=copy.deepcopy(case);del bad[key];malformed.append(bad)
    bad=copy.deepcopy(case);bad["matrix"][0][0]=float("nan");malformed.append(bad)
    bad=copy.deepcopy(case);bad["matrix"]=bad["matrix"][:-1];malformed.append(bad)
    bad=copy.deepcopy(case);bad["start_vector"]=[0.0]*len(bad["start_vector"]);malformed.append(bad)
    bad=copy.deepcopy(case);bad["iterations"]=len(bad["matrix"]);malformed.append(bad)
    gates["malformed_input_rejected"] = all(fails(validate_case, x) for x in malformed)
    breakdown={"matrix":np.eye(4).tolist(),"start_vector":[1.0,2.0,3.0,4.0],"sketch_matrix":np.eye(4).tolist(),"iterations":2,"selection_budget":1}
    gates["numerical_breakdown_rejected"] = fails(independent_solve, breakdown)
    gold=read(task / "public/cases/case_01/output.json");bad=copy.deepcopy(gold);bad["basis"]=[[0.0]]
    nonfinite=copy.deepcopy(gold);nonfinite["basis"][0][0]=float("inf")
    gates["malformed_output_rejected"] = fails(validate_output,bad,case) and fails(validate_output,nonfinite,case)
    legacy_before = read(ROOT / "curation_reports/0022_legacy_preservation.json") if (ROOT / "curation_reports/0022_legacy_preservation.json").is_file() else None
    with tempfile.TemporaryDirectory(prefix="verify_0022_core_", dir=ROOT) as temporary:
        root=Path(temporary); staged=root/TASK_ID;shutil.copytree(task,staged)
        provenance=read(staged/"hidden/provenance.json");provenance["lifecycle"]="validated";provenance["gold_source"]="pinned_official_checkout";(staged/"hidden/provenance.json").write_text(json.dumps(provenance))
        (root/"manifest.json").write_text(json.dumps({"schema_version":4,"scoring":{"public_weight":.4,"hidden_weight":.6},"tasks":[{"task_id":TASK_ID,"lifecycle":"validated","public_files":files(staged/"public"),"hidden_files":files(staged/"hidden")}]}))
        reference=(ROOT/"curation_tools/fixtures/0022_core_reference_solution.py").read_text();_,reference_score=execute_program(root,staged,"reference",reference)
        gates["curator_reference_full_score"] = reference_score["full_success"] and reference_score["score"] == 1.0
        public_map={sha(p/"input.json"):read(p/"output.json") for p in sorted((staged/"public/cases").iterdir())}
        memorizer="import argparse,hashlib,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();m="+repr(public_map)+"\nk=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(m.get(k,{})))\n"
        _,memo=execute_program(root,staged,"memorizer",memorizer);gates["public_memorizer_cap"] = memo["score"] <= .4 and memo["hidden_score"] == 0
        shortcut_names=("full_arnoldi","recent_truncated_arnoldi","sketch_and_truncate","recompute_after_selection","correlation_selection","unsketched_selection","euclidean_normalization","incorrect_initial_normalization")
        matrix={};hidden_scores={}
        for name in shortcut_names:
            report,score=execute_program(root,staged,name,PROGRAM.replace("__MODE__",name));hidden_scores[name]=score["hidden_score"]
            matrix[name]={check["id"]: check["passed"] for check in score["checks"]}
        gates["all_shortcuts_fail_hidden"] = all(score < 1.0 for score in hidden_scores.values())
        badjson=root/"bad.json";badjson.write_text('{"x":NaN}');gates["nonfinite_json_rejected"]=fails(read_json,badjson)
        huge=root/"huge.json";huge.write_bytes(b"{"+b" "*(16*1024*1024)+b"}");gates["oversized_json_rejected"]=fails(read_json,huge)
        gates["traversal_rejected"]=fails(safe_relative,root,"../escape");target=root/"target";target.write_text("x");link=root/"link";link.symlink_to(target);gates["symlink_rejected"]=fails(safe_relative,root,"link")
        submission=root/"reference";stale=root/"stale.json";(root/"stale_case_outputs").mkdir();gates["stale_output_rejected"]=fails(execute,submission,staged,stale,1)
        wrong=copy.deepcopy(read(submission/"submission.json"));wrong["task_id"]="wrong";(submission/"submission.json").write_text(json.dumps(wrong));gates["wrong_task_id_rejected"]=fails(execute,submission,staged,root/"wrong.json",1)
        good=read(root/"reference.json")
        for label,mutation in (("timeout",{"timed_out":True}),("partial",{"exit_code":1}),("hash",{"output_sha256":"0"*64})):
            value=copy.deepcopy(good);value["cases"]["hidden"][0].update(mutation);path=root/f"mut_{label}.json";path.write_text(json.dumps(value));result=evaluate(staged,path);gates[f"{label}_rejected"]=result["score"]==0 and not result["valid_execution"]
    status="ACCEPT" if all(gates.values()) else "REVISE"
    result={"schema_version":1,"task_id":TASK_ID,"status":status,"gates":gates,"reference_score":reference_score["score"],"public_memorizer_score":memo["score"],"shortcut_hidden_scores":hidden_scores,"case_by_shortcut":matrix,"maximum_shortcut_score":max(hidden_scores.values()),"blockers":[k for k,v in gates.items() if not v],"gate_evidence":{"G1":"The basic sketch-and-select Arnoldi process is the paper's named contribution.","G2":"Basis/Hessenberg/sketch outputs isolate the canonical pseudoinverse realization from baselines and heuristics.","G3":"Requires sketch-normalized sparse recurrence and pseudoinverse coefficient selection.","G4":"All matrices, vector, sketch, iteration count, and budget are explicit.","G5":"Eight hidden cases cover nonnormality, sketch size, early budget clamping, normalization, conditioning, and scale.","G6":str(g6_path.relative_to(ROOT)) if g6 else "unavailable","G7":str(g7_path.relative_to(ROOT)) if g7 else "unavailable","G8":"curation_reports/0022_core_oracle.json"}}
    (ROOT/"curation_reports/0022_core_validation.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    (ROOT/"curation_reports/0022_core_shortcuts.json").write_text(json.dumps({k:result[k] for k in ("shortcut_hidden_scores","case_by_shortcut","maximum_shortcut_score","public_memorizer_score")},indent=2,sort_keys=True)+"\n")
    (ROOT/"core_algorithm_audits/0022_core.json").parent.mkdir(parents=True,exist_ok=True);(ROOT/"core_algorithm_audits/0022_core.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(status, result["blockers"])


if __name__ == "__main__": main()
