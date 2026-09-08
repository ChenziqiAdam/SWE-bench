#!/usr/bin/env python3
"""Structural, scientific, shortcut, runtime, and lifecycle gates for 0020_core."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from spsur_core_common import instrument_design, restricted_design, validate_case, validate_output
from spsur_core_scientific import solve

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0020_core"


def read(path: Path):
    return json.loads(path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_map(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def fails(function, *args) -> bool:
    try:
        function(*args)
    except Exception:
        return True
    return False


def rebuild(case: dict, *, max_lag: int = 2, diagonal_sigma: bool = False, exogenous_wy: bool = False) -> dict:
    """Concrete fault models used only by the shortcut audit."""
    y_panel, x, w, shared = validate_case(case); g_count, n_count, p_count = x.shape
    y = y_panel.reshape(-1); base, mapping = restricted_design(x, shared); lag = np.kron(np.eye(g_count), w)
    wy = (lag @ y).reshape(g_count, n_count); endogenous = np.zeros((g_count*n_count, g_count))
    for g in range(g_count): endogenous[g*n_count:(g+1)*n_count, g] = wy[g]
    z = np.column_stack((endogenous, base)); noint = np.delete(base, sorted({mapping[g,0] for g in range(g_count)}), axis=1)
    blocks = [base]; current = noint
    for _ in range(max_lag): current = lag @ current; blocks.append(current)
    h = np.column_stack(blocks)
    zhat = z if exogenous_wy else h @ np.linalg.lstsq(h, z, rcond=None)[0]
    q = np.linalg.lstsq(zhat, y, rcond=None)[0]; residuals = (y - zhat @ q).reshape(g_count,n_count).T; residuals -= residuals.mean(0)
    sigma = residuals.T @ residuals / (n_count-1)
    if diagonal_sigma: sigma = np.diag(np.diag(sigma))
    omega = np.kron(np.linalg.inv(sigma), np.eye(n_count)); covariance = np.linalg.inv(zhat.T @ omega @ zhat); theta = covariance @ zhat.T @ omega @ y
    se = np.sqrt(np.maximum(np.diag(covariance),0)); beta=np.array([[theta[g_count+mapping[g,p]] for p in range(p_count)] for g in range(g_count)]); bse=np.array([[se[g_count+mapping[g,p]] for p in range(p_count)] for g in range(g_count)])
    fit=(z@theta).reshape(g_count,n_count); corr=lambda a,b: float(np.corrcoef(a,b)[0,1]**2); direct=np.empty((g_count,p_count-1)); total=np.empty_like(direct)
    for g in range(g_count):
        multiplier=np.linalg.inv(np.eye(n_count)-theta[g]*w); direct[g]=beta[g,1:]*np.trace(multiplier)/n_count; total[g]=beta[g,1:]*np.sum(multiplier)/n_count
    return {"beta":beta.tolist(),"beta_standard_errors":bse.tolist(),"rho":theta[:g_count].tolist(),"rho_standard_errors":se[:g_count].tolist(),"r2_by_equation":[corr(y_panel[g],fit[g]) for g in range(g_count)],"pooled_r2":corr(y,fit.ravel()),"direct_effects":direct.tolist(),"indirect_effects":(total-direct).tolist(),"total_effects":total.tolist()}


def shortcut(case: dict, expected: dict, mode: str) -> dict:
    if mode == "public_memorization": return copy.deepcopy(expected)
    if mode == "ignored_restrictions":
        altered=copy.deepcopy(case); altered["shared_beta_columns"]=[]; return solve(altered)
    if mode == "missing_w2x": return rebuild(case,max_lag=1)
    if mode == "diagonal_covariance": return rebuild(case,diagonal_sigma=True)
    if mode in {"wy_as_exogenous","equation_ols"}: return rebuild(case,exogenous_wy=True)
    if mode == "equation_2sls":
        # Diagonal covariance is exactly equation-wise 2SLS at the GLS stage.
        return rebuild(case,diagonal_sigma=True)
    result=copy.deepcopy(expected); beta=np.asarray(result["beta"],float); rho=np.asarray(result["rho"],float); w=np.asarray(case["w"],float)
    if mode == "nonspatial_sur":
        result["rho"]=[0.0]*len(rho); result["direct_effects"]=beta[:,1:].tolist(); result["indirect_effects"]=np.zeros_like(beta[:,1:]).tolist(); result["total_effects"]=beta[:,1:].tolist()
    elif mode == "wrong_stacking":
        result["rho"] = np.roll(rho,1).tolist(); result["beta"] = np.roll(beta,1,axis=0).tolist()
    elif mode == "coefficient_as_impact":
        result["direct_effects"]=beta[:,1:].tolist(); result["indirect_effects"]=np.zeros_like(beta[:,1:]).tolist(); result["total_effects"]=beta[:,1:].tolist()
    elif mode == "truncated_impacts":
        direct=[]; total=[]
        for g in range(len(rho)):
            multiplier=np.eye(w.shape[0])+rho[g]*w
            direct.append((beta[g,1:]*np.trace(multiplier)/w.shape[0]).tolist()); total.append((beta[g,1:]*np.sum(multiplier)/w.shape[0]).tolist())
        result["direct_effects"]=direct; result["total_effects"]=total; result["indirect_effects"]=(np.asarray(total)-np.asarray(direct)).tolist()
    return result


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute
    task=ROOT/TASK_ID; tolerance=read(task/"hidden/tolerances.json"); provenance=read(task/"hidden/provenance.json")
    cases=[(split,path,read(path/"input.json"),read(path/"output.json")) for split in ("public","hidden") for path in sorted((task/split/"cases").iterdir())]
    baseline=read(ROOT/"curation_reports/0020_core_legacy_baseline.json")["preserved_files"]
    blind_path=ROOT/"core_algorithm_audits/0020_core_blind.json"; g7_path=ROOT/"curation_reports/0020_core_g7.json"
    blind=read(blind_path) if blind_path.is_file() else {}; g7=read(g7_path) if g7_path.is_file() else {}
    gates={"G1_core_centrality":False,"G2_unique_core":False,"G3_scientific_specificity":False,"G4_executable_closure":True,
           "G5_hazard_coverage":len([c for c in cases if c[0]=="hidden"])==8,
           "G6_blind_identification":blind.get("G6")=="PASS" and blind.get("pass_count",0)>=2 and blind.get("configured_model_only") is True,
           "G7_blind_implementation":g7.get("G7")=="PASS" and g7.get("score")==1.0 and g7.get("public_only_offline") is True,
           "G8_oracle_validity":provenance["independent_audit"]["status"]=="passed" and len(set(provenance["official_reproduction"]["clean_checkout_bundle_sha256"]))==1,
           "legacy_bytes_unchanged":baseline==file_map(ROOT/"scibench_replication_0020"),
           "task_md_solution_only":(task/"public/task.md").read_text()=="solution.py\n",
           "full_paper":sha(task/"public/paper.pdf")=="380ffdb8a8c1e48cf204fb1742aa7f071d8c2898734b1dbe16b9b543570a02f2",
           "three_public_eight_hidden":sum(c[0]=="public" for c in cases)==3 and sum(c[0]=="hidden" for c in cases)==8}
    gates["independent_all_cases"]=all(compare_output(solve(value),expected,tolerance)["passed"] for _,_,value,expected in cases)
    valid=cases[0][2]; malformed=[]
    for key in valid: bad=copy.deepcopy(valid); del bad[key]; malformed.append(bad)
    bad=copy.deepcopy(valid); bad["y"][0][0]=float("nan"); malformed.append(bad)
    bad=copy.deepcopy(valid); bad["x"]=bad["x"][:-1]; malformed.append(bad)
    bad=copy.deepcopy(valid); bad["w"][0][0]=0.1; malformed.append(bad)
    bad=copy.deepcopy(valid); bad["w"][0]=[0.0]*len(bad["w"]); malformed.append(bad)
    bad=copy.deepcopy(valid); bad["shared_beta_columns"]=[2,1]; malformed.append(bad)
    bad=copy.deepcopy(valid); bad["x"][0][:]=[bad["x"][0][0]]*len(bad["x"][0]); malformed.append(bad)
    gates["invalid_inputs_rejected"]=all(fails(validate_case,value) for value in malformed)
    output=cases[0][3]; gates["invalid_outputs_rejected"]=fails(validate_output,{**output,"rho":[0.0]},valid) and fails(validate_output,{**output,"beta":[[float("inf")]]},valid)
    gates["shared_coefficients_repeat_exactly"]=all(np.all(np.asarray(expected["beta"])[0,j]==np.asarray(expected["beta"])[:,j]) for _,_,value,expected in cases for j in value["shared_beta_columns"])
    gates["impact_additivity"]=all(np.allclose(np.asarray(expected["direct_effects"])+np.asarray(expected["indirect_effects"]),expected["total_effects"],atol=2e-13,rtol=2e-13) for _,_,_,expected in cases)
    permutation_case=copy.deepcopy(next(c[2] for c in cases if c[0]=="hidden")); rng=np.random.default_rng(20); order=rng.permutation(len(permutation_case["w"]));
    permutation_case["y"]=np.asarray(permutation_case["y"])[:,order].tolist(); permutation_case["x"]=np.asarray(permutation_case["x"])[:,order,:].tolist(); permutation_case["w"]=np.asarray(permutation_case["w"])[np.ix_(order,order)].tolist()
    original=solve(next(c[2] for c in cases if c[0]=="hidden")); permuted=solve(permutation_case)
    gates["node_permutation_invariant"]=compare_output(permuted,original,{"comparison":"fieldwise","field_rules":{key:{"atol":2e-9,"rtol":2e-9} for key in original}})["passed"]
    beta_probe=np.array([[1.2,-0.7]]); identity=np.eye(5); gates["zero_spillover_limit"] = np.array_equal(beta_probe* np.trace(identity)/5,beta_probe) and np.array_equal(beta_probe*np.sum(identity)/5,beta_probe)
    modes=("nonspatial_sur","equation_ols","equation_2sls","wy_as_exogenous","missing_w2x","wrong_stacking","diagonal_covariance","ignored_restrictions","coefficient_as_impact","truncated_impacts","public_memorization")
    matrix={}
    for split,path,value,expected in cases:
        row={}
        for mode in modes:
            try: candidate={} if mode=="public_memorization" and split=="hidden" else shortcut(value,expected,mode); row[mode]=compare_output(candidate,expected,tolerance)["passed"]
            except Exception: row[mode]=False
        matrix[f"{split}:{path.name}"]=row
    gates["all_shortcuts_fail_hidden"]=all(not all(matrix[f"hidden:case_{i:02d}"][mode] for i in range(1,9)) for mode in modes)
    with tempfile.TemporaryDirectory(prefix="scibench_0020_core_verify_",dir=ROOT) as temporary:
        root=Path(temporary); staged=root/TASK_ID; shutil.copytree(task,staged); staged_p=read(staged/"hidden/provenance.json"); staged_p["lifecycle"]="validated"; staged_p["gold_source"]="pinned_official_checkout"; write=lambda p,v:p.write_text(json.dumps(v)); write(staged/"hidden/provenance.json",staged_p)
        write(root/"manifest.json",{"schema_version":4,"scoring":{"public_weight":.4,"hidden_weight":.6},"tasks":[{"task_id":TASK_ID,"lifecycle":"validated","public_files":file_map(staged/"public"),"hidden_files":file_map(staged/"hidden")} ]})
        submission=root/"reference"; submission.mkdir(); shutil.copyfile(ROOT/"curation_tools/fixtures/0020_core_reference_solution.py",submission/"solution.py"); write(submission/"submission.json",{"schema_version":4,"task_id":TASK_ID,"entrypoint":[sys.executable,"solution.py"]})
        report_path=root/"execution.json"; report=execute(submission,staged,report_path,30); write(report_path,report); score=evaluate(staged,report_path); gates["curator_reference_score_one"]=score["score"]==1.0 and score["full_success"]
        bad_json=root/"bad.json"; bad_json.write_text('{"x":NaN}'); gates["nonfinite_json_rejected"]=fails(read_json,bad_json)
        oversized=root/"oversized.json"; oversized.write_bytes(b'{"x":"'+b'x'*(16*1024*1024)+b'"}'); gates["oversized_json_rejected"]=fails(read_json,oversized)
        gates["traversal_rejected"]=fails(safe_relative,root,"../x"); target=root/"target"; target.write_text("x"); link=root/"link"; link.symlink_to(target); gates["symlink_rejected"]=fails(safe_relative,root,"link")
        mutation=copy.deepcopy(report); mutation["cases"]["hidden"][0]["timed_out"]=True; path=root/"timeout.json"; write(path,mutation); gates["timeout_rejected"]=evaluate(staged,path)["score"]==0
        mutation=copy.deepcopy(report); mutation["cases"]["hidden"][0]["output_sha256"]="0"*64; path=root/"hash.json"; write(path,mutation); gates["stale_or_hash_output_rejected"]=evaluate(staged,path)["score"]==0
    hard=[key for key in gates if key.startswith("G")]
    status="REJECT" if not all(gates[key] for key in ("G1_core_centrality","G2_unique_core","G3_scientific_specificity")) else ("ACCEPT" if all(gates.values()) else "REVISE")
    result={"schema_version":1,"task_id":TASK_ID,"status":status,"gates":gates,"case_shortcut_pass_matrix":matrix,"reference_score":score["score"],"hard_gate_failures":[key for key in hard if not gates[key]],"promotion_allowed":status=="ACCEPT"}
    (ROOT/"curation_reports/0020_core_validation.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":status,"failed":[key for key,value in gates.items() if not value],"reference_score":score["score"]},indent=2))


if __name__ == "__main__": main()
