import subprocess

import pytest

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit


def test_clone_repo_redacts_token_and_cleans_failed_tmpdir(tmp_path, monkeypatch):
    token = "github_pat_secret"

    def fail_clone(cmd, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=cmd,
            stderr=f"fatal: could not read https://{token}@github.com/demo/repo.git",
        )

    monkeypatch.setattr(subprocess, "run", fail_clone)

    with pytest.raises(RuntimeError) as exc:
        _clone_repo_at_commit(
            "demo/repo",
            "HEAD",
            token,
            tmp_root=tmp_path,
        )

    message = str(exc.value)
    assert token not in message
    assert "<redacted>" in message
    assert list(tmp_path.iterdir()) == []
