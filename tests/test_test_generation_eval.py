import json

from swebench.eval_pipeline.prompt_builder import build_agent_prompt
from swebench.eval_pipeline.test_generation_eval import (
    BUILD_FAIL,
    GOLD_APPLY_PASS,
    GEN_APPLY_PASS,
    _build_script,
    _evaluate_one,
    _no_tests_selected,
    _openmm_generated_pytest_targets,
    _test_command,
    classify_test_generation_result,
)


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


def test_test_generation_marks_build_failure_errored():
    result = classify_test_generation_result(
        {}, {}, True, True, build_failed=True
    )

    assert result["status"] == "errored"
    assert result["failure_reason"] == "generated_test_build_failed"


def test_base_build_failure_resolves_when_gold_tests_pass():
    result = classify_test_generation_result(
        {},
        {"TestNewAPI": "PASSED"},
        True,
        True,
        base_build_failed=True,
    )

    assert result == {
        "status": "resolved",
        "failure_reason": "",
        "base_failed_tests": ["generated_test_build"],
        "gold_passed_tests": ["generated_test_build"],
    }


def test_gold_build_failure_remains_errored():
    result = classify_test_generation_result(
        {"TestNewAPI": "FAILED"},
        {},
        True,
        True,
        gold_build_failed=True,
    )

    assert result["status"] == "errored"
    assert result["failure_reason"] == "generated_test_build_failed"


def test_test_generation_reports_patch_failure_before_secondary_build_failure():
    result = classify_test_generation_result(
        {}, {}, False, True, build_failed=True
    )

    assert result["failure_reason"] == "test_patch_failed_or_timeout"


def test_no_curated_target_is_not_exercised():
    assert _no_tests_selected("openmm#5031 has no curated generated-test target")


def test_gold_script_applies_gold_before_generated_test(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {"demo/repo": {"1": {"build": ["make tests"], "test_cmd": "run"}}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: "run",
    )
    script = _build_script(
        {"repo": "demo/repo", "version": "1", "base_commit": "abc"},
        "patch",
        apply_gold=True,
    )

    assert script.index(GOLD_APPLY_PASS) < script.index(GEN_APPLY_PASS)
    assert f"make tests || {{ echo {BUILD_FAIL}; exit 13; }}" in script


def test_openmm_test_generation_runs_touched_pytest_file_not_fixed_selector(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: [
            "cd wrappers/python/tests && python -m pytest -xvs "
            "TestForceField.py -k 'original_test'"
        ],
    )
    patch = """diff --git a/wrappers/python/tests/TestForceField.py b/wrappers/python/tests/TestForceField.py
--- a/wrappers/python/tests/TestForceField.py
+++ b/wrappers/python/tests/TestForceField.py
@@ -1 +1,2 @@
 pass
+def test_generated_regression(): pass
"""

    command = _test_command(
        {"repo": "openmm/openmm", "test_patch": ""},
        patch,
    )

    assert "python -m pip install --no-cache-dir openmm numpy scipy pytest" in command
    assert "mkdir -p \"$SIMTK_SITE\"" in command
    assert "rm -rf \"$SIMTK_SITE/app\"" in command
    assert "compiled*" in command
    assert "from openmm.vec3 import *" in command
    assert "from openmm.unit import *" in command
    assert "wrappers/python/openmm/*.py" in command
    assert "wrappers/python/simtk/unit" in command
    assert "python -m lib2to3 -w -n \"$SIMTK_SITE/app\"" in command
    assert command.index("/testbed/wrappers/python/openmm/app") < command.index(
        "/testbed/wrappers/python/simtk/openmm/app"
    )
    assert command.endswith(
        "cd wrappers/python/tests && python -m pytest -xvs "
        "TestForceField.py::test_generated_regression"
    )
    assert "-k 'original_test'" not in command


def test_openmm_test_generation_can_force_native_spec_command(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {
            "openmm/openmm": {
                "1": {
                    "test_cmd": ["./build/TestReferenceCustomIntegrator"],
                    "test_generation_use_spec_cmd": True,
                }
            }
        },
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: ["./build/TestReferenceCustomIntegrator"],
    )
    patch = """diff --git a/wrappers/python/tests/TestIntegrators.py b/wrappers/python/tests/TestIntegrators.py
--- a/wrappers/python/tests/TestIntegrators.py
+++ b/wrappers/python/tests/TestIntegrators.py
@@ -1 +1,2 @@
+def test_generated(): pass
"""

    command = _test_command(
        {"repo": "openmm/openmm", "version": "1", "test_patch": ""}, patch
    )

    assert command == "./build/TestReferenceCustomIntegrator"


def test_openmm_test_generation_runs_added_unittest_method_nodeids():
    patch = """diff --git a/wrappers/python/tests/TestForceField.py b/wrappers/python/tests/TestForceField.py
--- a/wrappers/python/tests/TestForceField.py
+++ b/wrappers/python/tests/TestForceField.py
@@ -845,5 +845,13 @@ class TestForceField(unittest.TestCase):
+    def test_Disulfides(self):
+        pass
 class AmoebaTestForceField(unittest.TestCase):
"""

    assert _openmm_generated_pytest_targets(patch) == (
        ["TestForceField.py::TestForceField::test_Disulfides"],
        None,
    )


def test_openmm_test_generation_falls_back_to_touched_pytest_file():
    patch = """diff --git a/wrappers/python/tests/TestForceField.py b/wrappers/python/tests/TestForceField.py
--- a/wrappers/python/tests/TestForceField.py
+++ b/wrappers/python/tests/TestForceField.py
@@ -654,6 +654,9 @@ class TestForceField(unittest.TestCase):
+        assert True
"""

    assert _openmm_generated_pytest_targets(patch) == (["TestForceField.py"], None)


def test_openmm_test_generation_falls_back_when_method_class_unknown():
    patch = '''diff --git a/wrappers/python/tests/TestForceField.py b/wrappers/python/tests/TestForceField.py
--- a/wrappers/python/tests/TestForceField.py
+++ b/wrappers/python/tests/TestForceField.py
@@ -1019,6 +1019,10 @@ END"""))
+    def test_CharmmPolar(self):
+        pass
'''

    assert _openmm_generated_pytest_targets(patch) == (
        ["TestForceField.py"],
        "test_CharmmPolar",
    )


def test_evaluation_exception_records_failure_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.make_test_spec",
        lambda _instance: (_ for _ in ()).throw(RuntimeError("image build failed")),
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.cleanup_container",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.close_logger",
        lambda *_args: None,
    )

    result = _evaluate_one(
        {"instance_id": "demo__repo-1"},
        {"model_patch": "diff --git a/a b/a", "model_name_or_path": "model"},
        "run",
        object(),
        str(tmp_path),
        1,
    )

    assert result["status"] == "errored"
    assert result["failure_reason"] == "evaluation_exception"
    report = json.loads(
        (tmp_path / "run/model/demo__repo-1/report.json").read_text()
    )
    assert "image build failed" in report["demo__repo-1"]["error"]
