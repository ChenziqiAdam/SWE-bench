#!/usr/bin/env python3
"""G1-G8, shortcut, scoring, and evaluator-safety gates for 0015_core."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from fixed_sparsity_core_common import validate_case, validate_output

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "scibench_replication_0015_core"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def expect_error(function, *args) -> bool:
    try: function(*args)
    except Exception: return True
    return False


BASE = r'''import argparse,json,pathlib,numpy as np
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();v=json.load(open(a.input));A=np.array(v['A'],float);S=np.array(v['S'],bool);G=np.array(v['G'],float);Z=A@G;R=np.zeros_like(A)
for i in range(A.shape[0]):
 c=np.flatnonzero(S[i])
 if len(c): R[i,c]=np.linalg.lstsq(G[c].T,Z[i],rcond=None)[0]
MODE
o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps({'A_tilde':R.tolist()},allow_nan=False))
'''


def program(mode: str) -> str:
    replacements = {
        "reference": "pass",
        "mask_copy": "R=A*S",
        "ignore_g": "R=A*S",
        "diagonal_only": "R=np.diag(np.diag(R)) if R.shape[0]==R.shape[1] else np.zeros_like(R)",
        "symmetric": "R=(R+R.T)/2 if R.shape[0]==R.shape[1] else np.zeros_like(R)",
        "uniform_rows": "c0=np.flatnonzero(S[0]);R=np.zeros_like(A);[R.__setitem__((i,c0),np.linalg.lstsq(G[c0].T,Z[i],rcond=None)[0]) for i in range(A.shape[0])]",
        "wrong_transpose": "R=R.T if R.shape[0]==R.shape[1] else np.zeros_like(R)",
        "coloring": """conflict=(S.T@S)>0;colors=[]
for j in range(A.shape[1]):
 used={colors[k] for k in range(j) if conflict[j,k]};color=0
 while color in used: color+=1
 colors.append(color)
V=np.zeros((A.shape[1],max(colors)+1))
for j,color in enumerate(colors): V[j,color]=1
Y=A@V;R=np.zeros_like(A)
for i in range(A.shape[0]):
 for j in np.flatnonzero(S[i]): R[i,j]=Y[i,colors[j]]""",
        "partial_exact": "R=A*S",
    }
    return BASE.replace("MODE", replacements[mode])


def execute_solver(root: Path, task: Path, name: str, source: str, timeout: float = 20.0):
    from run_submission import execute
    submission = root / name; submission.mkdir(); (submission / "solution.py").write_text(source, encoding="utf-8")
    (submission / "submission.json").write_text(json.dumps({"schema_version": 4, "task_id": TASK_ID, "entrypoint": [sys.executable, "solution.py"]}), encoding="utf-8")
    report_path = root / f"{name}_report.json"; report = execute(submission, task, report_path, timeout)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    from evaluation.framework import evaluate
    return report, evaluate(task, report_path)


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from evaluation.framework import compare_output, evaluate, read_json, safe_relative
    from run_submission import execute
    task = ROOT / TASK_ID; tolerance = read_json(task / "hidden/tolerances.json")
    blind = read(ROOT / "core_algorithm_audits/0015_core_blind.json"); oracle = read(ROOT / "curation_reports/0015_core_oracle.json")
    g7 = read(ROOT / "curation_reports/0015_core_g7.json")
    gates: dict[str, bool] = {
        "G1_core_centrality": True, "G2_unique_core": True, "G3_scientific_specificity": True,
        "G4_executable_closure": True, "G5_hidden_generalization": len(list((task / "hidden/cases").iterdir())) == 8,
        "G6_blind_identification": blind.get("G6") == "PASS" and blind.get("pass_count", 0) >= 2,
        "G7_dependency_closure": g7.get("G7") == "PASS" and g7.get("score") == 1.0,
        "G8_oracle_validity": oracle.get("G8") == "PASS" and oracle.get("two_clean_checkouts_match") is True,
    }
    public_names = files(task / "public")
    gates["public_bundle_exact"] = set(public_names) == {"paper.pdf", "task.md", "interface.schema.json", *(f"cases/case_{i:02d}/{name}" for i in range(1, 4) for name in ("input.json", "output.json"))}
    gates["task_only_names_solution"] = (task / "public/task.md").read_text(encoding="utf-8") == "solution.py\n"
    disclosure = ((task / "public/task.md").read_text() + (task / "public/interface.schema.json").read_text()).lower()
    gates["public_text_leakage_scan"] = not any(word in disclosure for word in ("gaussian", "least", "algorithm", "formula", "figure", "baseline", "hutchinson", "coloring"))
    gates["neutral_case_labels"] = all(p.name.startswith("case_") for p in (task / "public/cases").iterdir())
    gates["independent_reference_all_cases"] = all(
        compare_output(read_json(ROOT / f"curation_reports/official_runs/0015_core/independent/{split}_case_{i:02d}.json"), read_json(case / "output.json"), tolerance)["passed"]
        for split in ("public", "hidden") for i, case in enumerate(sorted((task / split / "cases").iterdir()), 1))

    valid = read_json(task / "public/cases/case_02/input.json"); malformed = []
    for key in valid:
        bad = copy.deepcopy(valid); del bad[key]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["A"][0][0] = float("nan"); malformed.append(bad)
    bad = copy.deepcopy(valid); bad["S"][0][0] = 0.5; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["S"] = bad["S"][:-1]; malformed.append(bad)
    bad = copy.deepcopy(valid); bad["G"] = bad["G"][:-1]; malformed.append(bad)
    gates["malformed_nonfinite_shape_binary_input_rejected"] = all(expect_error(validate_case, value) for value in malformed)
    shape = (len(valid["A"]), len(valid["A"][0]))
    gates["wrong_nonfinite_output_rejected"] = expect_error(validate_output, {"A_tilde": [[0.0]]}, shape) and expect_error(validate_output, {"A_tilde": [[float("inf") for _ in range(shape[1])] for _ in range(shape[0])]}, shape)

    with tempfile.TemporaryDirectory(prefix="scibench_0015_core_gates_", dir=ROOT) as temporary:
        root = Path(temporary); staged = root / TASK_ID; shutil.copytree(task, staged)
        manifest = {"schema_version": 4, "scoring": {"public_weight": 0.4, "hidden_weight": 0.6}, "tasks": [{"task_id": TASK_ID, "lifecycle": "validated", "public_files": files(staged / "public"), "hidden_files": files(staged / "hidden")}]}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        _, reference = execute_solver(root, staged, "clean_offline_reference", program("reference"))
        gates["G7_clean_offline_reference"] = reference["score"] == 1.0 and reference["full_success"]
        gates["reference_score_one"] = gates["G7_clean_offline_reference"]

        public_map = {hashlib.sha256((case / "input.json").read_bytes()).hexdigest(): read_json(case / "output.json") for case in sorted((staged / "public/cases").iterdir())}
        memorizer = "import argparse,hashlib,json,pathlib\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args();m=" + repr(public_map) + "\nk=hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest();o=pathlib.Path(a.output);o.mkdir(parents=True,exist_ok=True);(o/'output.json').write_text(json.dumps(m.get(k,{})))\n"
        _, memo_score = execute_solver(root, staged, "public_memorizer", memorizer)
        gates["public_memorizer_cap"] = memo_score["score"] <= 0.4 and memo_score["hidden_score"] == 0
        shortcuts = {}
        for name in ("mask_copy", "ignore_g", "diagonal_only", "symmetric", "uniform_rows", "wrong_transpose", "coloring", "partial_exact"):
            _, result = execute_solver(root, staged, name, program(name)); shortcuts[name] = result["hidden_score"]
        gates["all_shortcuts_fail_hidden"] = all(score < 1.0 for score in shortcuts.values())

        bad_json = root / "bad.json"; bad_json.write_text('{"x":NaN}')
        gates["nonfinite_json_rejected"] = expect_error(read_json, bad_json)
        gates["traversal_rejected"] = expect_error(safe_relative, root, "../escape")
        target = root / "target"; target.write_text("x"); link = root / "link"; link.symlink_to(target)
        gates["symlink_rejected"] = expect_error(safe_relative, root, "link")
        reference_dir = root / "clean_offline_reference"
        stale = root / "stale_report.json"; (root / "stale_report_case_outputs").mkdir()
        gates["stale_output_rejected"] = expect_error(execute, reference_dir, staged, stale, 1.0)
        good_report_path = root / "clean_offline_reference_report.json"; good = read(good_report_path)
        mutations = {}
        x = copy.deepcopy(good); x["cases"]["hidden"][0]["timed_out"] = True; mutations["timeout"] = x
        x = copy.deepcopy(good); x["cases"]["hidden"][0]["exit_code"] = 1; mutations["partial"] = x
        x = copy.deepcopy(good); x["cases"]["hidden"][0]["output_sha256"] = "0" * 64; mutations["hash"] = x
        for name, value in mutations.items():
            path = root / f"mutation_{name}.json"; path.write_text(json.dumps(value)); result = evaluate(staged, path)
            gates[f"{name}_rejected"] = result["score"] == 0 and not result["valid_execution"]

    if not all(gates.values()): raise AssertionError({key: value for key, value in gates.items() if not value})
    result = {"schema_version": 1, "task_id": TASK_ID, "status": "passed", "gates": gates,
              "reference_score": reference["score"], "public_memorizer_score": memo_score["score"], "shortcut_hidden_scores": shortcuts,
              "gate_evidence": {"G1": "Paper section 1.2 identifies Algorithm 2.1 as the first contribution solving both stated problems.",
                                "G2": "Public A/S/G to A_tilde contract selects Algorithm 2.1 over coloring, diagonal-only, bounds, and lower-bound constructions.",
                                "G3": "Requires the paper-specific shared Gaussian sketch and row-restricted recovery.",
                                "G4": "Finite explicit matrices close the deterministic input-output contract.",
                                "G5": "Eight hazard-driven hidden matrices cover distribution, support, shape, direction, and conditioning.",
                                "G6": "core_algorithm_audits/0015_core_blind.json", "G7": "curation_reports/0015_core_g7.json: native sandbox denied network and repository reads; score 1.0", "G8": "curation_reports/0015_core_oracle.json"}}
    (ROOT / "curation_reports/0015_core_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "core_algorithm_audits/0015_core.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
