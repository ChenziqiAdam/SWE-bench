import json

from swebench.eval_pipeline.inference_security import (
    inference_hidden_paths,
    inference_input_hash,
)
from swebench.eval_pipeline.prediction_utils import prediction_matches_backend


def test_hidden_paths_include_output_and_explicit_log_cache(tmp_path):
    output = tmp_path / "outputs" / "run" / "agent_predictions.jsonl"
    output.parent.mkdir(parents=True)
    logs = tmp_path / "evaluation_logs"
    logs.mkdir()

    hidden = inference_hidden_paths(output, [logs])

    assert str(output.parent.resolve()) in hidden
    assert str(logs.resolve()) in hidden


def test_prediction_cache_requires_exact_inference_input_hash():
    instance = {
        "instance_id": "demo__repo-1",
        "repo": "demo/repo",
        "base_commit": "abc",
        "problem_statement": "original issue",
        "patch": "gold",
    }
    fingerprint = inference_input_hash(instance)
    row = {
        "instance_id": instance["instance_id"],
        "model_name_or_path": "model",
        "agent_backend": "claude_code",
        "eval_mode": "test_generation",
        "inference_input_hash": fingerprint,
    }

    assert prediction_matches_backend(
        row,
        "claude_code",
        "model",
        eval_mode="test_generation",
        input_hash=fingerprint,
    )
    changed = json.loads(json.dumps(instance))
    changed["problem_statement"] = "changed issue"
    assert not prediction_matches_backend(
        row,
        "claude_code",
        "model",
        eval_mode="test_generation",
        input_hash=inference_input_hash(changed),
    )
    legacy = {key: value for key, value in row.items() if key != "inference_input_hash"}
    assert not prediction_matches_backend(
        legacy,
        "claude_code",
        "model",
        eval_mode="test_generation",
        input_hash=fingerprint,
    )


def test_hidden_paths_cover_stale_worktrees_and_neighbouring_checkouts(tmp_path, monkeypatch):
    """opus5.5/astra: agents listed `.sanitizer_eval_workspace/*` and earlier
    runs' checkouts under swebench-inference-<uid>/ and imported Biopython from
    one of them."""
    monkeypatch.setenv("SWE_AGENT_TMPDIR", str(tmp_path / "work"))
    stale = tmp_path / "work" / "claude-offline-full" / "run_old"
    stale.mkdir(parents=True)
    config = tmp_path / "work" / "codex-config" / "codex_home_live"
    config.mkdir(parents=True)
    output = tmp_path / "outputs" / "run" / "agent_predictions.jsonl"
    output.parent.mkdir(parents=True)

    hidden = inference_hidden_paths(output)

    assert str(stale.resolve()) in hidden
    assert str(config.resolve()) not in hidden
    # a worktree created after the list was computed is not hidden from its run
    fresh = tmp_path / "work" / "codex" / "run_new"
    fresh.mkdir(parents=True)
    assert str(fresh.resolve()) not in hidden
