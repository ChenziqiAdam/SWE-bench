import json
import sys

from swebench.eval_pipeline.prompt_builder import build_agent_prompt
from swebench.harness.constants.c import SPECS_OPENMM
from swebench.eval_pipeline.test_generation_eval import (
    BUILD_FAIL,
    GOLD_APPLY_PASS,
    GEN_APPLY_PASS,
    START_TEST_OUTPUT,
    _build_script,
    _exclude_gold_test_files,
    _evaluate_one,
    _infrastructure_failure_output,
    _no_tests_selected,
    _prepare_gold_patch,
    _qgis_isolated_python_command,
    _rdkit_isolated_cpp_commands,
    _rdkit_generated_unittest_targets,
    _rdkit_isolated_python_commands,
    _test_collection_failed,
    _test_execution_failed,
    _openmm_generated_pytest_targets,
    _test_command,
    _write_report_and_cleanup_instance_image,
    classify_test_generation_result,
    run_test_generation_evaluation,
)
from swebench.eval_pipeline.run_pipeline import parse_args


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
    assert "must add a new focused assertion" in prompt
    assert "non-empty patch" in prompt


def test_clean_images_cli_is_opt_in(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline"])
    assert parse_args().clean_images is False

    monkeypatch.setattr(sys, "argv", ["run_pipeline", "--clean_images"])
    assert parse_args().clean_images is True


def test_report_is_saved_before_instance_image_cleanup(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    events = []

    class FakeImages:
        def remove(self, image_name, force):
            assert json.loads(report_path.read_text()) == {"demo__repo-1": {"status": "resolved"}}
            events.append((image_name, force))

    class FakeSpec:
        instance_image_key = "sweb.eval.x86_64.demo__repo-1:latest"

    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.make_test_spec",
        lambda _instance: FakeSpec(),
    )
    _write_report_and_cleanup_instance_image(
        report_path,
        {"demo__repo-1": {"status": "resolved"}},
        {"instance_id": "demo__repo-1"},
        type("FakeClient", (), {"images": FakeImages()})(),
        clean_images=True,
    )

    assert events == [("sweb.eval.x86_64.demo__repo-1:latest", True)]


def test_report_cleanup_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.make_test_spec",
        lambda _instance: (_ for _ in ()).throw(AssertionError("unexpected cleanup")),
    )
    report_path = tmp_path / "report.json"
    _write_report_and_cleanup_instance_image(
        report_path,
        {"demo__repo-1": {"status": "resolved"}},
        {"instance_id": "demo__repo-1"},
        object(),
        clean_images=False,
    )

    assert report_path.exists()


def test_evaluation_runner_propagates_clean_images(monkeypatch, tmp_path):
    calls = []

    class FakeClient:
        def close(self):
            pass

    def fake_evaluate(*args):
        calls.append(args[-1])
        return {"status": "resolved"}

    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.docker.from_env",
        lambda: FakeClient(),
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval._prediction_map",
        lambda _path: {"demo__repo-1": {"model_patch": "patch"}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval._evaluate_one", fake_evaluate
    )

    run_test_generation_evaluation(
        [{"instance_id": "demo__repo-1"}],
        tmp_path / "predictions.jsonl",
        "run",
        max_workers=1,
        clean_images=True,
    )

    assert calls == [True]


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


def test_test_generation_marks_infrastructure_failures_excluded():
    result = classify_test_generation_result(
        {},
        {},
        test_patch_applied=True,
        gold_patch_applied=True,
        infrastructure_failed=True,
        gold_build_failed=True,
    )

    assert result["status"] == "excluded"
    assert result["failure_reason"] == "infrastructure_failure"


def test_scientific_infrastructure_failure_markers_are_narrow():
    for output in (
        "fatal error: GL/gl.h: No such file or directory",
        "error: unknown target CPU 'generic'",
        "ninja: fatal: posix_spawn: Operation not permitted",
        "Assertion failure (This test is stochastic and may occasionally fail)",
        "#if CL_KHR_COMMAND_BUFFER_EXTENSION_VERSION > CL_MAKE_VERSION(0, 9, 5)",
        "size of array 'altStackMem' is not an integral constant-expression",
        "call to non-'constexpr' function 'long int sysconf(int)'",
        "CMake 3.23.0 or higher is required",
    ):
        assert _infrastructure_failure_output(output)

    assert not _infrastructure_failure_output("AssertionError: expected 3, found 2")


def test_openmm_opencl_specs_apply_portable_pocl_cpu_compatibility():
    spec = SPECS_OPENMM["1382"]

    assert any(
        "getHostCPUName()" in command and 'StringRef("x86-64", 6)' in command
        for command in spec["build_after_test_patch"]
    )
    assert all(
        "LD_PRELOAD=${LD_PRELOAD:+$LD_PRELOAD:}"
        "/tmp/swebench_pocl_cpu_compat.so" in command
        for command in spec["test_cmd"]
    )


def test_openmm_opencl_specs_supply_cl_make_version_compatibility():
    spec = SPECS_OPENMM["5302"]

    assert any(
        "#define CL_MAKE_VERSION(major, minor, patch)" in command
        for command in spec["build_after_test_patch"]
    )
    assert any(
        "-DCMAKE_CXX_FLAGS='-include /tmp/swebench_opencl_compat.h'" in command
        for command in spec["build_after_test_patch"]
    )


def test_every_openmm_opencl_spec_has_runtime_and_header_compatibility():
    opencl_specs = [
        spec
        for spec in SPECS_OPENMM.values()
        if any(
            "-DOPENMM_BUILD_OPENCL_LIB=ON" in command
            for command in spec.get("build_after_test_patch", [])
        )
    ]

    assert opencl_specs
    for spec in opencl_specs:
        build_commands = spec["build_after_test_patch"]
        assert any("swebench_opencl_compat.h" in command for command in build_commands)
        assert any("swebench_pocl_cpu_compat.cpp" in command for command in build_commands)
        assert all(
            "/tmp/swebench_pocl_cpu_compat.so" in command
            for command in spec["test_cmd"]
        )


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


def test_ctest_no_tests_output_is_detected():
    assert _no_tests_selected("Test project /testbed\nNo tests were found!!!")


def test_test_generation_marks_collection_failure_as_generated_test_failure():
    result = classify_test_generation_result(
        {},
        {},
        test_patch_applied=True,
        gold_patch_applied=True,
        no_tests_selected=True,
        collection_failed=True,
    )

    assert result["status"] == "unresolved"
    assert result["failure_reason"] == "generated_test_collection_failed"


def test_collection_failure_detection_distinguishes_valid_empty_selection():
    assert _test_collection_failed(
        "collected 0 items / 1 error\nERROR collecting TestForceField.py"
    )
    assert not _test_collection_failed("collected 0 items\n0 selected")


def test_test_execution_failure_detection_is_scoped_to_test_output():
    assert _test_execution_failed(
        f"{GEN_APPLY_PASS}\n{START_TEST_OUTPUT}\n"
        "Traceback (most recent call last):\nImportError: invented API\n"
    )
    assert not _test_execution_failed("build warning: ImportError: documentation")


def test_test_generation_marks_unparseable_execution_failure_unresolved():
    result = classify_test_generation_result(
        {},
        {},
        True,
        True,
        test_execution_failed=True,
    )

    assert result["status"] == "unresolved"
    assert result["failure_reason"] == "generated_test_execution_failed"


def test_test_generation_marks_phase_timeout_unresolved():
    result = classify_test_generation_result(
        {},
        {"generated": "FAILED"},
        True,
        True,
        base_timed_out=True,
    )

    assert result["status"] == "unresolved"
    assert result["failure_reason"] == "generated_test_timed_out_on_base"


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


def test_gold_build_failure_is_an_unresolved_generated_test():
    result = classify_test_generation_result(
        {"TestNewAPI": "FAILED"},
        {},
        True,
        True,
        gold_build_failed=True,
    )

    assert result["status"] == "unresolved"
    assert result["failure_reason"] == "generated_test_did_not_build_on_gold"


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
    assert "--fuzz" not in script


def test_gold_patch_excludes_pr_authored_cpp_tests():
    gold = """diff --git a/src/fix.cpp b/src/fix.cpp
--- a/src/fix.cpp
+++ b/src/fix.cpp
@@ -1 +1 @@
-old
+fixed
diff --git a/Code/GraphMol/catch_graphmol.cpp b/Code/GraphMol/catch_graphmol.cpp
--- a/Code/GraphMol/catch_graphmol.cpp
+++ b/Code/GraphMol/catch_graphmol.cpp
@@ -1 +1 @@
-old test
+gold test
"""
    filtered, excluded = _exclude_gold_test_files(gold)

    assert "src/fix.cpp" in filtered
    assert "catch_graphmol.cpp" not in filtered
    assert excluded == ["Code/GraphMol/catch_graphmol.cpp"]


def test_gold_patch_excludes_rdkit_test_source_ending_in_catch():
    gold = """diff --git a/Code/GraphMol/Atom.cpp b/Code/GraphMol/Atom.cpp
--- a/Code/GraphMol/Atom.cpp
+++ b/Code/GraphMol/Atom.cpp
@@ -1 +1 @@
-old
+fixed
diff --git a/Code/GraphMol/FileParsers/file_parsers_catch.cpp b/Code/GraphMol/FileParsers/file_parsers_catch.cpp
--- a/Code/GraphMol/FileParsers/file_parsers_catch.cpp
+++ b/Code/GraphMol/FileParsers/file_parsers_catch.cpp
@@ -1 +1 @@
-old test
+gold test
"""
    filtered, excluded = _exclude_gold_test_files(gold)

    assert "Code/GraphMol/Atom.cpp" in filtered
    assert "file_parsers_catch.cpp" not in filtered
    assert excluded == ["Code/GraphMol/FileParsers/file_parsers_catch.cpp"]


def test_gold_patch_excludes_unavailable_binary_placeholders():
    gold = """diff --git a/src/fix.cpp b/src/fix.cpp
--- a/src/fix.cpp
+++ b/src/fix.cpp
@@ -1 +1 @@
-old
+fixed
diff --git a/Data/font.ttf b/Data/font.ttf
new file mode 100644
index 0000000..1234567
Binary files /dev/null and b/Data/font.ttf differ
"""

    filtered, excluded_tests, excluded_binary = _prepare_gold_patch(gold)

    assert "src/fix.cpp" in filtered
    assert "Data/font.ttf" not in filtered
    assert excluded_tests == []
    assert excluded_binary == ["Data/font.ttf"]


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
    assert "wrappers/python/openmm/*.py" not in command
    assert "wrappers/python/simtk/openmm/*.py" not in command
    assert "wrappers/python/simtk/unit" not in command
    assert "import openmm, simtk.openmm" in command
    assert "python -m lib2to3 -w -n \"$SIMTK_SITE/app\"" in command
    assert command.index("/testbed/wrappers/python/openmm/app") < command.index(
        "/testbed/wrappers/python/simtk/openmm/app"
    )
    assert command.endswith(
        "cd wrappers/python/tests && python -m pytest -xvs "
        "TestForceField.py::test_generated_regression"
    )
    assert "-k 'original_test'" not in command


def test_rdkit_test_generation_isolates_added_unittest_method(monkeypatch):
    command = (
        "cp -a build/rdkit/. rdkit/ && RDBASE=$PWD PYTHONPATH=$PWD "
        "python3 Code/GraphMol/FMCS/Wrap/testFMCS.py"
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: [command],
    )
    patch = """diff --git a/Code/GraphMol/FMCS/Wrap/testFMCS.py b/Code/GraphMol/FMCS/Wrap/testFMCS.py
--- a/Code/GraphMol/FMCS/Wrap/testFMCS.py
+++ b/Code/GraphMol/FMCS/Wrap/testFMCS.py
@@ -1145,6 +1145,18 @@ class TestCase(unittest.TestCase):
+  def testGithubCompleteRingsOnlyMemory(self):
+    pass
"""

    targets = _rdkit_generated_unittest_targets(patch)
    isolated = _rdkit_isolated_python_commands([command], patch)
    selected = _test_command(
        {"repo": "rdkit/rdkit", "version": "6646", "test_patch": ""}, patch
    )

    assert targets == {
        "Code/GraphMol/FMCS/Wrap/testFMCS.py": [
            "TestCase.testGithubCompleteRingsOnlyMemory"
        ]
    }
    assert isolated is not None
    assert selected.endswith(
        "python3 Code/GraphMol/FMCS/Wrap/testFMCS.py "
        "TestCase.testGithubCompleteRingsOnlyMemory"
    )


def test_rdkit_test_generation_isolates_touched_cpp_target(monkeypatch):
    commands = [
        "ctest --test-dir build -V -R '^graphmolTestsCatch$'",
        "ctest --test-dir build -V -R '^fileParsersCatchTest$'",
    ]
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: commands,
    )
    patch = """diff --git a/Code/GraphMol/FileParsers/file_parsers_catch.cpp b/Code/GraphMol/FileParsers/file_parsers_catch.cpp
--- a/Code/GraphMol/FileParsers/file_parsers_catch.cpp
+++ b/Code/GraphMol/FileParsers/file_parsers_catch.cpp
@@ -4253,3 +4253,6 @@ M  END
+TEST_CASE("generated regression") {
+  CHECK(true);
+}
"""

    isolated = _rdkit_isolated_cpp_commands(commands, patch)
    selected = _test_command(
        {"repo": "rdkit/rdkit", "version": "4806", "test_patch": ""}, patch
    )

    assert isolated == [commands[1]]
    assert selected == commands[1]


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


def test_openmm_source_spec_requires_generated_pytest(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {
            "openmm/openmm": {
                "4138": {
                    "test_cmd": ["fixed source oracle"],
                    "test_generation_requires_generated_pytest": True,
                }
            }
        },
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: ["fixed source oracle"],
    )

    command = _test_command(
        {"repo": "openmm/openmm", "version": "4138", "test_patch": ""},
        "diff --git a/docs/file.rst b/docs/file.rst\n",
    )

    assert "no curated generated pytest target" in command
    assert command.endswith("&& false")
    assert "fixed source oracle" not in command


def test_qgis_test_generation_keeps_fixed_ctest_command(monkeypatch):
    fixed = "ctest --test-dir build -V -R '^PyQgsRasterColorRampShader$'"
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {
            "qgis/QGIS": {
                "35852": {
                    "test_cmd": [fixed],
                    "test_generation_use_spec_cmd": True,
                }
            }
        },
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: [fixed],
    )
    patch = """diff --git a/tests/src/python/test_qgsrastercolorrampshader.py b/tests/src/python/test_qgsrastercolorrampshader.py
--- a/tests/src/python/test_qgsrastercolorrampshader.py
+++ b/tests/src/python/test_qgsrastercolorrampshader.py
@@ -1 +1,2 @@
 pass
+def test_regression(): pass
"""

    command = _test_command(
        {"repo": "qgis/QGIS", "version": "35852", "test_patch": ""}, patch
    )

    assert command == fixed
    assert "test_qgsrastercolorrampshader.py" not in command


def test_qgis_test_generation_isolates_added_unittest_method(monkeypatch):
    path = "python/plugins/processing/tests/Grass7AlgorithmsVectorTest.py"
    specs = {
        "test_cmd": ["ctest -R ProcessingGrass7AlgorithmsVectorTest"],
        "test_generation_use_spec_cmd": True,
        "test_generation_python_test": path,
    }
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {"qgis/QGIS": {"40837": specs}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: specs["test_cmd"],
    )
    patch = f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -127,6 +127,10 @@ class TestGrass7AlgorithmsVectorTest(unittest.TestCase):
+    def testCrsProjectionUsesWktFormat(self):
+        pass
"""

    isolated = _qgis_isolated_python_command(specs, patch)
    selected = _test_command(
        {"repo": "qgis/QGIS", "version": "40837", "test_patch": ""},
        patch,
    )

    assert isolated is not None
    assert selected == isolated
    assert "QGIS_PREFIX_PATH=/testbed/build/output" in selected
    assert "xvfb-run -a python3" in selected
    assert selected.endswith(
        f"/testbed/{path} "
        "TestGrass7AlgorithmsVectorTest.testCrsProjectionUsesWktFormat"
    )
    assert "ctest" not in selected


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


def test_openmm_test_generation_keeps_definition_scope_for_added_body_lines():
    patch = """diff --git a/wrappers/python/tests/TestForceField.py b/wrappers/python/tests/TestForceField.py
--- a/wrappers/python/tests/TestForceField.py
+++ b/wrappers/python/tests/TestForceField.py
@@ -845,5 +845,13 @@ class TestForceField(unittest.TestCase):
+    def test_Disulfides(self):
+        assert True
+
+        assert 1 == 1
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


def test_openmm_test_generation_isolates_edited_existing_method():
    patch = '''diff --git a/wrappers/python/tests/TestForceField.py b/wrappers/python/tests/TestForceField.py
--- a/wrappers/python/tests/TestForceField.py
+++ b/wrappers/python/tests/TestForceField.py
@@ -1115,9 +1115,11 @@ END"""))
     def test_CharmmPolar(self):
+        modeller = Modeller(pdb.topology, pdb.positions)
+        modeller.addExtraParticles(ff)
         pdb = PDBFile('systems/ala_ala_ala_drude.pdb')
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
    assert result["evaluation_wall_time_seconds"] >= 0
    report = json.loads(
        (tmp_path / "run/model/demo__repo-1/report.json").read_text()
    )
    assert "image build failed" in report["demo__repo-1"]["error"]
