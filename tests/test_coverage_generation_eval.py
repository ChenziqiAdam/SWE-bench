import json

import pytest

from swebench.eval_pipeline.coverage_generation_eval import (
    _is_flaky,
    _is_test_path,
    _phase_script,
    classify_coverage_result,
    infer_coverage_targets,
    inspect_test_patch,
    parse_coverage_json,
    parse_mutation_results,
    mutation_exit_is_fatal,
)
from swebench.eval_pipeline.prompt_builder import build_agent_prompt


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


@pytest.mark.parametrize("path", ["pyproject.toml", "src/pkg/core.py"])
def test_non_test_changes_are_invalid(path):
    info = {"tests_only_patch": False}
    assert classify_coverage_result({}, {}, info, 0, 0, True, False) == (
        "invalid", "production_or_non_test_files_modified"
    )
