import json
import os
import subprocess

from swebench.eval_pipeline.agy_inference import run_agy_inference


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


def test_agy_inference_writes_backend_tagged_prediction(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agy = fake_bin / "agy"
    agy.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "repo = pathlib.Path.cwd()\n"
        "(repo / 'module.py').write_text('value = 2\\n')\n"
        "print(json.dumps({'event': 'result', 'result': {'status': 'SUCCESS', 'usage': "
        "{'input_tokens': 10, 'cache_read_input_tokens': 4, 'output_tokens': 3}}}))\n"
    )
    agy.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.agy_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_agy_inference(
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
        model_name="agy-test",
        max_workers=1,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "agy"
    assert rows[0]["model_name_or_path"] == "agy-test"
    assert "value = 2" in rows[0]["model_patch"]
    assert rows[0]["metrics"]["input_tokens"] == 10
    assert rows[0]["metrics"]["cache_read_input_tokens"] == 4
    assert rows[0]["metrics"]["wall_time_seconds"] >= 0
    assert (tmp_path / "agy_logs" / "demo__repo-1.jsonl").exists()


def test_agy_inference_uses_accept_edits_for_fix_mode(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agy = fake_bin / "agy"
    agy.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "assert '--mode=accept-edits' in sys.argv, sys.argv\n"
        "assert '--dangerously-skip-permissions' not in sys.argv, sys.argv\n"
    )
    agy.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.agy_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_agy_inference(
        instances=[
            {
                "instance_id": "demo__repo-2",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Fix the bug.",
            }
        ],
        output_file=str(out),
        model_name="agy-test",
        max_workers=1,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "agy"


def test_agy_inference_uses_skip_permissions_for_coverage_mode(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agy = fake_bin / "agy"
    agy.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "assert '--dangerously-skip-permissions' in sys.argv, sys.argv\n"
        "assert '--mode=accept-edits' not in sys.argv, sys.argv\n"
    )
    agy.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.agy_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.coverage_adapters.install_coverage_runner",
        lambda repo_dir, inst: None,
    )

    out = tmp_path / "predictions.jsonl"
    run_agy_inference(
        instances=[
            {
                "instance_id": "demo__repo-3",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Improve coverage.",
            }
        ],
        output_file=str(out),
        model_name="agy-test",
        max_workers=1,
        timeout=30,
        eval_mode="coverage_generation",
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "agy"
    assert rows[0]["eval_mode"] == "coverage_generation"


def test_agy_inference_records_timeout(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agy = fake_bin / "agy"
    agy.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(5)\n"
    )
    agy.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.agy_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_agy_inference(
        instances=[
            {
                "instance_id": "demo__repo-4",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Fix the bug.",
            }
        ],
        output_file=str(out),
        model_name="agy-test",
        max_workers=1,
        timeout=1,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["error"] == "timeout"
    assert rows[0]["model_patch"] == ""
