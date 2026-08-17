import hashlib
import json
import subprocess

import pytest

from swebench.issue_pipeline import offline_claude_run as recovery


def _git(path, *args, input=None):
    return subprocess.run(
        ["git", *args],
        cwd=path,
        input=input,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(path):
    _git(path, "init", "--quiet")
    (path / "tests").mkdir()
    (path / "tests/test_science.py").write_text("old\n")
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


def _trajectory(calls, *, failed=(), final_text=None):
    rows = []
    for index, (name, tool_input) in enumerate(calls):
        tool_id = f"tool-{index}"
        rows.append(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": name,
                            "input": tool_input,
                        }
                    ]
                },
            }
        )
        rows.append(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "is_error": index in failed,
                        }
                    ]
                },
            }
        )
    if final_text is not None:
        rows.append(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": final_text}]},
            }
        )
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def _checkpoint(instance_id, digest, paths, *, error="disallowed_patch_scope", patch=""):
    audit = {
        "status": "failed" if error else "passed",
        "network_findings": [],
        "changed_paths": paths,
        "disallowed_paths": [],
        "trajectory_path": f"trajectories/{instance_id}.jsonl",
        "trajectory_sha256": digest,
    }
    prediction = {
        "instance_id": instance_id,
        "model_patch": patch,
        "model_name_or_path": "claude",
        "metrics": {"tokens": 10},
        "offline_audit": dict(audit),
        "trajectory_sha256": digest,
    }
    if error:
        prediction["error"] = error
    return {
        "instance_id": instance_id,
        "finalized": True,
        "imported": False,
        "prediction": prediction,
        "audit": {"instance_id": instance_id, **audit},
    }


def test_replay_uses_only_successful_write_edit_and_filters_root_scratch(tmp_path):
    commit = _repo(tmp_path)
    trajectory = _trajectory(
        [
            ("Bash", {"command": "printf hacked > tests/test_science.py"}),
            (
                "Edit",
                {
                    "file_path": str(tmp_path / "tests/test_science.py"),
                    "old_string": "old\n",
                    "new_string": "old\nnew assertion\n",
                },
            ),
            (
                "Write",
                {
                    "file_path": str(tmp_path / "draft.patch"),
                    "content": "scratch\n",
                },
            ),
            (
                "Write",
                {
                    "file_path": str(tmp_path / "transient_helper.py"),
                    "content": "removed later by Bash\n",
                },
            ),
            (
                "Write",
                {
                    "file_path": str(tmp_path / "verify_test.py"),
                    "content": "scratch verifier\n",
                },
            ),
            (
                "Write",
                {
                    "file_path": str(tmp_path / "TEST_SUMMARY.md"),
                    "content": "scratch summary\n",
                },
            ),
            (
                "Write",
                {
                    "file_path": str(tmp_path / "tests/failed.py"),
                    "content": "must not appear\n",
                },
            ),
        ],
        failed={6},
    )
    digest = hashlib.sha256(trajectory.encode()).hexdigest()
    checkpoint = _checkpoint(
        "case",
        digest,
        [
            "TEST_SUMMARY.md",
            "draft.patch",
            "tests/test_science.py",
            "verify_test.py",
        ],
    )

    recovered, provenance = recovery._recover_checkpoint(
        {"instance_id": "case", "base_commit": commit},
        checkpoint,
        trajectory,
        tmp_path,
    )

    patch = recovered["prediction"]["model_patch"]
    assert "+new assertion" in patch
    assert "draft.patch" not in patch
    assert "verify_test.py" not in patch
    assert "TEST_SUMMARY.md" not in patch
    assert "transient_helper.py" not in patch
    assert "failed.py" not in patch
    assert provenance["discarded_paths"] == [
        "TEST_SUMMARY.md",
        "draft.patch",
        "verify_test.py",
    ]
    assert provenance["method"] == "successful_write_edit_replay"
    assert checkpoint["prediction"]["model_patch"] == ""
    assert recovered["prediction"]["metrics"] == {"tokens": 10}


@pytest.mark.parametrize("error", ["attempted_network", "rate_limit", "claude_exit_1"])
def test_recovery_rejects_inference_failures(tmp_path, error):
    commit = _repo(tmp_path)
    trajectory = _trajectory(
        [
            (
                "Edit",
                {
                    "file_path": "tests/test_science.py",
                    "old_string": "old\n",
                    "new_string": "new\n",
                },
            )
        ]
    )
    checkpoint = _checkpoint(
        "case",
        hashlib.sha256(trajectory.encode()).hexdigest(),
        ["tests/test_science.py"],
        error=error,
    )
    with pytest.raises(ValueError, match="not recoverable"):
        recovery._recover_checkpoint(
            {"instance_id": "case", "base_commit": commit},
            checkpoint,
            trajectory,
            tmp_path,
        )


def test_recovery_rejects_a_path_not_in_original_audit(tmp_path):
    commit = _repo(tmp_path)
    trajectory = _trajectory(
        [
            (
                "Edit",
                {
                    "file_path": "tests/test_science.py",
                    "old_string": "old\n",
                    "new_string": "new\n",
                },
            )
        ]
    )
    checkpoint = _checkpoint(
        "case", hashlib.sha256(trajectory.encode()).hexdigest(), []
    )
    with pytest.raises(ValueError, match="original audit"):
        recovery._recover_checkpoint(
            {"instance_id": "case", "base_commit": commit},
            checkpoint,
            trajectory,
            tmp_path,
        )


def test_openmm_3428_uses_terminal_diff_fallback(tmp_path):
    commit = _repo(tmp_path)
    # Produce a valid new diff, then restore the disposable checkout.
    (tmp_path / "tests/test_science.py").write_text("old\nterminal assertion\n")
    patch = _git(tmp_path, "diff", "--", "tests/test_science.py") + "\n"
    _git(tmp_path, "restore", "tests/test_science.py")
    trajectory = _trajectory([], final_text=f"Final patch:\n```diff\n{patch}```")
    checkpoint = _checkpoint(
        "openmm__openmm-3428",
        hashlib.sha256(trajectory.encode()).hexdigest(),
        [],
        error=None,
    )

    recovered, provenance = recovery._recover_checkpoint(
        {"instance_id": "openmm__openmm-3428", "base_commit": commit},
        checkpoint,
        trajectory,
        tmp_path,
    )

    assert "+terminal assertion" in recovered["prediction"]["model_patch"]
    assert provenance["method"] == "terminal_diff"


def test_recovery_never_overwrites_an_existing_nonempty_patch(tmp_path):
    commit = _repo(tmp_path)
    trajectory = _trajectory([])
    checkpoint = _checkpoint(
        "case",
        hashlib.sha256(trajectory.encode()).hexdigest(),
        [],
        error=None,
        patch="existing patch",
    )
    with pytest.raises(ValueError, match="existing nonempty"):
        recovery._recover_checkpoint(
            {"instance_id": "case", "base_commit": commit},
            checkpoint,
            trajectory,
            tmp_path,
        )


def test_aggregate_merge_preserves_existing_backend_and_model_metadata():
    prior = {
        "instance_id": "case",
        "model_patch": "",
        "agent_backend": "claude_code",
        "model_name_or_path": "frozen-model",
        "metrics": {"tokens": 10},
        "error": "disallowed_patch_scope",
        "offline_audit": {"status": "failed"},
        "trajectory_sha256": "a" * 64,
    }
    recovered = {
        **prior,
        "model_patch": "diff --git a/tests/a b/tests/a\n",
        "agent_backend": "claude_code_offline_pilot",
        "offline_audit": {"status": "passed", "recovery": {"no_inference": True}},
    }

    merged = recovery._merge_recovered_prediction(prior, recovered)

    assert merged["agent_backend"] == "claude_code"
    assert merged["model_name_or_path"] == "frozen-model"
    assert merged["metrics"] == {"tokens": 10}
    assert "error" not in merged
    assert merged["offline_audit"]["recovery"]["no_inference"] is True


def test_git_apply_check_rejects_a_patch_that_does_not_apply(tmp_path):
    _repo(tmp_path)
    bad_patch = """diff --git a/tests/test_science.py b/tests/test_science.py
--- a/tests/test_science.py
+++ b/tests/test_science.py
@@ -1 +1 @@
-not the base content
+new
"""
    with pytest.raises(ValueError, match="git apply --check failed"):
        recovery._git_apply_check(tmp_path, bad_patch)


def test_atomic_update_backs_up_every_existing_target_and_rolls_back(
    tmp_path, monkeypatch
):
    first = tmp_path / "a.json"
    second = tmp_path / "nested/b.json"
    first.write_text("old-a")
    second.parent.mkdir()
    second.write_text("old-b")
    real_replace = recovery.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replacement failure")
        real_replace(source, target)

    monkeypatch.setattr(recovery.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        recovery._atomic_recovery_update(
            tmp_path, {first: "new-a", second: "new-b"}
        )

    assert first.read_text() == "old-a"
    assert second.read_text() == "old-b"
    backup = tmp_path / "backups/recover-old-inference-001"
    assert (backup / "a.json").read_text() == "old-a"
    assert (backup / "nested/b.json").read_text() == "old-b"


def test_parser_requires_resume_for_old_inference_recovery():
    with pytest.raises(SystemExit, match="requires --resume"):
        recovery.main(
            [
                "--instances",
                "missing.jsonl",
                "--output-dir",
                "missing",
                "--recover-old-inference",
            ]
        )


def test_recovery_manifest_allows_current_prompt_hash_drift():
    existing = {"model": "claude", "prompt_hash": "historical"}
    requested = {"model": "claude", "prompt_hash": "current"}

    recovery._validate_recovery_manifest(existing, requested)


def test_recovery_manifest_rejects_execution_input_drift():
    with pytest.raises(ValueError, match="does not match"):
        recovery._validate_recovery_manifest(
            {"model": "historical-model", "prompt_hash": "historical"},
            {"model": "different-model", "prompt_hash": "current"},
        )
