import json
import os
import subprocess

from swebench.eval_pipeline.codex_inference import run_codex_inference
from swebench.eval_pipeline.prediction_utils import (
    selected_prediction_rows,
    write_selected_predictions,
)


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


def test_codex_inference_writes_backend_tagged_prediction(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex = fake_bin / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "repo = pathlib.Path(sys.argv[sys.argv.index('--cd') + 1])\n"
        "(repo / 'module.py').write_text('value = 2\\n')\n"
        "print(json.dumps({'type': 'turn.completed'}))\n"
    )
    codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.codex_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_codex_inference(
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
        model_name="gpt-test",
        max_workers=1,
        timeout=30,
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "codex"
    assert rows[0]["model_name_or_path"] == "gpt-test"
    assert "value = 2" in rows[0]["model_patch"]
    assert (tmp_path / "codex_logs" / "demo__repo-1.jsonl").exists()


def test_codex_inference_translates_endpoint_to_temp_config(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex = fake_bin / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "repo = pathlib.Path(sys.argv[sys.argv.index('--cd') + 1])\n"
        "home = pathlib.Path(os.environ['CODEX_HOME'])\n"
        "cfg = home / 'custom.config.toml'\n"
        "text = cfg.read_text()\n"
        "assert 'model = \"provider-model\"' in text\n"
        "assert 'model_provider = \"eval_pipeline\"' in text\n"
        "assert 'base_url = \"https://example.test/v1\"' in text\n"
        "assert 'env_key = \"CODEX_EVAL_PIPELINE_API_KEY\"' in text\n"
        "assert os.environ['CODEX_EVAL_PIPELINE_API_KEY'] == 'secret-key'\n"
        "(repo / 'module.py').write_text('value = 3\\n')\n"
    )
    codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    repo = _make_git_repo(tmp_path / "repo")
    monkeypatch.setattr(
        "swebench.eval_pipeline.codex_inference._clone_repo_at_commit",
        lambda repo_name, base_commit, github_token, tmp_root=None: repo,
    )

    out = tmp_path / "predictions.jsonl"
    run_codex_inference(
        instances=[
            {
                "instance_id": "demo__repo-2",
                "repo": "demo/repo",
                "base_commit": "HEAD",
                "problem_statement": "Change value to 3.",
            }
        ],
        output_file=str(out),
        model_name="provider-model",
        max_workers=1,
        timeout=30,
        profile="custom",
        api_base="https://example.test/v1/",
        api_key="secret-key",
    )

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["agent_backend"] == "codex"
    assert "value = 3" in rows[0]["model_patch"]


def test_selected_predictions_are_backend_specific(tmp_path):
    rows = [
        {"instance_id": "i1", "model_name_or_path": "gpt", "model_patch": "swe"},
        {
            "instance_id": "i1",
            "model_name_or_path": "gpt",
            "model_patch": "codex",
            "agent_backend": "codex",
        },
        {
            "instance_id": "i2",
            "model_name_or_path": "gpt",
            "model_patch": "other",
            "agent_backend": "sweagent",
        },
    ]

    assert selected_prediction_rows(rows, "codex", "gpt") == [rows[1]]

    source = tmp_path / "all.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    dest = tmp_path / "selected.jsonl"
    count = write_selected_predictions(source, dest, "sweagent", "gpt", {"i1", "i2"})
    selected = [json.loads(line) for line in dest.read_text().splitlines()]

    assert count == 2
    assert {row["instance_id"] for row in selected} == {"i1", "i2"}
