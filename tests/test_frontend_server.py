"""Tests for frontend/server.py API endpoints."""
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    """TestClient wired to a temp outputs/ dir with fixture data."""
    # Build minimal fixture data
    run_dir = tmp_path / "my_run"
    run_dir.mkdir()

    instances = [
        {
            "instance_id": "scipy__scipy-100",
            "repo": "scipy/scipy",
            "pull_number": 100,
            "base_commit": "abc123",
            "patch": "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
            "test_patch": "",
            "problem_statement": "Fix the zeta function",
            "hints_text": "",
            "created_at": "2024-01-01T00:00:00",
            "version": "1.0",
            "FAIL_TO_PASS": ["test_zeta"],
            "PASS_TO_PASS": ["test_other"],
            "environment_setup_commit": "abc123",
            "pr_title": "Add zeta function",
            "pr_body": "Implements the Riemann zeta function.",
            "paper_reference": "Riemann 1859",
            "issue_numbers": [],
            "category": "new_algorithm",
            "algorithm_name": "Riemann Zeta",
            "file_contents": {"scipy/special/zeta.py": "# placeholder"},
        },
        {
            "instance_id": "numpy__numpy-200",
            "repo": "numpy/numpy",
            "pull_number": 200,
            "base_commit": "def456",
            "patch": "diff --git a/bar.py b/bar.py\n",
            "test_patch": "",
            "problem_statement": "Fix einsum",
            "hints_text": "",
            "created_at": "2024-02-01T00:00:00",
            "version": "2.0",
            "FAIL_TO_PASS": ["test_einsum"],
            "PASS_TO_PASS": [],
            "environment_setup_commit": "def456",
            "pr_title": "Fix einsum",
            "pr_body": "Fixes einsum contraction.",
            "paper_reference": "",
            "issue_numbers": [],
            "category": "fix_wrong_implementation",
            "algorithm_name": "",
            "file_contents": {},
        },
    ]
    with open(run_dir / "instances.jsonl", "w") as f:
        for inst in instances:
            f.write(json.dumps(inst) + "\n")

    preds_l1 = [
        {"instance_id": "scipy__scipy-100", "model_patch": "diff l1", "model_name_or_path": "claude", "full_output": "raw output l1"},
    ]
    with open(run_dir / "level1_predictions.jsonl", "w") as f:
        for p in preds_l1:
            f.write(json.dumps(p) + "\n")

    with open(run_dir / "level2_predictions.jsonl", "w") as f:
        f.write(json.dumps({"instance_id": "scipy__scipy-100", "model_patch": "diff l2", "model_name_or_path": "claude", "full_output": "raw output l2"}) + "\n")

    with open(run_dir / "agent_predictions.selected.jsonl", "w") as f:
        f.write(json.dumps({
            "instance_id": "scipy__scipy-100",
            "model_patch": "diff generated test",
            "model_name_or_path": "test-model",
            "eval_mode": "test_generation",
        }) + "\n")

    trajectory_dir = run_dir / "claude_code_logs"
    trajectory_dir.mkdir()
    trajectory = [
        {"type": "system", "subtype": "init", "session_id": "session-1", "model": "test-model", "cwd": "/work"},
        {"type": "system", "subtype": "thinking_tokens", "token_count": 4},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "I will inspect the tests."}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "2 passed", "is_error": False}]}},
        {"type": "result", "subtype": "success", "num_turns": 2},
    ]
    with open(trajectory_dir / "scipy__scipy-100.jsonl", "w") as f:
        for event in trajectory:
            f.write(json.dumps(event) + "\n")
    with open(trajectory_dir / "scipy__scipy-100.attempt-1.jsonl", "w") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "attempt one"}]}}) + "\n")

    # level3 absent (no file) — tests graceful handling

    # CSV eval results
    csv_content = "instance_id,repo,pr_number,category,buildable,level1_resolved,level2_resolved,level3_resolved\n"
    csv_content += "scipy__scipy-100,scipy/scipy,100,new_algorithm,yes,PASS,FAIL,FAIL\n"
    with open(run_dir / "eval_results.csv", "w") as f:
        f.write(csv_content)

    # Second run with no eval CSV
    run2_dir = tmp_path / "run2"
    run2_dir.mkdir()
    with open(run2_dir / "instances.jsonl", "w") as f:
        f.write(json.dumps(instances[0]) + "\n")

    # Import server with patched OUTPUTS_DIR
    import frontend.server as srv
    original_outputs = srv.OUTPUTS_DIR
    original_logs = srv.LOGS_DIR
    srv.OUTPUTS_DIR = tmp_path
    srv.LOGS_DIR = tmp_path / "evaluation_logs"
    yield TestClient(srv.app)
    srv.OUTPUTS_DIR = original_outputs
    srv.LOGS_DIR = original_logs


# ── /api/runs ─────────────────────────────────────────────────────────────────

def test_list_runs_returns_dirs_with_instances_jsonl(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert set(runs) == {"my_run", "run2"}


# ── /api/runs/{run}/overview ──────────────────────────────────────────────────

def test_overview_returns_one_row_per_instance(client):
    resp = client.get("/api/runs/my_run/overview")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2


def test_overview_row_has_required_fields(client):
    resp = client.get("/api/runs/my_run/overview")
    row = next(r for r in resp.json() if r["instance_id"] == "scipy__scipy-100")
    assert row["repo"] == "scipy/scipy"
    assert row["category"] == "new_algorithm"
    assert row["algorithm_name"] == "Riemann Zeta"
    assert row["has_level1"] is True
    assert row["has_level2"] is True
    assert row["has_level3"] is False


def test_overview_merges_eval_results(client):
    resp = client.get("/api/runs/my_run/overview")
    row = next(r for r in resp.json() if r["instance_id"] == "scipy__scipy-100")
    assert row["buildable"] == "yes"
    assert row["level1_resolved"] == "PASS"
    assert row["level2_resolved"] == "FAIL"


def test_overview_reports_trajectory_availability(client):
    rows = client.get("/api/runs/my_run/overview").json()
    scipy = next(r for r in rows if r["instance_id"] == "scipy__scipy-100")
    numpy = next(r for r in rows if r["instance_id"] == "numpy__numpy-200")
    assert scipy["has_trajectory"] is True
    assert numpy["has_trajectory"] is False


def test_overview_unknown_run_returns_404(client):
    resp = client.get("/api/runs/nonexistent/overview")
    assert resp.status_code == 404


# ── /api/runs/{run}/instance/{id} ─────────────────────────────────────────────

def test_instance_detail_has_instance_metadata(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100")
    assert resp.status_code == 200
    data = resp.json()
    inst = data["instance"]
    assert inst["instance_id"] == "scipy__scipy-100"
    assert inst["repo"] == "scipy/scipy"
    assert inst["pull_number"] == 100
    assert inst["pr_title"] == "Add zeta function"


def test_instance_detail_strips_file_contents(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100")
    inst = resp.json()["instance"]
    assert "file_contents" not in inst


def test_instance_detail_has_level_prompts(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100")
    levels = resp.json()["levels"]
    assert "1" in levels
    assert "2" in levels
    prompt1 = levels["1"]["prompt"]
    assert "Add zeta function" in prompt1  # PR title in level1 prompt
    prompt2 = levels["2"]["prompt"]
    assert "Fix the zeta function" in prompt2  # problem_statement in level2 prompt


def test_instance_detail_level3_prompt_when_paper_reference_present(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100")
    levels = resp.json()["levels"]
    assert "3" in levels
    assert levels["3"]["prompt"] is not None
    assert "Riemann 1859" in levels["3"]["prompt"]


def test_instance_detail_level3_prompt_none_when_no_paper_reference(client):
    resp = client.get("/api/runs/my_run/instance/numpy__numpy-200")
    levels = resp.json()["levels"]
    assert levels["3"]["prompt"] is None


def test_instance_detail_has_predictions(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100")
    levels = resp.json()["levels"]
    assert levels["1"]["model_patch"] == "diff l1"
    assert levels["1"]["full_output"] == "raw output l1"
    assert levels["1"]["model_name_or_path"] == "claude"


def test_instance_detail_compares_agent_and_gold_tests(client):
    data = client.get("/api/runs/my_run/instance/scipy__scipy-100").json()
    assert data["comparison"]["agent_test_patch"] == "diff generated test"
    assert data["comparison"]["gold_test_patch"] == ""
    assert data["comparison"]["model_name"] == "test-model"


def test_instance_detail_missing_prediction_is_none(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100")
    levels = resp.json()["levels"]
    assert levels["3"]["model_patch"] is None
    assert levels["3"]["full_output"] is None


def test_instance_detail_unknown_id_returns_404(client):
    resp = client.get("/api/runs/my_run/instance/does__not-exist")
    assert resp.status_code == 404


def test_instance_detail_unknown_run_returns_404(client):
    resp = client.get("/api/runs/nonexistent/instance/scipy__scipy-100")
    assert resp.status_code == 404


# ── /api/runs/{run}/instance/{id}/trajectory ─────────────────────────────────

def test_trajectory_filters_token_events_and_pairs_tool_results(client):
    resp = client.get("/api/runs/my_run/instance/scipy__scipy-100/trajectory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["raw_line_count"] == 6
    assert data["summary"]["ignored_thinking_token_events"] == 1
    assert data["summary"]["terminal_result_seen"] is True
    assert data["summary"]["completion"] == "completed"
    tool = next(event for event in data["events"] if event["kind"] == "tool")
    assert tool["name"] == "Bash"
    assert tool["input"]["command"] == "pytest -q"
    assert tool["result"]["content"] == "2 passed"


def test_trajectory_lists_and_selects_attempt_sources(client):
    base = client.get("/api/runs/my_run/instance/scipy__scipy-100/trajectory").json()
    assert base["sources"] == [
        "scipy__scipy-100.jsonl",
        "scipy__scipy-100.attempt-1.jsonl",
    ]
    attempt = client.get(
        "/api/runs/my_run/instance/scipy__scipy-100/trajectory",
        params={"source": "scipy__scipy-100.attempt-1.jsonl"},
    ).json()
    assert attempt["summary"]["completion"] == "interrupted"
    assert attempt["events"][0]["text"] == "attempt one"


def test_trajectory_missing_and_invalid_sources(client):
    missing = client.get("/api/runs/my_run/instance/numpy__numpy-200/trajectory")
    assert missing.status_code == 404
    invalid = client.get(
        "/api/runs/my_run/instance/scipy__scipy-100/trajectory",
        params={"source": "../secret.jsonl"},
    )
    assert invalid.status_code == 400
