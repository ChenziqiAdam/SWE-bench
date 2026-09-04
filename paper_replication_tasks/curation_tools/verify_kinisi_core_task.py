#!/usr/bin/env python3
"""Verify 0011_core construction, shortcuts, evaluator safety, and optional G7."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from kinisi_core_common import validate_case, validate_output

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0011_core"
REFERENCE = ROOT / "curation_tools/fixtures/0011_core_reference_solution.py"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def expect_error(function, *args) -> bool:
    try:
        function(*args)
    except Exception:
        return True
    return False


SHORTCUT = r'''import argparse,json,pathlib,numpy as np
from scipy.linalg import pinvh
from scipy.stats import norm,truncnorm
MODE="__MODE__"
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();v=json.load(open(a.input))
t=np.asarray(v['lag_times'],float);rows=[np.asarray(x,float) for x in v['squared_displacement_samples']];means=np.asarray([x.mean() for x in rows]);counts=np.asarray(v['independent_sample_counts'],float)
if MODE=='wrong_neff':counts=np.asarray([len(x) for x in rows],float)
variances=np.asarray([x.var(ddof=1)/n for x,n in zip(rows,counts)]);first=0 if MODE=='wrong_fit_window' else int(np.flatnonzero(t>=float(v['fit_start']))[0]);t=t[first:];means=means[first:];counts=counts[first:];variances=variances[first:];X=np.column_stack((t,np.ones(t.size)))
if MODE=='ols':
 beta=np.linalg.lstsq(X,means,rcond=None)[0];res=means-X@beta;s2=max(float(res@res/max(t.size-2,1)),np.finfo(float).eps*max(float(np.mean(np.abs(means))),1.0)**2);C=pinvh(X.T@X)*s2;dist=norm(beta[0],max(float(np.sqrt(abs(C[0,0]))),1e-15))
elif MODE=='wls':
 P=np.diag(1/variances);C=pinvh(X.T@P@X);beta=C@X.T@P@means;dist=norm(beta[0],max(float(np.sqrt(abs(C[0,0]))),1e-15))
else:
 C=np.empty((t.size,t.size))
 for i in range(t.size):
  for j in range(i,t.size):
   C[i,j]=C[j,i]=(variances[j]*counts[j]/counts[i] if MODE=='wrong_eq6' else variances[i]*counts[i]/counts[j])
 if MODE=='diagonal_covariance':C=np.diag(np.diag(C))
 if MODE!='skip_reconditioning':
  e,Q=np.linalg.eigh(C);e=np.maximum(e,e[-1]/float(v['condition_limit']));C=(Q*e)@Q.T
 P=pinvh(C);PC=pinvh(X.T@P@X);beta=PC@X.T@P@means;sd=max(float(np.sqrt(abs(PC[0,0]))),1e-15)
 dist=norm(beta[0],sd) if MODE=='ignore_nonnegative_prior' else truncnorm(-beta[0]/sd,np.inf,loc=beta[0],scale=sd)
scale=1/(2*int(v['dimension']));q=dist.ppf([.025,.5,.975]);result={'mean':float(dist.mean()*scale),'variance':float(dist.var()*scale**2),'quantiles':[float(x*scale) for x in q]};o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(result,allow_nan=False))
'''


def execute_solver(root: Path, task: Path, name: str, source: str, timeout: float = 30.0):
    from run_submission import execute
    from evaluation.framework import evaluate
    submission = root / name; submission.mkdir()
    (submission / "solution.py").write_text(source, encoding="utf-8")
    write(submission / "submission.json", {"schema_version": 4, "task_id": TASK_ID,
                                            "entrypoint": [sys.executable, "solution.py"]})
    report_path = root / f"{name}_execution.json"
    execution = execute(submission, task, report_path, timeout)
    write(report_path, execution)
    return execution, evaluate(task, report_path)


def case_matrix(result: dict) -> dict[str, bool]:
    return {row["id"]: bool(row["passed"]) for row in result["checks"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-g7", action="store_true")
    parser.add_argument("--waive-g7", action="store_true")
    args = parser.parse_args()
    if args.require_g7 and args.waive_g7:
        parser.error("--require-g7 and --waive-g7 are mutually exclusive")
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, read_json, safe_relative
    task = ROOT / TASK_ID
    tolerance = read_json(task / "hidden/tolerances.json")
    blind = read(ROOT / "core_algorithm_audits/0011_core_blind.json")
    oracle = read(ROOT / "curation_reports/0011_core_oracle.json")
    hazards = read(ROOT / "curation_reports/0011_core_hazards.json")
    sources = read(ROOT / "curation_reports/sources/0011_core/sources.json")
    gates = {
        "G1_core_centrality": True,
        "G2_unique_core": True,
        "G3_scientific_specificity": True,
        "G4_executable_closure": True,
        "G5_hidden_generalization": len(list((task / "hidden/cases").iterdir())) == 8,
        "G6_blind_identification": blind.get("G6") == "PASS" and blind.get("pass_count", 0) >= 2,
        "G8_oracle_validity": oracle.get("G8") == "PASS" and oracle.get("two_clean_checkouts_match") is True
            and oracle.get("independent_within_frozen_tolerance") is True,
    }
    public_names = files(task / "public")
    gates["public_bundle_exact"] = set(public_names) == {
        "paper.pdf", "task.md", "interface.schema.json",
        *(f"cases/case_{index:02d}/{name}" for index in range(1, 4) for name in ("input.json", "output.json")),
    }
    gates["task_only_names_solution"] = (task / "public/task.md").read_text(encoding="utf-8") == "solution.py\n"
    disclosure = ((task / "public/task.md").read_text() + (task / "public/interface.schema.json").read_text()).lower()
    gates["public_text_leakage_scan"] = not any(term in disclosure for term in (
        "bayes", "diffusion", "covariance", "eigen", "regression", "kinisi", "equation", "formula", "repository"))
    gates["neutral_case_labels"] = all(path.name.startswith("case_") for path in (task / "public/cases").iterdir())
    gates["source_archive_complete"] = len(sources["sources"]) == 4 and all(
        (ROOT / "curation_reports/sources/0011_core" / row["file"]).is_file()
        and sha(ROOT / "curation_reports/sources/0011_core" / row["file"]) == row["sha256"]
        for row in sources["sources"])
    covered = {case for hazard in hazards["hazards"] for case in hazard["hidden_cases"]}
    gates["hazard_catalog_covers_hidden"] = covered == {f"case_{index:02d}" for index in range(1, 9)}
    gates["two_official_evidence_runs_exact"] = all(
        sha(ROOT / f"curation_reports/official_runs/0011_core/run_1/{split}_case_{index:02d}.json")
        == sha(ROOT / f"curation_reports/official_runs/0011_core/run_2/{split}_case_{index:02d}.json")
        for split, count in (("public", 3), ("hidden", 8)) for index in range(1, count + 1))
    gates["independent_all_cases"] = all(compare_output(
        read_json(ROOT / f"curation_reports/official_runs/0011_core/independent/{split}_case_{index:02d}.json"),
        read_json(case / "output.json"), tolerance)["passed"]
        for split in ("public", "hidden")
        for index, case in enumerate(sorted((task / split / "cases").iterdir()), 1))

    valid = read(task / "public/cases/case_01/input.json")
    malformed = []
    for key in valid:
        bad = copy.deepcopy(valid); del bad[key]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["lag_times"][0] = float("nan"); malformed.append(bad)
    bad = copy.deepcopy(valid); bad["squared_displacement_samples"][0][0] = -1; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["independent_sample_counts"] = bad["independent_sample_counts"][:-1]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["fit_start"] = bad["lag_times"][-1]; malformed.append(bad)
    gates["malformed_nonfinite_shape_input_rejected"] = all(expect_error(validate_case, value) for value in malformed)
    gates["wrong_nonfinite_output_rejected"] = expect_error(validate_output, {"mean": 1, "variance": 1, "quantiles": [0, 1]}) \
        and expect_error(validate_output, {"mean": float("inf"), "variance": 1, "quantiles": [0, 1, 2]})

    with tempfile.TemporaryDirectory(prefix="scibench_0011_core_verify_", dir=ROOT) as temporary:
        root = Path(temporary); staged = root / TASK_ID; shutil.copytree(task, staged)
        provenance = read(staged / "hidden/provenance.json"); provenance["lifecycle"] = "validated"; write(staged / "hidden/provenance.json", provenance)
        manifest = {"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6},
                    "tasks": [{"task_id": TASK_ID, "lifecycle": "validated",
                               "public_files": files(staged / "public"), "hidden_files": files(staged / "hidden")} ]}
        write(root / "manifest.json", manifest)
        _, reference = execute_solver(root, staged, "curator_reference", REFERENCE.read_text(encoding="utf-8"))
        gates["curator_reference_score_one"] = reference["score"] == 1.0 and reference["full_success"]

        shortcuts = {}
        for name in ("ols", "wls", "diagonal_covariance", "wrong_eq6", "wrong_neff",
                     "skip_reconditioning", "ignore_nonnegative_prior", "wrong_fit_window"):
            _, result = execute_solver(root, staged, name, SHORTCUT.replace("__MODE__", name))
            shortcuts[name] = {"score": result["score"], "public_score": result["public_score"],
                               "hidden_score": result["hidden_score"], "cases": case_matrix(result)}
        gates["all_scientific_shortcuts_fail_hidden"] = all(row["hidden_score"] < 1.0 for row in shortcuts.values())

        public_map = {sha(case / "input.json"): read(case / "output.json") for case in sorted((staged / "public/cases").iterdir())}
        memorizer = "import argparse,hashlib,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();m=" + repr(public_map) + "\nk=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();v=m.get(k,{'mean':0.0,'variance':0.0,'quantiles':[0.0,0.0,0.0]});o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(v))\n"
        _, memo = execute_solver(root, staged, "public_memorizer", memorizer)
        gates["public_memorizer_reported_separately"] = memo["public_score"] == 1.0 and memo["hidden_score"] == 0.0 and memo["score"] == 0.4

        gates["traversal_rejected"] = expect_error(safe_relative, root, "../escape")
        target = root / "target"; target.write_text("x", encoding="utf-8"); link = root / "link"; link.symlink_to(target)
        gates["symlink_rejected"] = expect_error(safe_relative, root, "link")
        sleep_source = "import argparse,time\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');p.parse_args();time.sleep(1)\n"
        _, timed = execute_solver(root, staged, "timeout_probe", sleep_source, timeout=0.01)
        gates["runner_timeout_enforced"] = timed["score"] == 0.0 and timed["valid_execution"] is False

    g7_path = ROOT / "curation_reports/0011_core_g7.json"
    if args.require_g7:
        g7 = read(g7_path)
        gates["G7_blind_implementation"] = g7.get("G7") == "PASS" and g7.get("score") == 1.0
    elif g7_path.exists():
        g7 = read(g7_path)
        gates["G7_blind_implementation"] = g7.get("G7") == "PASS" and g7.get("score") == 1.0

    failed = {key: value for key, value in gates.items() if not value}
    if args.waive_g7:
        failed.pop("G7_blind_implementation", None)
    if failed:
        raise AssertionError(failed)
    maximum = max(row["hidden_score"] for row in shortcuts.values())
    report = {"schema_version": 1, "task_id": TASK_ID,
              "status": "ready_g7_waived" if args.waive_g7 else ("passed" if args.require_g7 else "construction_passed"), "gates": gates,
              "validation_waivers": ([{"gate": "G7_blind_implementation", "granted_on": "2026-09-04", "reason": "Explicit curator decision; original failed G7 report and submission are retained."}] if args.waive_g7 else []),
              "curator_reference": {"sha256": sha(REFERENCE), "score": reference["score"]},
              "shortcut_audit": {"distinct_scientific_shortcut_count": len(shortcuts),
                  "results": shortcuts, "maximum_hidden_score": maximum,
                  "conclusion": f"All {len(shortcuts)} tested scientific shortcuts fail at least one hidden case; maximum hidden score is {maximum}."},
              "public_memorizer": {"score": memo["score"], "public_score": memo["public_score"], "hidden_score": memo["hidden_score"]},
              "gate_evidence": {
                  "G1": "The target paper's main contribution is the approximate Bayesian MSD regression; deleting it removes the claimed estimator and uncertainty method.",
                  "G2": "The numeric input/output selects posterior diffusion summaries, distinguishing the target from OLS, WLS, GLS point estimates, and random-walk generation.",
                  "G3": "Requires the paper-specific Eq. 6 covariance approximation, effective-count rescaling, reconditioning, fit regime, and nonnegative posterior.",
                  "G4": "All numerical inputs, fit boundary, condition bound, dimension, and seed are explicit.",
                  "G5": "curation_reports/0011_core_hazards.json and shortcut_audit.results",
                  "G6": "core_algorithm_audits/0011_core_blind.json",
                  "G7": "curation_reports/0011_core_g7.json" if g7_path.exists() else "pending formal blind implementation",
                  "G8": "curation_reports/0011_core_oracle.json"}}
    write(ROOT / "curation_reports/0011_core_validation.json", report)
    write(ROOT / "core_algorithm_audits/0011_core.json", report)


if __name__ == "__main__":
    main()
