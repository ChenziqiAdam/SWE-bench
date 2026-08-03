import json

from swebench.eval_pipeline.constants import COL_PR_NUMBER, COL_REPO
from swebench.eval_pipeline.instance_builder import build_all_instances


def test_checkpoint_superset_returns_only_requested_instances(tmp_path):
    selected = {"instance_id": "demo__repo-2083", "marker": "selected"}
    unrelated = {"instance_id": "openmm__openmm-1235", "marker": "unrelated"}
    checkpoint = tmp_path / "instances_checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps(unrelated) + "\n" + json.dumps(selected) + "\n"
    )

    instances = build_all_instances(
        [{COL_REPO: "demo/repo", COL_PR_NUMBER: 2083}],
        checkpoint_path=str(checkpoint),
    )

    assert instances == [selected]


def test_checkpoint_stale_zero_version_is_refreshed_from_pr_spec(
    monkeypatch, tmp_path
):
    checkpoint = tmp_path / "instances_checkpoint.jsonl"
    stale = {
        "instance_id": "demo__repo-42",
        "repo": "demo/repo",
        "pull_number": 42,
        "version": "0",
        "FAIL_TO_PASS": [],
    }
    checkpoint.write_text(json.dumps(stale) + "\n")
    monkeypatch.setattr(
        "swebench.eval_pipeline.instance_builder.MAP_REPO_VERSION_TO_SPECS",
        {"demo/repo": {"42": {}}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.instance_builder._spec_fail_to_pass",
        lambda _repo, _version: ["generated_regression"],
    )

    instances = build_all_instances(
        [{COL_REPO: "demo/repo", COL_PR_NUMBER: 42}],
        checkpoint_path=str(checkpoint),
    )

    assert instances[0]["version"] == "42"
    assert instances[0]["FAIL_TO_PASS"] == ["generated_regression"]
    persisted = json.loads(checkpoint.read_text())
    assert persisted["version"] == "42"
