import json
import subprocess
import sys

import pytest

from swebench.eval_pipeline.coverage_generation_eval import (
    _is_flaky,
    _is_test_path,
    _phase_script,
    _standalone_mutation_script,
    _standalone_phase_script,
    classify_coverage_result,
    format_baseline_coverage_report,
    infer_coverage_targets,
    inspect_test_patch,
    parse_coverage_json,
    parse_mutation_results,
    run_standalone_coverage_evaluation,
    select_mutation_targets,
    standalone_baseline_failure,
    mutation_exit_is_fatal,
)
from swebench.eval_pipeline.prompt_builder import build_agent_prompt
from swebench.eval_pipeline.run_pipeline import _standalone_coverage_instance, parse_args


def test_standalone_default_setup_uses_editable_install(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline"])
    args = parse_args()
    assert args.coverage_setup_command == "python -m pip install -e . pytest"


def test_biopython_profile_builds_extensions_and_uses_offline_runner(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--repo_url",
            "https://github.com/biopython/biopython.git",
            "--base_commit",
            "8ef753085b11520207d5a8f6122e6fb53fddedba",
        ],
    )
    instance = _standalone_coverage_instance(parse_args())
    assert "build_ext --inplace" in instance["coverage_setup_command"]
    assert instance["coverage_test_command"] == "python Tests/run_tests.py --offline"
    assert "--source=Bio" in instance["coverage_command"]
    assert "Tests/run_tests.py --offline" in instance["coverage_command"]


def test_coverage_prompt_names_target_and_tests_only_constraints():
    prompt = build_agent_prompt(
        {
            "instance_id": "demo__repo-1",
            "repo": "demo/repo",
            "problem_statement": "Scientific context",
            "coverage_targets": ["src/package/target_module.py"],
        },
        eval_mode="coverage_generation",
    )

    assert "src/package/target_module.py" in prompt
    assert "Only add or modify test files" in prompt
    assert "scientific invariants" in prompt


def test_coverage_prompt_does_not_require_issue_text():
    prompt = build_agent_prompt(
        {
            "instance_id": "demo__repo-1",
            "repo": "demo/repo",
            "problem_statement": "",
            "coverage_targets": ["src/package/target_module.py"],
        },
        eval_mode="coverage_generation",
    )
    assert prompt is not None
    assert "Background issue context" not in prompt
    assert "<issue>" not in prompt


def test_coverage_prompt_includes_standalone_repository_commands():
    prompt = build_agent_prompt(
        {
            "instance_id": "standalone__demo-1",
            "repo": "https://github.com/example/science.git",
            "problem_statement": "",
            "coverage_targets": ["src/science/core.py"],
            "coverage_setup_command": "python -m pip install .",
            "coverage_test_command": "python -m pytest -q",
            "baseline_coverage_report": "Repository totals: line 42.00%",
        },
        eval_mode="coverage_generation",
    )
    assert "Environment setup command: python -m pip install ." in prompt
    assert "Complete test command: python -m pytest -q" in prompt
    assert "Repository totals: line 42.00%" in prompt


def test_repository_coverage_aggregates_production_files_and_selects_improvements():
    payload = json.dumps({"files": {
        "pkg/core.py": {"summary": {
            "covered_lines": 2, "num_statements": 4,
            "covered_branches": 0, "num_branches": 2,
        }},
        "pkg/other.py": {"summary": {
            "covered_lines": 3, "num_statements": 3,
            "covered_branches": 0, "num_branches": 0,
        }},
        "tests/test_core.py": {"summary": {
            "covered_lines": 10, "num_statements": 10,
            "covered_branches": 0, "num_branches": 0,
        }},
    }})
    before = parse_coverage_json(payload, [])
    assert before["scope"] == "repository"
    assert before["target_file_count"] == 2
    assert "tests/test_core.py" not in before["files"]
    after = json.loads(json.dumps(before))
    after["files"]["pkg/core.py"]["covered_lines"] = 3
    assert select_mutation_targets(before, after) == ["pkg/core.py"]
    assert "pkg/core.py" in format_baseline_coverage_report(before)


def test_targets_default_to_python_implementation_files():
    instance = {
        "file_contents": {
            "src/pkg/core.py": "",
            "src/pkg/testing/helpers.py": "",
            "numpy/testing/utils.py": "",
            "tests/test_core.py": "",
            "src/pkg/native.cpp": "",
        }
    }
    assert infer_coverage_targets(instance) == [
        "numpy/testing/utils.py",
        "src/pkg/core.py",
        "src/pkg/testing/helpers.py",
    ]


def test_patch_inspection_counts_tests_assertions_and_illegal_files():
    patch = """diff --git a/tests/test_core.py b/tests/test_core.py
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -1,0 +1,3 @@
+def test_edge_case():
+    value = 1
+    assert value == 1
diff --git a/src/pkg/core.py b/src/pkg/core.py
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1 +1 @@
-OLD = 1
+OLD = 2
"""
    result = inspect_test_patch(patch)
    assert result["tests_only_patch"] is False
    assert result["illegal_changed_files"] == ["src/pkg/core.py"]
    assert result["added_test_count"] == 1
    assert result["added_assertion_count"] == 1
    assert result["no_existing_test_lines_removed"] is False
    assert result["preserves_existing_test_behavior"] is False


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_core.py", True),
        ("tests/data/reference.csv", True),
        ("pkg/core_test.py", True),
        ("numpy/testing/utils.py", False),
        ("src/testing/helpers.py", False),
        ("tests/conftest.py", False),
        ("tests/pyproject.toml", False),
    ],
)
def test_test_path_scope_is_conservative(path, expected):
    assert _is_test_path(path) is expected


def test_patch_inspection_recognizes_scientific_assertions_and_expected_errors():
    patch = """diff --git a/tests/test_science.py b/tests/test_science.py
--- a/tests/test_science.py
+++ b/tests/test_science.py
@@ -0,0 +1,8 @@
+def test_numerics():
+    np.testing.assert_allclose(actual, expected)
+    assert_allclose(actual, expected)
+    npt.assert_array_equal(actual, expected)
+
+def test_domain_error():
+    with pytest.raises(ValueError):
+        calculate_invalid_state()
"""
    info = inspect_test_patch(patch)
    assert info["tests_only_patch"] is True
    assert info["added_assertion_count"] == 4


def test_rename_from_production_into_tests_is_still_illegal():
    patch = """diff --git a/src/pkg/core.py b/tests/test_core.py
similarity index 100%
rename from src/pkg/core.py
rename to tests/test_core.py
"""
    info = inspect_test_patch(patch)
    assert info["tests_only_patch"] is False
    assert info["illegal_changed_files"] == ["src/pkg/core.py"]


def test_parses_target_coverage_and_mutation_score():
    payload = json.dumps({
        "files": {
            "src/pkg/core.py": {"summary": {
                "covered_lines": 8, "num_statements": 10,
                "covered_branches": 3, "num_branches": 4,
            }},
            "src/pkg/other.py": {"summary": {
                "covered_lines": 1, "num_statements": 100,
                "covered_branches": 0, "num_branches": 0,
            }},
        }
    })
    coverage = parse_coverage_json(payload, ["src/pkg/core.py"])
    mutation = parse_mutation_results("Killed: 7\nSurvived: 2\nTimeout: 1")
    assert coverage["line_coverage"] == 80.0
    assert coverage["branch_coverage"] == 75.0
    assert mutation["score"] == 70.0
    assert mutation["score_killed_or_timeout"] == 80.0
    assert mutation["score_definition"].startswith("100 * killed")


def test_parses_mutmut_two_emoji_summary():
    mutation = parse_mutation_results("3/3  🎉 2  ⏰ 0  🤔 0  🙁 1  🔇 0")
    assert mutation["killed"] == 2
    assert mutation["survived"] == 1
    assert mutation["score"] == pytest.approx(66.6666667)


def test_classification_requires_valid_passing_improvement():
    before = {"line_coverage": 50.0, "branch_coverage": 25.0}
    after = {"line_coverage": 60.0, "branch_coverage": 25.0}
    patch_info = {
        "tests_only_patch": True,
        "preserves_existing_test_behavior": True,
        "added_assertion_count": 1,
    }
    assert classify_coverage_result(before, after, patch_info, 0, 0, True, False) == (
        "resolved", ""
    )
    assert classify_coverage_result(before, after, patch_info, 0, 1, True, False) == (
        "unresolved", "tests_failed_after_patch"
    )


def test_mutation_improvement_can_resolve_without_coverage_delta():
    coverage = {"line_coverage": 50.0, "branch_coverage": 25.0}
    patch_info = {
        "tests_only_patch": True,
        "preserves_existing_test_behavior": True,
        "added_assertion_count": 1,
    }
    result = classify_coverage_result(
        coverage, coverage, patch_info, 0, 0, True, False,
        mutation_before={"score": 20.0},
        mutation_after={"score": 40.0},
    )
    assert result == ("resolved", "")


def test_flakiness_is_compared_separately_before_and_after_patch():
    coverage = {"line_coverage": 50.0, "branch_coverage": 25.0}
    improved = {"line_coverage": 60.0, "branch_coverage": 25.0}
    patch_info = {
        "tests_only_patch": True,
        "no_existing_test_lines_removed": True,
        "added_assertion_count": 1,
    }
    assert classify_coverage_result(
        coverage, improved, patch_info, 0, 0, True, False, baseline_flaky=True
    ) == ("excluded", "baseline_test_suite_flaky")
    assert classify_coverage_result(
        coverage, improved, patch_info, 0, 0, True, False, generated_tests_flaky=True
    ) == ("unresolved", "flaky_generated_tests")
    assert _is_flaky(0, [0, 1]) is True
    assert _is_flaky(0, [0, 0]) is False


def test_mutmut_nonzero_outcomes_are_not_all_tool_errors():
    assert mutation_exit_is_fatal(0) is False
    assert mutation_exit_is_fatal(2) is False  # survivors
    assert mutation_exit_is_fatal(4) is False  # timeouts
    assert mutation_exit_is_fatal(1) is True
    assert mutation_exit_is_fatal(None) is True


def test_phase_script_repeats_both_phases_and_guards_old_python(monkeypatch):
    monkeypatch.setitem(
        __import__(
            "swebench.eval_pipeline.coverage_generation_eval", fromlist=["MAP_REPO_VERSION_TO_SPECS"]
        ).MAP_REPO_VERSION_TO_SPECS,
        "demo/repo",
        {"1": {}},
    )
    instance = {
        "repo": "demo/repo",
        "version": "1",
        "base_commit": "abc123",
        "coverage_targets": ["src/pkg/core.py"],
    }
    before = _phase_script(instance, False, 2)
    after = _phase_script(instance, True, 2)
    assert "REPEAT_RUN_1_EXIT" in before
    assert "REPEAT_RUN_2_EXIT" in after
    assert "MUTATION_UNSUPPORTED_PYTHON=1" in before
    assert "'coverage<6' 'mutmut<2'" in before


def test_standalone_script_uses_repo_commands_without_swebench_paths(tmp_path):
    instance = {
        "base_commit": "abc123",
        "coverage_targets": [],
        "coverage_setup_command": "python -m pip install -e .",
        "coverage_test_command": "python -m pytest -q",
    }
    script = _standalone_phase_script(instance, tmp_path / "test.patch", True, 1)
    assert "/testbed" not in script
    assert "python -m pip install -e ." in script
    assert "python -m pytest -q" in script
    assert "COVERAGE_TEST_PATCH_APPLIED" in script
    assert str((tmp_path / "test.patch").resolve()) in script
    assert "pip install --disable-pip-version-check pytest coverage" in script
    completed = subprocess.run(["bash", "-n"], input=script, text=True)
    assert completed.returncode == 0


def test_standalone_mutation_script_is_scoped_to_selected_modules(tmp_path):
    instance = {
        "base_commit": "abc123",
        "coverage_setup_command": "true",
        "coverage_tool_install_command": "true",
        "mutation_command": "mutation-tool --paths {targets}",
        "mutation_results_command": "mutation-tool results",
    }
    script = _standalone_mutation_script(
        instance, tmp_path / "test.patch", False, ["pkg/core.py", "pkg/math.py"]
    )
    assert "mutation-tool --paths pkg/core.py,pkg/math.py" in script
    completed = subprocess.run(["bash", "-n"], input=script, text=True)
    assert completed.returncode == 0


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"timed_out": True}, "baseline_timeout"),
        ({"setup_exit": 1}, "baseline_repository_setup_failed"),
        ({"tools_exit": 1}, "baseline_test_or_coverage_tools_unavailable"),
        ({"test_exit": 1}, "baseline_tests_failed"),
        ({"coverage_test_exit": 1}, "baseline_coverage_test_failed"),
        ({"coverage": None}, "baseline_coverage_unavailable"),
        ({"repeat_exits": [0, 1]}, "baseline_test_suite_flaky_or_failed"),
    ],
)
def test_invalid_standalone_baseline_stops_before_inference(override, reason):
    baseline = {
        "timed_out": False,
        "setup_exit": 0,
        "tools_exit": 0,
        "test_exit": 0,
        "coverage_test_exit": 0,
        "coverage": {"files": {}},
        "repeat_exits": [0, 0],
        **override,
    }
    assert standalone_baseline_failure(baseline) == reason


def test_valid_standalone_baseline_can_reach_inference():
    assert standalone_baseline_failure({
        "timed_out": False,
        "setup_exit": 0,
        "tools_exit": 0,
        "test_exit": 0,
        "coverage_test_exit": 0,
        "coverage": {"files": {}},
        "repeat_exits": [0, 0],
    }) == ""


def test_standalone_empty_prediction_preserves_error_and_baseline(tmp_path):
    instance = {
        "instance_id": "standalone__demo-empty",
        "repo": "demo/repo",
        "repo_url": "https://github.com/demo/repo.git",
        "base_commit": "a" * 40,
        "coverage_targets": [],
    }
    baseline_coverage = {"line_coverage": 78.0, "branch_coverage": 68.0}
    result = run_standalone_coverage_evaluation(
        instance,
        {
            "model_name_or_path": "demo-model",
            "model_patch": "",
            "error": "claude exited with code 1: missing prompt",
            "metrics": {"wall_time_seconds": 2.0},
        },
        run_id="standalone-test",
        log_dir=str(tmp_path / "logs"),
        baseline={
            "coverage": baseline_coverage,
            "runtime": 12.5,
            "setup_exit": 0,
            "tools_exit": 0,
            "test_exit": 0,
            "coverage_test_exit": 0,
            "repeat_exits": [0, 0],
        },
    )
    assert result["status"] == "no-pred"
    assert result["failure_reason"] == "claude exited with code 1: missing prompt"
    assert result["coverage_scope"] == "repository"
    assert result["coverage_before"] == baseline_coverage
    assert result["base_tests_passed"] is True
    assert result["before_wall_time_seconds"] == 12.5


def test_standalone_evaluation_runs_repo_before_and_after_without_issue(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "pkg").mkdir()
    (repo / "tests").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "core.py").write_text(
        "def classify(value):\n"
        "    if value > 0:\n"
        "        return 'positive'\n"
        "    return 'nonpositive'\n"
    )
    (repo / "tests" / "test_core.py").write_text(
        "from pkg.core import classify\n\n"
        "def test_positive():\n"
        "    assert classify(1) == 'positive'\n"
    )
    (repo / "make_coverage.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "improved = 'test_zero' in Path('tests/test_core.py').read_text()\n"
        "summary = {'covered_lines': 4 if improved else 3, 'num_statements': 4, "
        "'covered_branches': 2 if improved else 1, 'num_branches': 2}\n"
        "Path('/tmp/coverage-generation.json').write_text(json.dumps("
        "{'files': {'pkg/core.py': {'summary': summary}}}))\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        cwd=repo,
        check=True,
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    patch = """diff --git a/tests/test_core.py b/tests/test_core.py
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -3,2 +3,5 @@
 def test_positive():
     assert classify(1) == 'positive'
+
+def test_zero():
+    assert classify(0) == 'nonpositive'
"""
    instance = {
        "instance_id": "standalone__demo-1",
        "repo": repo.as_uri(),
        "repo_url": repo.as_uri(),
        "base_commit": commit,
        "coverage_targets": [],
        "coverage_setup_command": "true",
        "coverage_test_command": "python -m pytest -q",
        "coverage_command": "python make_coverage.py",
        "coverage_results_command": "true",
        "coverage_tool_install_command": "true",
        "mutation_command": "printf 'Killed: 1\\nSurvived: 1\\n'",
        "mutation_results_command": "true",
    }
    result = run_standalone_coverage_evaluation(
        instance,
        {
            "model_name_or_path": "demo-model",
            "model_patch": patch,
            "metrics": {"turns": 1},
        },
        run_id="standalone-test",
        log_dir=str(tmp_path / "logs"),
        timeout=120,
        flaky_runs=0,
    )
    assert result["status"] == "resolved"
    assert result["standalone"] is True
    assert result["base_tests_passed"] is True
    assert result["after_tests_passed"] is True
    assert result["coverage_line_delta"] > 0
    assert result["coverage_scope"] == "repository"
    assert result["mutation_targets"] == ["pkg/core.py"]
    assert result["mutation_before"]["score"] == 50.0


def test_repo_url_mode_bypasses_spreadsheet_and_issue_ingestion(tmp_path, monkeypatch):
    from swebench.eval_pipeline.run_pipeline import main

    monkeypatch.setattr(sys, "argv", [
        "run_pipeline",
        "--eval_mode", "coverage_generation",
        "--repo_url", "https://github.com/example/science.git",
        "--base_commit", "a" * 40,
        "--output_dir", str(tmp_path / "output"),
        "--run_id", "standalone-smoke",
        "--model", "demo-model",
        "--agent_backend", "claude_code",
        "--skip_inference",
        "--skip_eval",
    ])
    main()

    instance = json.loads((tmp_path / "output" / "instances.jsonl").read_text())
    assert instance["repo_url"] == "https://github.com/example/science.git"
    assert instance["coverage_targets"] == []
    assert instance["standalone"] is True
    assert instance["problem_statement"] == ""
    assert (tmp_path / "output" / "standalone-smoke_results.csv").exists()


@pytest.mark.parametrize("path", ["pyproject.toml", "src/pkg/core.py"])
def test_non_test_changes_are_invalid(path):
    info = {"tests_only_patch": False}
    assert classify_coverage_result({}, {}, info, 0, 0, True, False) == (
        "invalid", "production_or_non_test_files_modified"
    )
