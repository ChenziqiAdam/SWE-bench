import json
import subprocess

from openpyxl import Workbook

from swebench.issue_pipeline.offline_codex_pilot import (
    PILOT_CASES,
    _capture_patch,
    audit_patch_paths,
    audit_trajectory,
    build_pilot_prompt,
    codex_command,
    select_pilot_instances,
)


def _instance(instance_id, repo):
    return {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": "a" * 40,
        "problem_statement": "Scientific issue text",
        "patch": "SECRET GOLD PATCH",
        "FAIL_TO_PASS": ["SECRET TEST HINT"],
        "file_contents": {"secret.py": "SECRET FILE CONTENT"},
    }


def test_select_pilot_instances_cross_checks_both_sheets(tmp_path):
    workbook = Workbook()
    workbook.remove(workbook.active)
    headers = ["Repo", "Issue Number", "Closing PR #"]
    for sheet_name in ("Batch 1", "Batch 2"):
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(headers)
    for _iid, (repo, issue, pr, sheet_name) in PILOT_CASES.items():
        workbook[sheet_name].append([repo, issue, pr])
    excel = tmp_path / "issues.xlsx"
    workbook.save(excel)

    rows = [_instance(iid, values[0]) for iid, values in PILOT_CASES.items()]
    instances = tmp_path / "instances.jsonl"
    instances.write_text("".join(json.dumps(row) + "\n" for row in reversed(rows)))

    selected = select_pilot_instances(excel, instances)
    assert [row["instance_id"] for row in selected] == list(PILOT_CASES)


def test_pilot_prompt_excludes_solution_and_mined_hints():
    prompt = build_pilot_prompt(_instance("openmm__openmm-4161", "openmm/openmm"))
    assert "Scientific issue text" in prompt
    assert "Base commit:" in prompt
    assert "SECRET GOLD PATCH" not in prompt
    assert "SECRET TEST HINT" not in prompt
    assert "SECRET FILE CONTENT" not in prompt
    assert "Network access from tools is forbidden" in prompt


def test_codex_command_disables_external_tool_surfaces(tmp_path):
    command = codex_command(tmp_path, "prompt")
    joined = " ".join(command)
    assert "--ignore-user-config" in command
    assert "workspace-write" in command
    assert "sandbox_workspace_write.network_access=false" in command
    assert "mcp_servers={}" in command
    for feature in ("apps", "browser_use", "computer_use", "multi_agent", "plugins"):
        assert f"--disable {feature}" in joined


def test_audit_flags_network_commands_and_web_tools_not_issue_urls():
    events = [
        {"type": "thread.started", "text": "Issue says https://example.test"},
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "git fetch origin main"},
        },
        {
            "type": "item.started",
            "item": {"type": "web_search", "query": "answer"},
        },
    ]
    findings = audit_trajectory("\n".join(json.dumps(event) for event in events))
    assert {finding.kind for finding in findings} == {"network_git", "forbidden_tool"}


def test_audit_flags_absolute_tools_and_python_package_install():
    events = [
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "/usr/bin/curl example.test"},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "python3 -m pip install chemistry-package",
            },
        },
    ]
    findings = audit_trajectory("\n".join(json.dumps(event) for event in events))
    assert {finding.kind for finding in findings} == {"curl", "package_install"}


def test_audit_patch_scope_allows_tests_and_rejects_source(tmp_path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "source.cpp").write_text("old\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_science.py").write_text("old\n")
    unittest = tmp_path / "unittest"
    unittest.mkdir()
    (unittest / "in.regression_fixture").write_text("old\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--quiet", "-m", "base",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "source.cpp").write_text("new\n")
    (tests / "test_science.py").write_text("new\n")
    (unittest / "in.regression_fixture").write_text("new\n")
    (tmp_path / "new_source.cpp").write_text("new\n")

    _capture_patch(tmp_path)
    paths, disallowed = audit_patch_paths(tmp_path)
    assert paths == [
        "new_source.cpp",
        "source.cpp",
        "tests/test_science.py",
        "unittest/in.regression_fixture",
    ]
    assert disallowed == ["new_source.cpp", "source.cpp"]


def test_process_launch_error_is_a_final_auditable_result(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("pass\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "--quiet", "-m", "base",
        ],
        cwd=repo,
        check=True,
    )
    output = tmp_path / "output"
    (output / "trajectories").mkdir(parents=True)

    def fail_to_launch(*args, **kwargs):
        raise OSError("cannot execute")

    from swebench.issue_pipeline.offline_codex_pilot import _run_one

    prediction, audit = _run_one(
        _instance("openmm__openmm-1", "openmm/openmm"),
        repo,
        output,
        "gpt-5.6-sol",
        1,
        runner=fail_to_launch,
    )
    assert prediction["error"] == "process_error"
    assert prediction["model_patch"] == ""
    assert audit["status"] == "failed"
