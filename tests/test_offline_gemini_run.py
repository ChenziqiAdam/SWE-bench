import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from swebench.issue_pipeline import offline_gemini_pilot as pilot
from swebench.issue_pipeline import offline_gemini_run as full


ROOT = Path(__file__).resolve().parents[1]


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path):
    _git(path, "init", "--quiet")
    (path / "tests").mkdir()
    (path / "tests/test_base.py").write_text("def test_base(): pass\n")
    _git(path, "add", ".")
    _git(
        path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-m",
        "base",
    )
    return _git(path, "rev-parse", "HEAD")


def _instance(instance_id="owner__repo-1", commit="a" * 40):
    return {
        "instance_id": instance_id,
        "repo": "owner/repo",
        "base_commit": commit,
        "problem_statement": "A scientific result is wrong.",
    }


def test_final_workbook_maps_exactly_to_84_instances():
    source = ROOT / "outputs/issues_no_tests_final_codex/instances.jsonl"
    instances = full.select_full_instances(
        ROOT / "Issues_No_Tests_final.xlsx", [source]
    )
    selection = full._workbook_selection(ROOT / "Issues_No_Tests_final.xlsx")
    assert selection["row_count"] == 88
    assert selection["unique_instance_count"] == 84
    assert selection["duplicate_mappings"] == {
        "lammps__lammps-4339": [4216, 4337, 4338],
        "lammps__lammps-4443": [4373, 4398],
        "lammps__lammps-4481": [4487, 4491],
    }
    assert Counter(item["repo"] for item in instances) == full.FINAL_PROFILE["repos"]
    assert [item["instance_id"] for item in instances] == selection[
        "ordered_instance_ids"
    ]


def test_selection_requires_exactly_one_matching_source():
    excel = ROOT / "Issues_No_Tests_final.xlsx"
    with pytest.raises(ValueError, match="exactly one"):
        full.select_full_instances(excel, [])
    source = ROOT / "outputs/issues_no_tests_final_codex/instances.jsonl"
    with pytest.raises(ValueError, match="exactly one"):
        full.select_full_instances(excel, [source, source])


def test_every_final_prompt_excludes_prohibited_instance_fields():
    instances = full.select_full_instances(
        ROOT / "Issues_No_Tests_final.xlsx",
        [ROOT / "outputs/issues_no_tests_final_codex/instances.jsonl"],
    )
    for instance in instances:
        prompt = pilot.build_pilot_prompt(instance)
        altered = dict(instance)
        altered.update(
            patch="SECRET-GOLD-PATCH",
            test_patch="SECRET-MINED-TEST",
            FAIL_TO_PASS=["SECRET-MINED-TARGET"],
            file_contents={"secret": "SECRET-FILE-CONTENTS"},
        )
        assert pilot.build_pilot_prompt(altered) == prompt
        assert instance["problem_statement"].strip() in prompt
        assert instance["base_commit"] in prompt


def test_manifest_records_frozen_safety_configuration_and_hash():
    excel = ROOT / "Issues_No_Tests_final.xlsx"
    source = ROOT / "outputs/issues_no_tests_final_codex/instances.jsonl"
    instances = full.select_full_instances(excel, [source])
    manifest = full._manifest_config(
        excel_path=excel,
        instance_paths=[source],
        instances=instances,
        model=pilot.MODEL,
        timeout=900,
        workers=3,
        wave_size=3,
        review_all=True,
    )
    assert manifest["instance_count"] == 84
    assert manifest["antigravity_safety_configuration"] == pilot.safety_settings()
    assert manifest["antigravity_safety_configuration_sha256"] == pilot.safety_settings_hash()
    assert manifest["network_isolation"] == pilot.NETWORK_ISOLATION_LABEL
    assert manifest["agent_backend"] == "antigravity_cli"


def test_command_is_headless_frozen_and_sandboxed(monkeypatch):
    monkeypatch.setattr(pilot, "_antigravity_bin", lambda: "/bin/agy")
    command = pilot.gemini_command("private prompt")
    assert command[0] == "/bin/agy"
    assert command[command.index("--model") + 1] == "gemini-3.6-flash-high"
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert "--new-project" in command
    assert "--sandbox" in command
    assert "--disable-slash-commands" in command
    assert command[-1] == "private prompt"


def test_gemini_environment_does_not_copy_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-be-copied")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-copied")
    monkeypatch.setenv("ORDINARY_SETTING", "kept")
    env = pilot._gemini_env()
    assert "GITHUB_TOKEN" not in env
    assert "GEMINI_API_KEY" not in env
    assert env["ORDINARY_SETTING"] == "kept"


@pytest.mark.parametrize(
    "event,kind",
    [
        ({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "search_web", "tool_info": {"parameters": {"q": "x"}}}}, "forbidden_tool"),
        ({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "call_mcp_tool", "tool_info": {"parameters": {}}}}, "forbidden_tool"),
        ({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "invoke_subagent", "tool_info": {"parameters": {}}}}, "forbidden_tool"),
        ({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "run_command", "tool_info": {"parameters": {"CommandLine": "curl https://example.test"}}}}, "curl"),
        ({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "run_command", "tool_info": {"parameters": {"CommandLine": "python -m pip install numpy"}}}}, "package_install"),
    ],
)
def test_trajectory_rejects_prohibited_tools_and_commands(event, kind):
    assert kind in [
        finding.kind for finding in pilot.audit_trajectory(json.dumps(event))
    ]


def test_trajectory_allows_repository_tools_and_local_tests():
    events = [
        {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "view_file", "tool_info": {"parameters": {"AbsolutePath": "x.py"}}}},
        {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "run_command", "tool_info": {"parameters": {"CommandLine": "pytest -q tests/test_x.py"}}}},
        {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "write_to_file", "tool_info": {"parameters": {"TargetFile": "tests/test_x.py"}}}},
    ]
    assert pilot.audit_trajectory("\n".join(map(json.dumps, events))) == []


@pytest.mark.parametrize(
    "stdout,stderr",
    [
        (json.dumps({"event": "result", "result": {"status": "ERROR", "error": "429 quota exceeded"}}), ""),
        (json.dumps({"event": "result", "result": {"status": "ERROR", "error": "Individual quota reached. Resets in 4h."}}), ""),
        (json.dumps({"type": "error", "error": {"type": "RESOURCE_EXHAUSTED"}}), ""),
        ("", "Quota exceeded for this project"),
    ],
)
def test_quota_detection(stdout, stderr):
    assert pilot.detect_quota_limit(stdout, stderr)


def test_run_one_redacts_prompt_audits_stream_and_captures_test_patch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    output = tmp_path / "output"
    (output / "trajectories").mkdir(parents=True)
    seen = {}

    def runner(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        (kwargs["cwd"] / "tests/test_generated.py").write_text("def test_generated(): assert 1\n")
        stream = json.dumps({"event": "result", "result": {"status": "SUCCESS", "usage": {"input_tokens": 4, "output_tokens": 2}}})
        return subprocess.CompletedProcess(command, 0, stream, "")

    record, audit = pilot._run_one(
        _instance(commit=commit), repo, output, pilot.MODEL, 10, runner=runner
    )
    command_audit = json.loads(
        (output / "trajectories/owner__repo-1.command.json").read_text()
    )
    assert seen["command"][-1] == pilot.build_pilot_prompt(_instance(commit=commit))
    assert "A scientific result is wrong" not in json.dumps(command_audit)
    assert command_audit["safety_settings_sha256"] == pilot.safety_settings_hash()
    assert command_audit["argv"][-1] == "<redacted_issue_prompt>"
    assert record["agent_backend"] == "antigravity_cli"
    assert "tests/test_generated.py" in record["model_patch"]
    assert audit["status"] == "passed"


def test_run_one_rejects_source_patch_and_filters_scratch_build_noise(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    output = tmp_path / "output"
    (output / "trajectories").mkdir(parents=True)

    def runner(command, **kwargs):
        (kwargs["cwd"] / "module.py").write_text("production = True\n")
        (kwargs["cwd"] / "notes.md").write_text("scratch\n")
        build = kwargs["cwd"] / "build-temp"
        build.mkdir()
        (build / "generated.txt").write_text("noise\n")
        return subprocess.CompletedProcess(command, 0, json.dumps({"event": "result", "result": {"status": "SUCCESS"}}), "")

    record, audit = pilot._run_one(
        _instance(commit=commit), repo, output, pilot.MODEL, 10, runner=runner
    )
    assert record["model_patch"] == ""
    assert record["error"] == "disallowed_patch_scope"
    assert audit["disallowed_paths"] == ["module.py"]


def test_run_one_handles_missing_executable_and_timeout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    output = tmp_path / "output"
    (output / "trajectories").mkdir(parents=True)

    def missing(*args, **kwargs):
        raise FileNotFoundError("agy")

    record, _ = pilot._run_one(
        _instance(commit=commit), repo, output, pilot.MODEL, 10, runner=missing
    )
    assert record["error"] == "process_error"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, output="partial", stderr="late")

    record, _ = pilot._run_one(
        _instance("owner__repo-2", commit), repo, output, pilot.MODEL, 1, runner=timeout
    )
    assert record["error"] == "timeout"


def test_run_one_with_fake_antigravity_executable(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    output = tmp_path / "output"
    (output / "trajectories").mkdir(parents=True)
    executable = tmp_path / "agy"
    executable.write_text(
        "#!/bin/sh\n"
        "python -c 'import json; print(json.dumps({\"event\": \"result\", "
        "\"result\": {\"status\": \"SUCCESS\", \"usage\": {\"input_tokens\": 1}}}))'\n"
    )
    executable.chmod(0o755)
    monkeypatch.setattr(pilot, "_antigravity_bin", lambda: str(executable))

    record, audit = pilot._run_one(
        _instance(commit=commit), repo, output, pilot.MODEL, 10
    )
    assert record.get("error") is None
    assert record["metrics"]["input_tokens"] == 1
    assert audit["status"] == "passed"


def test_wave_finishes_fetches_before_agents(tmp_path, monkeypatch):
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
    assert len(list(full._run_wave(wave, tmp_path, tmp_path, model="m", timeout=1, workers=3, github_token=None, run_one=run_one))) == 3
    assert [kind for kind, _ in events[:3]] == ["fetch"] * 3


def test_quota_result_is_not_checkpointed_and_resume_is_exact(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(full, "inference_worktree_root", lambda _name: private)
    monkeypatch.setattr(
        full,
        "_run_wave",
        lambda *args, **kwargs: iter([(
            {"instance_id": "case", "error": "quota_limit"},
            {"instance_id": "case"},
        )]),
    )
    output = tmp_path / "run"
    kwargs = dict(
        instances=[_instance("case")],
        output_dir=output,
        manifest={"frozen": True},
        resume=False,
        review_all=True,
        finalize_reviews=False,
        model=pilot.MODEL,
        timeout=900,
        workers=1,
        wave_size=1,
        github_token=None,
    )
    with pytest.raises(full.QuotaLimitStop):
        full.run_full(**kwargs)
    assert list((output / "checkpoints").glob("*.json")) == []
    with pytest.raises(ValueError, match="resume manifest"):
        full.run_full(**{**kwargs, "resume": True, "manifest": {"changed": True}})


def test_manual_rejection_empties_patch_without_changing_checkpoint(tmp_path):
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "trajectories").mkdir()
    text = "trajectory\n"
    (tmp_path / "trajectories/case.jsonl").write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    audit = {
        "status": "passed",
        "network_findings": [],
        "changed_paths": ["tests/test_x.py"],
        "disallowed_paths": [],
        "trajectory_path": "trajectories/case.jsonl",
        "trajectory_sha256": digest,
    }
    prediction = {
        "instance_id": "case",
        "model_patch": "raw patch",
        "offline_audit": dict(audit),
        "trajectory_sha256": digest,
    }
    checkpoint = {"instance_id": "case", "finalized": True, "imported": False, "prediction": prediction, "audit": audit}
    full._atomic_json(tmp_path / "checkpoints/case.json", checkpoint)
    instances = [{"instance_id": "case"}]
    checkpoints = {"case": checkpoint}
    full._write_review_files(tmp_path, instances, checkpoints, review_all=True)
    review = json.loads((tmp_path / "manual_review.json").read_text())
    review["cases"][0].update({
        "review_status": "rejected",
        "no_network_attempt_verified": True,
        "no_prohibited_inputs_verified": True,
        "patch_scope_verified": True,
    })
    full._atomic_json(tmp_path / "manual_review.json", review)
    result = full._finalize_manual_reviews(tmp_path, instances, checkpoints, model=pilot.MODEL, timeout=900)
    assert result[0]["model_patch"] == ""
    assert result[0]["error"] == "manual_review_rejected"
    assert json.loads((tmp_path / "checkpoints/case.json").read_text())["prediction"]["model_patch"] == "raw patch"
