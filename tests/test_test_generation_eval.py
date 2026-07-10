from swebench.eval_pipeline.prompt_builder import build_agent_prompt
from swebench.eval_pipeline.test_generation_eval import classify_test_generation_result


def test_test_generation_prompt_requests_tests_only():
    prompt = build_agent_prompt(
        {
            "instance_id": "demo__repo-1",
            "repo": "demo/repo",
            "problem_statement": "Bug report",
        },
        eval_mode="test_generation",
    )

    assert "regression test" in prompt
    assert "Do not fix the bug" in prompt
    assert "Return only a valid unified git diff" in prompt


def test_test_generation_classifies_strict_fail_then_pass():
    result = classify_test_generation_result(
        {"tests/test_bug.py::test_bug": "FAILED"},
        {"tests/test_bug.py::test_bug": "PASSED"},
        test_patch_applied=True,
        gold_patch_applied=True,
    )

    assert result["status"] == "resolved"
    assert result["base_failed_tests"] == ["tests/test_bug.py::test_bug"]
    assert result["gold_passed_tests"] == ["tests/test_bug.py::test_bug"]


def test_test_generation_rejects_pass_on_base():
    result = classify_test_generation_result(
        {"tests/test_bug.py::test_bug": "PASSED"},
        {"tests/test_bug.py::test_bug": "PASSED"},
        test_patch_applied=True,
        gold_patch_applied=True,
    )

    assert result["status"] == "unresolved"


def test_test_generation_marks_apply_failure_errored():
    result = classify_test_generation_result(
        {},
        {},
        test_patch_applied=False,
        gold_patch_applied=False,
    )

    assert result["status"] == "errored"


def test_test_generation_marks_placeholder_specs_excluded():
    result = classify_test_generation_result(
        {},
        {},
        test_patch_applied=True,
        gold_patch_applied=True,
        non_evaluable=True,
    )

    assert result["status"] == "excluded"
    assert result["failure_reason"] == "non_evaluable_spec"


def test_test_generation_marks_zero_selected_not_exercised():
    result = classify_test_generation_result(
        {},
        {},
        test_patch_applied=True,
        gold_patch_applied=True,
        no_tests_selected=True,
    )

    assert result["status"] == "not_exercised"
    assert result["failure_reason"] == "no_tests_selected"
