import subprocess

import pytest

from swebench.issue_pipeline import offline_claude_pilot, offline_codex_pilot


PILOT_MODULES = (offline_claude_pilot, offline_codex_pilot)


@pytest.mark.parametrize("pilot", PILOT_MODULES)
def test_prompt_forbids_nonfinal_scratch_artifacts(pilot):
    prompt = pilot.build_pilot_prompt(
        {
            "repo": "science/project",
            "base_commit": "a" * 40,
            "problem_statement": "A scientific regression.",
        }
    )

    assert "only persistent file changes" in prompt
    assert ".patch/.diff files" in prompt
    assert "helper scripts" in prompt
    assert "Do not write the final patch to disk or to /tmp" in prompt
    assert "inspect it with `git diff`" in prompt


def _init_repo(path):
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    (path / "tests").mkdir()
    (path / "tests" / "test_science.py").write_text("old\n")
    (path / "canonical.patch").write_text("tracked fixture\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "-m",
            "base",
        ],
        cwd=path,
        check=True,
    )


@pytest.mark.parametrize("pilot", PILOT_MODULES)
def test_untracked_root_scratch_is_filtered_without_changing_test_patch(
    tmp_path, pilot
):
    _init_repo(tmp_path)
    test_path = tmp_path / "tests" / "test_science.py"
    test_path.write_text("old\nnew assertion\n")
    (tmp_path / "test_regression.patch").write_text("duplicated scratch diff\n")

    expected_test_patch = subprocess.run(
        ["git", "diff", "HEAD", "--", "tests/test_science.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    scratch_paths = pilot._untracked_root_scratch_paths(tmp_path)
    assert scratch_paths == {"test_regression.patch"}

    captured = pilot._capture_patch(tmp_path)
    filtered = pilot._strip_build_artifact_diff_blocks(
        captured, scratch_paths=scratch_paths
    )
    paths, disallowed = pilot.audit_patch_paths(
        tmp_path, scratch_paths=scratch_paths
    )

    assert filtered == expected_test_patch
    assert paths == ["test_regression.patch", "tests/test_science.py"]
    assert disallowed == []


@pytest.mark.parametrize("pilot", PILOT_MODULES)
def test_tracked_root_patch_is_never_treated_as_disposable_scratch(tmp_path, pilot):
    _init_repo(tmp_path)
    (tmp_path / "canonical.patch").write_text("tracked fixture changed\n")

    scratch_paths = pilot._untracked_root_scratch_paths(tmp_path)
    captured = pilot._capture_patch(tmp_path)
    filtered = pilot._strip_build_artifact_diff_blocks(
        captured, scratch_paths=scratch_paths
    )

    assert scratch_paths == set()
    assert filtered == captured
    assert "diff --git a/canonical.patch b/canonical.patch" in filtered


@pytest.mark.parametrize("pilot", PILOT_MODULES)
def test_nested_patch_fixture_is_not_treated_as_root_scratch(tmp_path, pilot):
    _init_repo(tmp_path)
    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir()
    fixture = fixtures / "expected.patch"
    fixture.write_text("legitimate test fixture\n")

    scratch_paths = pilot._untracked_root_scratch_paths(tmp_path)
    captured = pilot._capture_patch(tmp_path)
    filtered = pilot._strip_build_artifact_diff_blocks(
        captured, scratch_paths=scratch_paths
    )

    assert scratch_paths == set()
    assert filtered == captured
    assert "diff --git a/tests/fixtures/expected.patch" in filtered
