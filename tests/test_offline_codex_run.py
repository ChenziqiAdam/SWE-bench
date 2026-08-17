import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from swebench.issue_pipeline import offline_codex_run as full
from swebench.issue_pipeline.offline_codex_pilot import build_pilot_prompt


ROOT = Path(__file__).resolve().parents[1]


def test_real_v1_selection_maps_37_rows_to_35_unique_instances():
    instances = full.select_full_instances(
        ROOT / "Issues_No_Tests_v1.xlsx",
        [ROOT / "outputs/issues_testgenwo_v1/instances.jsonl"],
    )
    selection = full._workbook_selection(ROOT / "Issues_No_Tests_v1.xlsx")
    assert selection["row_count"] == 37
    assert selection["unique_instance_count"] == 35
    assert selection["duplicate_mappings"] == {
        "lammps__lammps-4339": [4337, 4216],
        "lammps__lammps-4195": [4141, 4180],
    }
    assert [item["instance_id"] for item in instances] == selection[
        "ordered_instance_ids"
    ]
    assert Counter(item["repo"] for item in instances) == {
        "lammps/lammps": 31,
        "biopython/biopython": 4,
    }


def test_every_v1_prompt_excludes_gold_and_mined_hints():
    instances = full.select_full_instances(
        ROOT / "Issues_No_Tests_v1.xlsx",
        [ROOT / "outputs/issues_testgenwo_v1/instances.jsonl"],
    )
    for instance in instances:
        prompt = build_pilot_prompt(instance)
        assert instance["problem_statement"].strip() in prompt
        assert str(instance["base_commit"]) in prompt
        altered = dict(instance)
        altered["patch"] = "SECRET-GOLD-PATCH"
        altered["FAIL_TO_PASS"] = ["SECRET-MINED-TARGET"]
        altered["file_contents"] = {"secret": "SECRET-FILE-CONTENTS"}
        assert build_pilot_prompt(altered) == prompt


def test_real_v2_selection_maps_41_rows_to_40_unique_instances():
    instances = full.select_full_instances(
        ROOT / "Issues_No_Tests_v2.xlsx",
        [ROOT / "outputs/issues_testgenwo_v2/instances.jsonl"],
    )
    selection = full._workbook_selection(ROOT / "Issues_No_Tests_v2.xlsx")
    assert selection["row_count"] == 41
    assert selection["unique_instance_count"] == 40
    assert selection["duplicate_mappings"] == {
        "lammps__lammps-4481": [4487, 4499],
    }
    assert [item["instance_id"] for item in instances] == selection[
        "ordered_instance_ids"
    ]
    assert Counter(item["repo"] for item in instances) == {
        "lammps/lammps": 15,
        "qutip/qutip": 13,
        "deepchem/deepchem": 4,
        "astropy/astropy": 3,
        "qgis/QGIS": 2,
        "qiskit/qiskit": 2,
        "biopython/biopython": 1,
    }


def test_every_v2_prompt_excludes_gold_and_mined_hints():
    instances = full.select_full_instances(
        ROOT / "Issues_No_Tests_v2.xlsx",
        [ROOT / "outputs/issues_testgenwo_v2/instances.jsonl"],
    )
    for instance in instances:
        prompt = build_pilot_prompt(instance)
        assert instance["problem_statement"].strip() in prompt
        assert instance["base_commit"] in prompt
        altered = dict(instance)
        altered.update(
            patch="SECRET-GOLD-PATCH",
            FAIL_TO_PASS=["SECRET-MINED-TARGET"],
            file_contents={"secret": "SECRET-FILE-CONTENTS"},
        )
        assert build_pilot_prompt(altered) == prompt


def test_real_v2_manifest_records_all_input_hashes():
    excel = ROOT / "Issues_No_Tests_v2.xlsx"
    source = ROOT / "outputs/issues_testgenwo_v2/instances.jsonl"
    instances = full.select_full_instances(excel, [source])
    manifest = full._manifest_config(
        excel_path=excel,
        instance_paths=[source],
        instances=instances,
        model="gpt-5.6-sol",
        timeout=900,
        workers=3,
        wave_size=3,
        review_all=True,
    )
    assert manifest["instance_count"] == 40
    assert len(manifest["instance_inputs"]) == 40
    assert manifest["workbook_selection"]["duplicate_mappings"] == {
        "lammps__lammps-4481": [4487, 4499],
    }
    assert all(len(item["input_hash"]) == 64 for item in manifest["instance_inputs"])


def test_real_manifest_records_hashes_inputs_duplicates_and_full_review():
    excel = ROOT / "Issues_No_Tests_v1.xlsx"
    source = ROOT / "outputs/issues_testgenwo_v1/instances.jsonl"
    instances = full.select_full_instances(excel, [source])
    manifest = full._manifest_config(
        excel_path=excel,
        instance_paths=[source],
        instances=instances,
        model="gpt-5.6-sol",
        timeout=900,
        workers=3,
        wave_size=3,
        review_all=True,
    )
    assert manifest["instance_count"] == 35
    assert manifest["review_all"] is True
    assert manifest["workbook_selection"]["duplicate_mappings"] == {
        "lammps__lammps-4339": [4337, 4216],
        "lammps__lammps-4195": [4141, 4180],
    }
    assert len(manifest["instance_inputs"]) == 35
    assert all(len(item["input_hash"]) == 64 for item in manifest["instance_inputs"])
    assert len(manifest["prompt_hash"]) == 64
    assert len(manifest["excel"]["sha256"]) == 64
    assert len(manifest["sources"][0]["sha256"]) == 64


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_validate_checkout_requires_exact_single_commit_and_no_remote(tmp_path):
    _git(tmp_path, "init", "--quiet")
    (tmp_path / "test_x.py").write_text("pass\n")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-m",
        "base",
    )
    commit = _git(tmp_path, "rev-parse", "HEAD")
    full.validate_checkout(tmp_path, commit)
    _git(tmp_path, "remote", "add", "origin", "https://example.test/repo.git")
    with pytest.raises(RuntimeError, match="checkout isolation failed"):
        full.validate_checkout(tmp_path, commit)


def test_wave_finishes_all_fetches_before_starting_agents(tmp_path, monkeypatch):
    events = []

    def fetch(instance, token, root):
        events.append(("fetch", instance["instance_id"]))
        checkout = root / instance["instance_id"]
        checkout.mkdir()
        return checkout

    def run_one(instance, checkout, output, model, timeout):
        assert sum(kind == "fetch" for kind, _ in events) == 3
        events.append(("agent", instance["instance_id"]))
        return {"instance_id": instance["instance_id"]}, {"instance_id": instance["instance_id"]}

    monkeypatch.setattr(full, "_fetch_with_retries", fetch)
    wave = [{"instance_id": str(index)} for index in range(3)]
    results = list(
        full._run_wave(
            wave,
            tmp_path,
            tmp_path,
            model="model",
            timeout=1,
            workers=3,
            github_token=None,
            run_one=run_one,
        )
    )
    assert len(results) == 3
    assert [kind for kind, _ in events[:3]] == ["fetch"] * 3
    assert not any((tmp_path / str(index)).exists() for index in range(3))


def _result(instance_id, trajectory_hash, *, patch="patch", error=None):
    audit = {
        "status": "failed" if error else "passed",
        "network_findings": [],
        "changed_paths": ["tests/test_x.py"] if patch else [],
        "disallowed_paths": [],
        "trajectory_path": f"trajectories/{instance_id}.jsonl",
        "trajectory_sha256": trajectory_hash,
    }
    prediction = {
        "instance_id": instance_id,
        "model_patch": patch,
        "model_name_or_path": "gpt-5.6-sol",
        "offline_audit": audit,
        "trajectory_sha256": trajectory_hash,
    }
    if error:
        prediction["error"] = error
    return prediction, {"instance_id": instance_id, **audit}


def test_checkpoint_is_atomic_ordered_and_final_errors_are_not_pending(tmp_path):
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "trajectories").mkdir()
    checkpoints = {}
    ordered = ["a", "b"]
    for instance_id, error in (("b", "timeout"), ("a", None)):
        text = f"trajectory {instance_id}\n"
        (tmp_path / "trajectories" / f"{instance_id}.jsonl").write_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        prediction, audit = _result(instance_id, digest, patch="" if error else "patch", error=error)
        full._save_checkpoint(
            tmp_path,
            prediction,
            audit,
            checkpoints,
            ordered,
            model="gpt-5.6-sol",
            timeout=900,
        )
    rows = full._jsonl_rows(tmp_path / "agent_predictions.jsonl")
    assert [row["instance_id"] for row in rows] == ordered
    loaded = full._load_checkpoints(tmp_path, ordered)
    assert set(loaded) == {"a", "b"}
    assert "b" not in [item for item in ordered if item not in loaded]
    for checkpoint in loaded.values():
        full._verify_trajectory(tmp_path, checkpoint)


def test_resume_requires_an_exact_manifest(tmp_path, monkeypatch):
    private_root = tmp_path / "private"
    private_root.mkdir()
    monkeypatch.setattr(full, "inference_worktree_root", lambda _name: private_root)
    output = tmp_path / "run"
    kwargs = {
        "instances": [],
        "output_dir": output,
        "manifest": {"frozen": "manifest"},
        "review_all": True,
        "finalize_reviews": False,
        "model": "gpt-5.6-sol",
        "timeout": 900,
        "workers": 3,
        "wave_size": 3,
        "github_token": None,
    }
    full.run_full(resume=False, **kwargs)
    full.run_full(resume=True, **kwargs)
    with pytest.raises(ValueError, match="resume manifest does not match"):
        full.run_full(resume=True, **{**kwargs, "manifest": {"changed": True}})


def test_review_all_queue_includes_every_case_and_preserves_alerts():
    instances = []
    checkpoints = {}
    for repo, count in (("lammps/lammps", 10), ("biopython/biopython", 3)):
        for index in range(count):
            instance_id = f"{repo.replace('/', '__')}-{index}"
            instances.append({"instance_id": instance_id, "repo": repo})
            prediction, audit = _result(instance_id, "0" * 64)
            checkpoints[instance_id] = {
                "instance_id": instance_id,
                "finalized": True,
                "imported": False,
                "prediction": prediction,
                "audit": audit,
            }
    alerted = instances[0]["instance_id"]
    checkpoints[alerted]["prediction"]["model_patch"] = ""
    queue = full._build_review_queue(instances, checkpoints, review_all=True)
    reasons = {item["instance_id"]: item["reasons"] for item in queue}
    assert reasons[alerted] == ["empty_patch"]
    assert len(queue) == len(instances)
    assert all(
        item["reasons"] == ["full_manual_audit"]
        for item in queue
        if item["instance_id"] != alerted
    )


def test_manual_rejection_empties_final_patch_without_overwriting_checkpoint(tmp_path):
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "trajectories").mkdir()
    instances = [{"instance_id": "case", "repo": "lammps/lammps"}]
    text = "trajectory\n"
    (tmp_path / "trajectories/case.jsonl").write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    prediction, audit = _result("case", digest, patch="raw patch")
    checkpoints = {
        "case": {
            "instance_id": "case",
            "finalized": True,
            "imported": False,
            "prediction": prediction,
            "audit": audit,
        }
    }
    full._atomic_json(tmp_path / "checkpoints/case.json", checkpoints["case"])
    full._write_review_files(tmp_path, instances, checkpoints, review_all=True)
    review = json.loads((tmp_path / "manual_review.json").read_text())
    review["cases"][0].update(
        {
            "review_status": "rejected",
            "no_network_attempt_verified": True,
            "no_prohibited_inputs_verified": True,
            "patch_scope_verified": True,
            "review_notes": "not a regression test",
        }
    )
    full._atomic_json(tmp_path / "manual_review.json", review)
    finalized = full._finalize_manual_reviews(
        tmp_path,
        instances,
        checkpoints,
        model="gpt-5.6-sol",
        timeout=900,
    )
    assert finalized[0]["model_patch"] == ""
    assert finalized[0]["error"] == "manual_review_rejected"
    assert checkpoints["case"]["prediction"]["model_patch"] == "raw patch"
    assert full._load_checkpoints(tmp_path, ["case"])["case"]["prediction"][
        "model_patch"
    ] == "raw patch"
