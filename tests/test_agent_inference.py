import subprocess

import pytest

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit


def _git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


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


def test_clone_repo_excludes_future_history_and_removes_remote(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet")
    _git(source, "config", "user.name", "Test User")
    _git(source, "config", "user.email", "test@example.com")

    tracked = source / "tracked.txt"
    tracked.write_text("base\n")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "--quiet", "-m", "base")
    base_commit = _git(source, "rev-parse", "HEAD").stdout.strip()

    tracked.write_text("future answer\n")
    _git(source, "commit", "--quiet", "-am", "future answer commit")
    future_commit = _git(source, "rev-parse", "HEAD").stdout.strip()

    checkout_root = tmp_path / "checkouts"
    checkout = _clone_repo_at_commit(
        source.as_uri(),
        base_commit,
        github_token=None,
        tmp_root=checkout_root,
    )

    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == base_commit
    assert _git(checkout, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert _git(checkout, "rev-list", "--count", "--all").stdout.strip() == "1"
    assert _git(checkout, "remote").stdout.strip() == ""
    visible_log = _git(checkout, "log", "--all", "--oneline").stdout
    assert "base" in visible_log
    assert "future answer commit" not in visible_log
    assert _git(
        checkout,
        "cat-file",
        "-e",
        f"{future_commit}^{{commit}}",
        check=False,
    ).returncode != 0
    assert not (checkout / ".git" / "FETCH_HEAD").exists()
