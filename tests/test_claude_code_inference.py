import json
import os
import subprocess

from swebench.eval_pipeline.claude_code_inference import run_claude_code_inference
from swebench.eval_pipeline.prediction_utils import selected_prediction_rows


def _make_git_repo(path):
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "module.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "module.py"], cwd=path, check=True, capture_output=True)
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


def test_claude_code_inference_writes_backend_tagged_prediction(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "prompt = sys.stdin.read()\n"
        "assert 'Change value to 2.' in prompt\n"
        "assert '-p' in sys.argv\n"
        "assert '--verbose' in sys.argv\n"
        "assert sys.argv[sys.argv.index('--model') + 1] == 'claude-test'\n"
        "assert sys.argv[sys.argv.index('--permission-mode') + 1] == 'acceptEdits'\n"
        "assert sys.argv[sys.argv.index('--allowedTools') + 1] == 'Bash'\n"
        "assert sys.argv[-1] == 'Bash'\n"
        "repo = pathlib.Path.cwd()\n"
        "(repo / 'module.py').write_text('value = 2\\n')\n"
        "print(json.dumps({'type': 'result', 'duration_ms': 1500, "
        "'num_turns': 2, 'total_cost_usd': 0.25, "
        "'usage': {'input_tokens': 20, 'output_tokens': 5}}))\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-1",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Change value to 2.",
                "FAIL_TO_PASS": ["tests/test_module.py::test_value"],
            }
        ],
        output_file=str(out),
        model_name="claude-test",
        max_workers=1,
        timeout=30,
        eval_mode="coverage_generation",
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "claude_code"
    assert rows[0]["model_name_or_path"] == "claude-test"
    assert "value = 2" in rows[0]["model_patch"]
    assert rows[0]["metrics"]["input_tokens"] == 20
    assert rows[0]["metrics"]["provider_duration_seconds"] == 1.5
    assert rows[0]["metrics"]["cost_usd"] == 0.25
    assert (tmp_path / "claude_code_logs" / "demo__repo-1.jsonl").exists()
    human_log = (tmp_path / "claude_code_logs" / "demo__repo-1.log").read_text()
    assert "prompt transport === stdin" in human_log
    assert "Change value to 2." not in human_log


def test_claude_code_inference_maps_endpoint_and_api_key_to_env(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "assert os.environ['ANTHROPIC_BASE_URL'] == 'https://anthropic.example/v1'\n"
        "assert os.environ['ANTHROPIC_API_KEY'] == 'secret-key'\n"
        "assert os.environ['CLAUDE_CODE_MAX_TURNS'] == '7'\n"
        "assert '--verbose' in sys.argv\n"
        "assert sys.argv[sys.argv.index('--model') + 1] == 'provider-claude'\n"
        "repo = pathlib.Path.cwd()\n"
        "(repo / 'module.py').write_text('value = 3\\n')\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-2",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Change value to 3.",
            }
        ],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=1,
        timeout=30,
        api_base="https://anthropic.example/v1/",
        api_key="secret-key",
        max_turns=7,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "claude_code"
    assert "value = 3" in rows[0]["model_patch"]


def test_claude_code_inference_skips_duplicate_instance_rows(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "repo = pathlib.Path.cwd()\n"
        "(repo / 'module.py').write_text('value = 4\\n')\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    calls = []

    def fake_clone(repo_name, base_commit, github_token, tmp_root=None):
        calls.append((repo_name, tmp_root))
        return repo

    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        fake_clone,
    )

    instance = {
        "instance_id": "demo__repo-dup",
        "repo": "demo/repo",
        "base_commit": "HEAD",
        "problem_statement": "Change value to 4.",
    }
    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[instance, dict(instance)],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=2,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert len(calls) == 1
    assert calls[0][1] == tmp_path / "tmp" / "claude_code"


def test_claude_code_inference_records_nonzero_exit_detail(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "print('interrupted tool use')\n"
        "raise SystemExit(129)\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-exit",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Exit nonzero.",
            }
        ],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=1,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["model_patch"] == ""
    assert "claude exited with code 129" in rows[0]["error"]
    assert "interrupted tool use" in rows[0]["error"]
    assert "STDOUT tail" in (tmp_path / "claude_code_logs" / "demo__repo-exit.log").read_text()


def test_claude_code_inference_extracts_stream_json_api_error(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'type': 'system', 'subtype': 'api_retry', 'error': 'unknown'}))\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': ["
        "{'type': 'text', 'text': 'API Error: Unable to connect to API (ConnectionRefused)'}"
        "]}, 'error': 'server_error'}))\n"
        "print(json.dumps({'type': 'result', 'is_error': True, "
        "'result': 'API Error: Unable to connect to API (ConnectionRefused)', "
        "'usage': {'input_tokens': 0}, 'uuid': 'opaque'}))\n"
        "raise SystemExit(1)\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-api",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Exit with an API error.",
            }
        ],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=1,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["model_patch"] == ""
    assert rows[0]["error"] == (
        "claude exited with code 1: "
        "API Error: Unable to connect to API (ConnectionRefused)"
    )


def test_claude_code_inference_ignores_low_signal_stream_json_on_exit(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': ["
        "{'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'module.py'}}"
        "]}}))\n"
        "print(json.dumps({'type': 'user', 'message': {'content': ["
        "{'type': 'tool_result', 'content': 'value = 1\\\\n' * 100}"
        "]}}))\n"
        "print(json.dumps({'type': 'system', 'subtype': 'thinking_tokens', "
        "'estimated_tokens': 328, 'uuid': 'opaque'}))\n"
        "raise SystemExit(129)\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-interrupted",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Exit after tool use.",
            }
        ],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=1,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["model_patch"] == ""
    assert rows[0]["error"] == (
        "claude exited with code 129: "
        "no actionable Claude Code error detail in stream-json output; "
        "last event: type=system, subtype=thinking_tokens"
    )


def test_claude_code_inference_captures_patch_on_timeout(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, time\n"
        "repo = pathlib.Path.cwd()\n"
        "(repo / 'module.py').write_text('value = 5\\n')\n"
        "time.sleep(10)\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-timeout",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Timeout after editing.",
            }
        ],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=1,
        timeout=2,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["error"] == "timeout"
    assert "value = 5" in rows[0]["model_patch"]


def test_claude_code_inference_recovers_structured_patch_on_timeout(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    repo = _make_git_repo(tmp_path / "repo")
    file_path = repo / "module.py"
    claude.write_text(
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        f"file_path = {str(file_path)!r}\n"
        "print(json.dumps({\n"
        "  'type': 'user',\n"
        "  'tool_use_result': {\n"
        "    'filePath': file_path,\n"
        "    'structuredPatch': [{\n"
        "      'oldStart': 1,\n"
        "      'oldLines': 1,\n"
        "      'newStart': 1,\n"
        "      'newLines': 1,\n"
        "      'lines': ['-value = 1', '+value = 6'],\n"
        "    }],\n"
        "  },\n"
        "}), flush=True)\n"
        "time.sleep(10)\n"
    )
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    monkeypatch.setattr(
        "swebench.eval_pipeline.claude_code_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_claude_code_inference(
        instances=[
            {
                "instance_id": "demo__repo-timeout-stream",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Timeout after structured patch.",
            }
        ],
        output_file=str(out),
        model_name="provider-claude",
        max_workers=1,
        timeout=2,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["error"] == "timeout"
    assert rows[0]["model_patch"].startswith("diff --git a/module.py b/module.py")
    assert "+value = 6" in rows[0]["model_patch"]
    assert "recovered patch bytes" in (
        tmp_path / "claude_code_logs" / "demo__repo-timeout-stream.log"
    ).read_text()


def test_selected_predictions_do_not_treat_legacy_rows_as_claude_code():
    rows = [
        {"instance_id": "i1", "model_name_or_path": "claude", "model_patch": "legacy"},
        {
            "instance_id": "i1",
            "model_name_or_path": "claude",
            "model_patch": "claude-code",
            "agent_backend": "claude_code",
        },
    ]

    assert selected_prediction_rows(rows, "claude_code", "claude") == [rows[1]]
