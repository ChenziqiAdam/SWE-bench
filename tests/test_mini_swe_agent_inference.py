import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from swebench.eval_pipeline.inference_security import inference_input_hash
from swebench.eval_pipeline.mini_swe_agent_inference import (
    _litellm_model_name,
    _mini_problem_text,
    _trajectory_metrics,
    run_mini_swe_agent_inference,
)


def _make_git_repo(path):
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "module.py").write_text("value = 1\n")
    subprocess.run(
        ["git", "add", "module.py"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "base",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def _instance(instance_id="demo__repo-1"):
    return {
        "instance_id": instance_id,
        "repo": "demo/repo",
        "base_commit": "HEAD",
        "problem_statement": "Change value to 2.",
        "file_contents": {"module.py": "value = 1\n"},
        "FAIL_TO_PASS": ["tests/test_module.py::test_value"],
    }


def _install_fake_mini(tmp_path, monkeypatch, *, exit_code=0, sleep_seconds=0):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    executable = fake_bin / "mini"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys, time\n"
        f"time.sleep({sleep_seconds})\n"
        "args = sys.argv[1:]\n"
        "assert '--yolo' in args and '--exit-immediately' in args\n"
        "assert args[args.index('--environment-class') + 1] == 'local'\n"
        "assert 'environment.timeout=17' in args\n"
        "assert os.environ['MSWEA_CONFIGURED'] == 'true'\n"
        "assert pathlib.Path(os.environ['MSWEA_GLOBAL_CONFIG_DIR']).is_dir()\n"
        "task = args[args.index('--task') + 1]\n"
        "assert 'Change value to 2.' in task\n"
        "repo = pathlib.Path.cwd()\n"
        "(repo / 'module.py').write_text('value = 2\\n')\n"
        "trajectory = {\n"
        "  'info': {'mini_version': '2.4.6', 'model_stats': "
        "{'instance_cost': 0.125, 'api_calls': 2}},\n"
        "  'messages': [{'role': 'assistant', 'extra': {\n"
        "    'actions': [{'command': 'true'}],\n"
        "    'response': {'usage': {'prompt_tokens': 10, "
        "'completion_tokens': 4, 'prompt_tokens_details': {'cached_tokens': 3}}}\n"
        "  }}]\n"
        "}\n"
        "pathlib.Path(args[args.index('--output') + 1]).write_text(json.dumps(trajectory))\n"
        "print(os.environ.get('OPENAI_API_KEY', 'ok'))\n"
        "print(os.environ.get('OPENAI_API_KEY', 'ok'), file=sys.stderr)\n"
        f"sys.exit({exit_code})\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    return executable


def test_mini_backend_captures_patch_trajectory_and_metrics(tmp_path, monkeypatch):
    _install_fake_mini(tmp_path, monkeypatch)
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )

    output = tmp_path / "predictions.jsonl"
    run_mini_swe_agent_inference(
        [_instance()],
        str(output),
        "gpt-test",
        max_workers=1,
        timeout=30,
        command_timeout=17,
    )

    row = json.loads(output.read_text())
    assert row["agent_backend"] == "mini_swe_agent"
    assert row["model_name_or_path"] == "gpt-test"
    assert "value = 2" in row["model_patch"]
    assert row["metrics"] == {
        "cost_usd": 0.125,
        "api_calls": 2,
        "turns": 2,
        "input_tokens": 10,
        "output_tokens": 4,
        "cache_read_input_tokens": 3,
        "total_tokens": 14,
        "tool_calls": 1,
        "mini_swe_agent_version": "2.4.6",
        "wall_time_seconds": row["metrics"]["wall_time_seconds"],
    }
    logs = tmp_path / "mini_swe_agent_logs"
    assert (logs / "demo__repo-1.traj.json").exists()
    assert (logs / "demo__repo-1.stdout.log").exists()
    assert (logs / "demo__repo-1.stderr.log").exists()


def test_relative_output_does_not_write_trajectory_inside_repo(tmp_path, monkeypatch):
    _install_fake_mini(tmp_path, monkeypatch)
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )
    monkeypatch.chdir(tmp_path)

    output = "outputs/predictions.jsonl"
    run_mini_swe_agent_inference(
        [_instance()],
        output,
        "gpt-test",
        max_workers=1,
        timeout=30,
        command_timeout=17,
    )

    row = json.loads((tmp_path / output).read_text())
    assert "module.py" in row["model_patch"]
    assert "mini_swe_agent_logs" not in row["model_patch"]
    assert not (repo / "outputs").exists()
    assert (
        tmp_path
        / "outputs"
        / "mini_swe_agent_logs"
        / "demo__repo-1.traj.json"
    ).exists()


def test_guarded_runtime_trajectory_is_outside_hidden_output_and_archived(
    tmp_path, monkeypatch
):
    _install_fake_mini(tmp_path, monkeypatch)
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference.validate_network_policy",
        lambda *args, **kwargs: None,
    )
    captured = {}

    def capture_guard(command, **_kwargs):
        captured["runtime_trajectory"] = command[command.index("--output") + 1]
        return command

    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference.guard_command",
        capture_guard,
    )
    output = tmp_path / "predictions.jsonl"
    stale = tmp_path / "mini_swe_agent_logs" / "demo__repo-1.traj.json"
    stale.parent.mkdir()
    stale.write_text('{"info":{"mini_version":"stale"},"messages":[]}')

    run_mini_swe_agent_inference(
        [_instance()],
        str(output),
        "gpt-test",
        max_workers=1,
        timeout=30,
        command_timeout=17,
        network_policy="model-only",
    )

    runtime_path = captured["runtime_trajectory"]
    assert not runtime_path.startswith(str(tmp_path))
    assert not os.path.exists(runtime_path)
    archived = json.loads(stale.read_text())
    assert archived["info"]["mini_version"] == "2.4.6"
    assert json.loads(output.read_text())["metrics"]["api_calls"] == 2


def test_custom_endpoint_uses_litellm_config_without_persisting_key(
    tmp_path, monkeypatch
):
    executable = _install_fake_mini(tmp_path, monkeypatch)
    custom = tmp_path / "custom.yaml"
    custom.write_text("agent:\n  system_template: test\n")
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )
    inspected = tmp_path / "inspected"
    original = executable.read_text()
    executable.write_text(
        original.replace(
            "task = args[args.index('--task') + 1]",
            "assert args[args.index('--model') + 1] == 'openai/provider-model'\n"
            "assert 'model.model_kwargs.api_base=\\\"http://127.0.0.1:4000/v1\\\"' in args\n"
            "assert args[args.index('--config') + 1] == "
            + repr(str(custom.resolve()))
            + "\n"
            "assert 'secret-key' not in repr(args)\n"
            f"pathlib.Path({str(inspected)!r}).write_text('yes')\n"
            "task = args[args.index('--task') + 1]",
        )
    )

    output = tmp_path / "predictions.jsonl"
    run_mini_swe_agent_inference(
        [_instance()],
        str(output),
        "provider-model",
        max_workers=1,
        timeout=30,
        command_timeout=17,
        config_path=str(custom),
        api_base="http://127.0.0.1:4000/v1/",
        api_key="secret-key",
    )

    assert inspected.exists()
    logs = tmp_path / "mini_swe_agent_logs"
    for path in logs.iterdir():
        assert "secret-key" not in path.read_text()
    assert "<redacted>" in (logs / "demo__repo-1.stdout.log").read_text()


@pytest.mark.parametrize(
    ("mode", "required"),
    [
        ("fix", "smallest source change"),
        ("test_generation", "Do not fix the bug"),
        ("coverage_generation", "Improve whole-repository test coverage"),
    ],
)
def test_mode_specific_prompts_include_context(mode, required):
    prompt = _mini_problem_text(_instance(), mode)
    assert required in prompt
    assert "module.py" in prompt
    assert "tests/test_module.py::test_value" in prompt


def test_litellm_model_prefix_only_for_custom_endpoint():
    assert _litellm_model_name("gpt-4o", None) == "gpt-4o"
    assert _litellm_model_name("gpt-4o", "http://localhost:4000") == "openai/gpt-4o"
    assert (
        _litellm_model_name("openai/gpt-4o", "http://localhost:4000") == "openai/gpt-4o"
    )


def test_nonzero_exit_and_missing_executable_are_structured(tmp_path, monkeypatch):
    _install_fake_mini(tmp_path, monkeypatch, exit_code=7)
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )
    output = tmp_path / "nonzero.jsonl"
    run_mini_swe_agent_inference(
        [_instance()], str(output), "gpt", max_workers=1, timeout=30, command_timeout=17
    )
    row = json.loads(output.read_text())
    assert row["error"] == "mini-swe-agent exited with code 7"
    assert row["model_patch"]

    missing_repo = _make_git_repo(tmp_path / "missing-repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: missing_repo,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._mini_swe_agent_bin",
        lambda: "/definitely/missing/mini",
    )
    missing_output = tmp_path / "missing.jsonl"
    run_mini_swe_agent_inference(
        [_instance("demo__repo-2")],
        str(missing_output),
        "gpt",
        max_workers=1,
        command_timeout=17,
    )
    missing = json.loads(missing_output.read_text())
    assert missing["model_patch"] == ""
    assert "No such file or directory" in missing["error"]
    missing_logs = tmp_path / "mini_swe_agent_logs"
    assert (missing_logs / "demo__repo-2.traj.json").exists()
    assert (missing_logs / "demo__repo-2.stdout.log").exists()
    assert (missing_logs / "demo__repo-2.stderr.log").exists()


def test_duplicate_resume_hash_and_empty_retry(tmp_path, monkeypatch):
    _install_fake_mini(tmp_path, monkeypatch)
    instance = _instance()
    clone_calls = []

    def clone(*args, **kwargs):
        clone_calls.append(1)
        return _make_git_repo(tmp_path / f"repo-{len(clone_calls)}")

    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit", clone
    )
    output = tmp_path / "predictions.jsonl"
    cached = {
        "instance_id": instance["instance_id"],
        "model_patch": "",
        "model_name_or_path": "gpt",
        "agent_backend": "mini_swe_agent",
        "eval_mode": "fix",
        "inference_input_hash": inference_input_hash(instance),
    }
    output.write_text(json.dumps(cached) + "\n")
    run_mini_swe_agent_inference(
        [instance, instance],
        str(output),
        "gpt",
        max_workers=1,
        command_timeout=17,
        retry_empty_predictions=True,
    )
    assert len(clone_calls) == 1
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["model_patch"]

    run_mini_swe_agent_inference(
        [instance], str(output), "gpt", max_workers=1, command_timeout=17
    )
    assert len(clone_calls) == 1

    changed = dict(instance)
    changed["file_contents"] = {"module.py": "different inference context\n"}
    run_mini_swe_agent_inference(
        [changed], str(output), "gpt", max_workers=1, command_timeout=17
    )
    assert len(clone_calls) == 2


def test_timeout_keeps_partial_patch_and_records_error(tmp_path, monkeypatch):
    _install_fake_mini(tmp_path, monkeypatch, sleep_seconds=1)
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )
    output = tmp_path / "predictions.jsonl"
    run_mini_swe_agent_inference(
        [_instance()],
        str(output),
        "gpt",
        max_workers=1,
        timeout=0.1,
        command_timeout=17,
    )
    row = json.loads(output.read_text())
    assert row["error"] == "timeout"
    assert row["metrics"]["wall_time_seconds"] >= 0.1


def test_cpp_coverage_capture_excludes_build_artifacts(tmp_path, monkeypatch):
    executable = _install_fake_mini(tmp_path, monkeypatch)
    executable.write_text(
        executable.read_text().replace(
            "(repo / 'module.py').write_text('value = 2\\n')",
            "(repo / 'build').mkdir()\n"
            "(repo / 'build' / 'generated.o').write_text('binary')\n"
            "(repo / 'Tests').mkdir()\n"
            "(repo / 'Tests' / 'test_added.cpp').write_text('// test\\n')",
        )
    )
    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.mini_swe_agent_inference._clone_repo_at_commit",
        lambda *args, **kwargs: repo,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.coverage_adapters.install_coverage_runner",
        lambda *args, **kwargs: None,
    )
    instance = _instance()
    instance["coverage_language"] = "cpp"
    output = tmp_path / "predictions.jsonl"
    run_mini_swe_agent_inference(
        [instance],
        str(output),
        "gpt",
        max_workers=1,
        command_timeout=17,
        eval_mode="coverage_generation",
    )
    patch = json.loads(output.read_text())["model_patch"]
    assert "Tests/test_added.cpp" in patch
    assert "build/generated.o" not in patch


def test_trajectory_metric_extraction_tolerates_missing_usage():
    assert _trajectory_metrics({"info": {"mini_version": "2"}, "messages": []}) == {
        "mini_swe_agent_version": "2"
    }


def test_pipeline_cli_exposes_mini_backend(monkeypatch):
    from swebench.eval_pipeline import run_pipeline

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--agent_backend",
            "mini_swe_agent",
            "--mini_swe_agent_model",
            "openai/test",
            "--mini_swe_agent_timeout",
            "12",
            "--mini_swe_agent_command_timeout",
            "7",
            "--mini_swe_agent_cost_limit",
            "1.5",
        ],
    )
    args = run_pipeline.parse_args()
    assert args.agent_backend == "mini_swe_agent"
    assert args.mini_swe_agent_model == "openai/test"
    assert args.mini_swe_agent_timeout == 12
    assert args.mini_swe_agent_command_timeout == 7
    assert args.mini_swe_agent_cost_limit == 1.5


def test_pipeline_dispatches_all_mini_settings(monkeypatch):
    from swebench.eval_pipeline import mini_swe_agent_inference, run_pipeline

    captured = {}
    monkeypatch.setattr(
        mini_swe_agent_inference,
        "run_mini_swe_agent_inference",
        lambda **kwargs: captured.update(kwargs),
    )
    args = SimpleNamespace(
        agent_backend="mini_swe_agent",
        log_dir="logs",
        spreadsheet="input.xlsx",
        inference_hidden_path=["extra"],
        max_workers=3,
        mini_swe_agent_timeout=12,
        mini_swe_agent_command_timeout=7,
        mini_swe_agent_cost_limit=1.5,
        mini_swe_agent_config="custom.yaml",
        endpoint="http://127.0.0.1:4000/v1",
        api_key="key",
        retry_empty_predictions=True,
        eval_mode="test_generation",
        inference_network_policy="model-only",
    )
    run_pipeline._run_agent_backend(
        args, [_instance()], "predictions.jsonl", "model", None
    )
    assert captured["model_name"] == "model"
    assert captured["timeout"] == 12
    assert captured["command_timeout"] == 7
    assert captured["cost_limit"] == 1.5
    assert captured["config_path"] == "custom.yaml"
    assert captured["hidden_paths"] == ["logs", "input.xlsx", "extra"]
