import json
import sys

from swebench.eval_pipeline.prompt_builder import build_agent_prompt
from swebench.harness.constants.c import SPECS_OPENMM
from swebench.eval_pipeline.test_generation_eval import (
    BUILD_FAIL,
    GOLD_APPLY_PASS,
    GEN_APPLY_PASS,
    START_TEST_OUTPUT,
    GeneratedTestExecutionPlan,
    _build_script,
    _exclude_gold_test_files,
    _evaluate_one,
    _infrastructure_failure_output,
    _lammps_generated_test_targets,
    _no_tests_selected,
    _patch_driven_build_commands,
    _prepare_gold_patch,
    _biopython_generated_test_command,
    _qgis_isolated_python_command,
    _rdkit_isolated_cpp_commands,
    _rdkit_generated_unittest_targets,
    _rdkit_isolated_python_commands,
    _test_collection_failed,
    _test_execution_failed,
    _openmm_generated_pytest_targets,
    _special_repo_execution_plan,
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
    assert "only persistent file changes" in prompt
    assert ".patch/.diff files" in prompt
    assert "helper scripts" in prompt
    assert "Do not write the final patch to disk or to /tmp" in prompt
    assert "inspect it with `git diff`" in prompt


def test_clean_images_cli_is_opt_in(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline"])
    assert parse_args().clean_images is False

    monkeypatch.setattr(sys, "argv", ["run_pipeline", "--clean_images"])
    assert parse_args().clean_images is True


def test_container_boundary_cli_defaults_and_overrides(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline"])
    defaults = parse_args()
    assert defaults.build_memory == "32g"
    assert defaults.build_cpus == 8.0
    assert defaults.eval_memory == "32g"
    assert defaults.eval_cpus == 8.0
    assert defaults.eval_pids_limit == 2048
    assert defaults.allow_eval_network is False
    assert defaults.disable_eval_hardening is False

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--build_memory",
            "0",
            "--build_cpus",
            "0",
            "--eval_memory",
            "24g",
            "--eval_cpus",
            "6",
            "--eval_pids_limit",
            "1024",
            "--allow_eval_network",
            "--disable_eval_hardening",
        ],
    )
    overridden = parse_args()
    assert overridden.build_memory == "0"
    assert overridden.build_cpus == 0
    assert overridden.eval_memory == "24g"
    assert overridden.eval_cpus == 6
    assert overridden.eval_pids_limit == 1024
    assert overridden.allow_eval_network is True
    assert overridden.disable_eval_hardening is True


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


def test_test_generation_accepts_base_process_crash_when_gold_passes():
    result = classify_test_generation_result(
        {},
        {"generated_test": "PASSED"},
        test_patch_applied=True,
        gold_patch_applied=True,
        test_execution_failed=True,
        base_test_execution_failed=True,
    )

    assert result == {
        "status": "resolved",
        "failure_reason": "",
        "base_failed_tests": ["generated_test_process"],
        "gold_passed_tests": ["generated_test_process"],
    }


def test_test_generation_rejects_crash_when_gold_also_crashes():
    result = classify_test_generation_result(
        {},
        {"generated_test": "PASSED"},
        test_patch_applied=True,
        gold_patch_applied=True,
        test_execution_failed=True,
        base_test_execution_failed=True,
        gold_test_execution_failed=True,
    )

    assert result["status"] == "unresolved"
    assert result["failure_reason"] == "gold_did_not_pass"


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
        "#if CL_KHR_COMMAND_BUFFER_EXTENSION_VERSION > CL_MAKE_VERSION(0, 9, 5)",
        "size of array 'altStackMem' is not an integral constant-expression",
        "call to non-'constexpr' function 'long int sysconf(int)'",
        "CMake 3.23.0 or higher is required",
    ):
        assert _infrastructure_failure_output(output)

    assert not _infrastructure_failure_output("AssertionError: expected 3, found 2")


def test_openmm_stochastic_assertion_marker_is_not_infrastructure_failure():
    """OpenMM's ASSERT_USUALLY_* macros stamp this exact phrase on every
    stochastic-integrator assertion failure, deterministic or not (see
    openmmapi/include/openmm/internal/AssertionUtilities.h). Treating it as
    a host/toolchain infrastructure marker silently discarded real,
    deterministic base-fail/gold-pass results (e.g. tests that fix an RNG
    seed via setRandomNumberSeed before comparing) as `excluded`. A single
    generated test asserting via ASSERT_USUALLY_EQUAL_TOL must still be
    scorable like any other assertion.
    """
    assert not _infrastructure_failure_output(
        "exception: Assertion failure at TestLangevinIntegrator.h:124. "
        "Expected 9.97736, found 10.6733 "
        "(This test is stochastic and may occasionally fail)"
    )


def test_openmm_pocl_runtime_crashes_are_infrastructure_failures():
    outputs = (
        "WARNING: Using an unsupported OpenCL implementation.\n"
        "exception: Error creating array forceBuffers: clCreateBuffer (-61)",
        "WARNING: Using an unsupported OpenCL implementation.\n"
        "exception: clCreateKernel",
        "LLVM ERROR: Cannot select: v4f32 = X86ISD::VFPROUND",
        "Test: ./lib/CL/pocl_llvm_build.cc:587: Assertion failed.",
        "/tmp/swebench_pocl_cpu_compat.so ./build/Test\nSegmentation fault",
    )

    for output in outputs:
        assert _infrastructure_failure_output(output)


def test_openmm_opencl_specs_apply_portable_pocl_cpu_compatibility():
    from swebench.harness.constants.c import _openmm_opencl_targets_spec

    spec = _openmm_opencl_targets_spec("TestOpenCLExample")

    assert any(
        "getHostCPUName()" in command
        and "swebench_cpu=znver2" in command
        and "swebench_cpu=haswell" in command
        and "swebench_cpu=nehalem" in command
        for command in spec["build_after_test_patch"]
    )
    assert all(
        "LD_PRELOAD=${LD_PRELOAD:+$LD_PRELOAD:}"
        "/tmp/swebench_pocl_cpu_compat.so" in command
        for command in spec["test_cmd"]
    )


def test_openmm_opencl_specs_supply_cl_make_version_compatibility():
    spec = SPECS_OPENMM["3872"]

    assert any(
        "#define CL_MAKE_VERSION(major, minor, patch)" in command
        for command in spec["build_after_test_patch"]
    )
    assert any(
        "-DCMAKE_CXX_FLAGS='-include /tmp/swebench_opencl_compat.h'" in command
        for command in spec["build_after_test_patch"]
    )


def test_openmm_gpu_only_specs_request_real_gpu_runtime():
    for pr in ("2255",):
        spec = SPECS_OPENMM[pr]
        assert spec["docker_specs"] == {"run_args": {"gpu": True}}
        spec_text = "\n".join(spec["test_cmd"])
        assert "not evaluable:" not in spec_text
        assert "NVIDIA" in spec_text or "CUDA" in spec_text


def test_openmm_real_gpu_specs_request_gpu_docker_run_args():
    for pr in ("1640", "2152", "2829", "4364", "5302"):
        spec = SPECS_OPENMM[pr]
        spec_text = "\n".join(spec["test_cmd"])
        assert "not evaluable" not in spec_text, pr
        assert spec["docker_specs"]["run_args"]["gpu"] is True, pr


def test_openmm_native_python_specs_pin_numpy_one_x():
    commands = "\n".join(SPECS_OPENMM["3923"]["pre_install"])

    assert "'numpy<2'" in commands


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
        if spec.get("docker_specs", {}).get("run_args", {}).get("gpu"):
            assert any("libnvidia-opencl.so.1" in command for command in build_commands)
            assert all("clinfo -l" in command for command in spec["test_cmd"])
        else:
            assert any(
                "swebench_pocl_cpu_compat.cpp" in command
                for command in build_commands
            )
            assert all(
                "/tmp/swebench_pocl_cpu_compat.so" in command
                for command in spec["test_cmd"]
            )


def test_openmm_opencl_retarget_writes_compat_header_before_configure():
    # SPECS_OPENMM["1382"] declares the compat-header printf before its cmake
    # configure line, but the patch-driven retargeting used to reorder
    # configure to the front, so CMAKE_CXX_FLAGS' forced include pointed at a
    # file that didn't exist yet. The header write must stay ahead of the
    # cmake -B command that force-includes it.
    spec = SPECS_OPENMM["1382"]
    plan = GeneratedTestExecutionPlan(
        languages=("cpp",), build_targets=("TestOpenCLSomething",)
    )
    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    header_index = next(
        i for i, c in enumerate(commands) if "swebench_opencl_compat.h" in c and "printf" in c
    )
    configure_index = next(
        i for i, c in enumerate(commands)
        if c.startswith("cmake ") and " -B " in c
    )
    assert header_index < configure_index


def test_openmm_pip_based_python_spec_is_not_rebuilt_from_source():
    # SPECS_OPENMM["1540"] installs openmm from PyPI (no cmake build at all)
    # and its `build` step assumes `import openmm` already works. Forcing a
    # from-source cmake+PythonInstall retarget here uninstalls the working
    # pip package first, breaking the import that the original spec relied
    # on. A python-only plan against a spec with no configure command must
    # leave the spec's build list untouched.
    spec = SPECS_OPENMM["1540"]
    assert not any(
        command.startswith("cmake ") and " -B " in command
        for command in spec.get("build", []) + spec.get("build_after_test_patch", [])
    )
    plan = GeneratedTestExecutionPlan(languages=("python",), build_targets=())

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    assert commands == spec["build"]
    assert not any("pip uninstall" in command for command in commands)


def test_openmm_3311_python_plan_keeps_native_amoeba_build():
    plan = GeneratedTestExecutionPlan(
        languages=("python",),
        paths=("wrappers/python/tests/TestForceField.py",),
        commands=("python -m pytest",),
    )

    commands = _patch_driven_build_commands(
        "openmm/openmm", SPECS_OPENMM["3311"], plan
    )
    configure = next(
        command for command in commands
        if command.startswith("cmake ") and " -B " in command
    )

    assert commands[0] == "python -m pip uninstall -y openmm || true"
    assert "-DOPENMM_BUILD_PYTHON_WRAPPERS=ON" in configure
    assert "-DOPENMM_BUILD_AMOEBA_PLUGIN=ON" in configure
    assert any("--target install" in command for command in commands)
    assert any("PythonInstall" in command for command in commands)


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
    assert _no_tests_selected("[  PASSED  ] 0 tests.")


def test_gtest_all_failed_summary_is_not_mistaken_for_zero_selected():
    # gtest always prints "[ PASSED ] 0 tests." when every executed test
    # fails -- that line reports the *passed* count, not whether any test
    # ran. `_no_tests_selected` alone cannot tell the two apart (it matches
    # both), so callers must gate it on the parsed status map being empty:
    # when the parser actually recovered a FAILED result, tests were
    # genuinely selected and executed, and the correct classification is
    # unresolved/gold_did_not_pass, not not_exercised/no_tests_selected.
    gtest_all_failed_output = (
        "[==========] Running 1 test from 1 test suite.\n"
        "[ RUN      ] ReaxFFSpeciesTest.PositionUsesCenterOfMassAndTotalCharge\n"
        "[  FAILED  ] ReaxFFSpeciesTest.PositionUsesCenterOfMassAndTotalCharge (3 ms)\n"
        "[==========] 1 test from 1 test suite ran. (3 ms total)\n"
        "[  PASSED  ] 0 tests.\n"
        "[  FAILED  ] 1 test, listed below:\n"
        "[  FAILED  ] ReaxFFSpeciesTest.PositionUsesCenterOfMassAndTotalCharge\n"
    )
    assert _no_tests_selected(gtest_all_failed_output)

    base_status = {
        "ReaxFFSpeciesTest.PositionUsesCenterOfMassAndTotalCharge": "FAILED"
    }
    result = classify_test_generation_result(
        base_status,
        base_status,
        test_patch_applied=True,
        gold_patch_applied=True,
        no_tests_selected=(
            _no_tests_selected(gtest_all_failed_output) and not base_status
        ),
    )

    assert result["status"] == "unresolved"
    assert result["failure_reason"] == "gold_did_not_pass"


def test_base_process_abort_is_valid_when_gold_tests_pass_despite_prior_statuses():
    result = classify_test_generation_result(
        {"ExistingTest": "PASSED"},
        {"ExistingTest": "PASSED", "GeneratedTest": "PASSED"},
        test_patch_applied=True,
        gold_patch_applied=True,
        base_test_execution_failed=True,
    )

    assert result["status"] == "resolved"
    assert result["base_failed_tests"] == ["generated_test_process"]


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
    assert _test_execution_failed(
        f"{START_TEST_OUTPUT}\ntest_generated: Aborted (core dumped)\n"
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


def test_gold_script_installs_after_applying_patches(monkeypatch):
    install = "python -m pip install -e ."
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {
            "demo/repo": {
                "1": {"install": install, "test_cmd": "pytest generated_test.py"}
            }
        },
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: "pytest generated_test.py",
    )

    script = _build_script(
        {"repo": "demo/repo", "version": "1", "base_commit": "abc"},
        "patch",
        apply_gold=True,
    )

    assert script.index(GOLD_APPLY_PASS) < script.index(GEN_APPLY_PASS)
    assert script.index(GEN_APPLY_PASS) < script.index(install)
    assert script.index(install) < script.index(START_TEST_OUTPUT)


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

    assert "pip install" not in command
    assert "LD_LIBRARY_PATH=$PWD/build" in command
    assert "OPENMM_PLUGIN_DIR=$PWD/build" in command
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
        "Code/GraphMol/FMCS/Wrap/testFMCS.py::TestCase::"
        "testGithubCompleteRingsOnlyMemory"
    )


def test_biopython_test_generation_runs_only_added_nodeid(monkeypatch):
    patch = """diff --git a/Tests/test_SeqUtils.py b/Tests/test_SeqUtils.py
--- a/Tests/test_SeqUtils.py
+++ b/Tests/test_SeqUtils.py
@@ -228,6 +228,9 @@ class SeqUtilsTests(unittest.TestCase):
+    def test_Tm_NN_terminal_mismatch(self):
+        assert True
"""
    command = _biopython_generated_test_command(patch)

    assert command is not None
    assert command.startswith("cd /testbed/Tests && PYTHONPATH=/testbed")
    assert command.endswith(
        "test_SeqUtils.py::SeqUtilsTests::test_Tm_NN_terminal_mismatch"
    )


def test_lammps_test_generation_builds_and_runs_touched_binary(monkeypatch):
    patch = """diff --git a/unittest/commands/test_regions.cpp b/unittest/commands/test_regions.cpp
--- a/unittest/commands/test_regions.cpp
+++ b/unittest/commands/test_regions.cpp
@@ -278,3 +278,6 @@ TEST_F(RegionTest, Counts)
+TEST_F(RegionTest, EllipsoidSurfaceContact) {}
"""
    specs = {
        "build_after_test_patch": [
            "cmake -S cmake -B build -D ENABLE_TESTING=ON",
            "cmake --build build --parallel $(nproc)",
        ],
        "test_cmd": ["ctest --test-dir build --output-on-failure"],
        "test_generation_use_spec_cmd": True,
    }
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {"lammps/lammps": {"3931": specs}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: specs["test_cmd"],
    )
    instance = {
        "instance_id": "lammps__lammps-3931",
        "repo": "lammps/lammps",
        "version": "3931",
        "base_commit": "abc",
        "test_patch": "",
    }

    assert _lammps_generated_test_targets(patch) == [
        ("test_regions", "build/test_regions")
    ]
    assert _test_command(instance, patch) == "build/test_regions"
    script = _build_script(instance, patch, apply_gold=False)
    assert "cmake --build build --parallel $(nproc) --target test_regions" in script
    assert "ctest --test-dir build" not in script


def test_lammps_test_generation_accepts_yaml_fixture_with_companion_input_file(
    monkeypatch,
):
    """A force-styles YAML fixture's own `input_file: in.<name>` field names
    a companion LAMMPS input deck shipped alongside it under the same
    tests/ directory (read by the shared driver binary at runtime, not
    independently invoked). It must not be treated as an unsupported test
    path and veto the otherwise-valid YAML fixture (regression for the bug
    found in lammps__lammps-4346, where this exact patch shape was
    incorrectly rejected as unsupported_generated_test)."""
    patch = """diff --git a/unittest/force-styles/tests/atomic-pair-gran_hooke_history_virial.yaml b/unittest/force-styles/tests/atomic-pair-gran_hooke_history_virial.yaml
new file mode 100644
--- /dev/null
+++ b/unittest/force-styles/tests/atomic-pair-gran_hooke_history_virial.yaml
@@ -0,0 +1,3 @@
+---
+input_file: in.gran_hooke_history_virial
+pair_style: gran/hooke/history 1000.0 0.0 0.0 0.0 0.0 0
diff --git a/unittest/force-styles/tests/in.gran_hooke_history_virial b/unittest/force-styles/tests/in.gran_hooke_history_virial
new file mode 100644
--- /dev/null
+++ b/unittest/force-styles/tests/in.gran_hooke_history_virial
@@ -0,0 +1,2 @@
+units lj
+atom_style granular
"""
    plan = _special_repo_execution_plan({"repo": "lammps/lammps"}, patch, [])

    assert plan.failure_reason is None
    assert plan.evidence["rejected_paths"] == ()
    assert (
        "unittest/force-styles/tests/atomic-pair-gran_hooke_history_virial.yaml"
        in plan.paths
    )
    assert any("ctest" in command for command in plan.commands)


def _lammps_force_style_driver_specs():
    return {
        "build_after_test_patch": [
            "cmake -S cmake -B build -D ENABLE_TESTING=ON",
            "cmake --build build --parallel $(nproc)",
        ],
        "test_cmd": ["ctest --test-dir build --output-on-failure"],
        "test_generation_use_spec_cmd": True,
    }


def test_lammps_test_generation_rejects_bare_force_style_driver(monkeypatch):
    """A generated edit to a shared force-styles driver's .cpp (e.g.
    test_pair_style.cpp) that does not add a new TEST()/TEST_F() case, and
    has no ctest registration or YAML fixture, has no argument to invoke the
    driver with — it must be flagged unsupported, not silently run bare
    (which just prints usage and produces no parseable test output,
    previously misclassified as no_parseable_test_status)."""
    patch = """diff --git a/unittest/force-styles/test_pair_style.cpp b/unittest/force-styles/test_pair_style.cpp
--- a/unittest/force-styles/test_pair_style.cpp
+++ b/unittest/force-styles/test_pair_style.cpp
@@ -10,3 +10,6 @@
+// bumped a shared constant used by existing cases, no new TEST() added
+constexpr double kTolerance = 1e-10;
"""
    specs = _lammps_force_style_driver_specs()
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {"lammps/lammps": {"4887": specs}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: specs["test_cmd"],
    )
    instance = {
        "instance_id": "lammps__lammps-4887",
        "repo": "lammps/lammps",
        "version": "4887",
        "base_commit": "abc",
        "test_patch": "",
    }

    command = _test_command(instance, patch)

    assert "UNSUPPORTED_GENERATED_TEST" in command
    assert "build/test_pair_style" not in command


def test_lammps_test_generation_runs_bare_driver_with_new_native_test_case(
    monkeypatch,
):
    """A generated edit that adds a new TEST()/TEST_F() case directly to a
    shared force-styles driver's own .cpp source (e.g. test_pair_style.cpp)
    needs no YAML fixture or ctest registration to be invokable: gtest
    self-discovers compiled-in TEST()/TEST_F() cases in the binary they're
    linked into, so running the driver bare already exercises the new case.
    This must NOT be flagged unsupported (regression for the bug found in
    lammps__lammps-4887, where this exact patch shape was incorrectly
    vetoed)."""
    patch = """diff --git a/unittest/force-styles/test_pair_style.cpp b/unittest/force-styles/test_pair_style.cpp
--- a/unittest/force-styles/test_pair_style.cpp
+++ b/unittest/force-styles/test_pair_style.cpp
@@ -10,3 +10,6 @@
+TEST(PairStyle, ExtraCase) {}
"""
    specs = _lammps_force_style_driver_specs()
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {"lammps/lammps": {"4887": specs}},
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: specs["test_cmd"],
    )
    instance = {
        "instance_id": "lammps__lammps-4887",
        "repo": "lammps/lammps",
        "version": "4887",
        "base_commit": "abc",
        "test_patch": "",
    }

    command = _test_command(instance, patch)

    assert "UNSUPPORTED_GENERATED_TEST" not in command
    assert "build/test_pair_style" in command


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
    assert selected.endswith(commands[1])


def test_openmm_test_generation_uses_patch_language_over_fixed_spec(monkeypatch):
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

    assert "TestIntegrators.py::test_generated" in command
    assert "TestReferenceCustomIntegrator" not in command


def test_openmm_shared_header_preserves_curated_platform_family():
    patch = """diff --git a/tests/TestCustomIntegrator.h b/tests/TestCustomIntegrator.h
--- a/tests/TestCustomIntegrator.h
+++ b/tests/TestCustomIntegrator.h
@@ -1 +1,2 @@
+void testGeneratedRegression() {}
"""
    commands = SPECS_OPENMM["2257"]["test_cmd"]

    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm", "version": "2257", "test_patch": ""},
        patch,
        commands,
    )

    assert plan is not None
    assert plan.failure_reason is None
    assert plan.build_targets == ("TestOpenCLCustomIntegrator",)
    assert "./build/TestOpenCLCustomIntegrator" in plan.commands[0]
    assert "TestReferenceCustomIntegrator" not in plan.commands[0]


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

    assert "NO_GENERATED_TESTS_SELECTED" in command
    assert command.endswith("&& false")
    assert "fixed source oracle" not in command


def test_qgis_test_generation_rejects_unsupported_cpp_only_patch(monkeypatch):
    # QGIS has no C++ dispatch branch (unlike LAMMPS/RDKit/OpenMM): a patch
    # that only touches a .cpp test source has no safe way to be retargeted,
    # so it must fail closed instead of silently running the curated
    # fixed ctest command for an unrelated original-PR test.
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
    patch = """diff --git a/tests/src/analysis/testqgsrastercolorrampshader.cpp b/tests/src/analysis/testqgsrastercolorrampshader.cpp
--- a/tests/src/analysis/testqgsrastercolorrampshader.cpp
+++ b/tests/src/analysis/testqgsrastercolorrampshader.cpp
@@ -1,3 +1,6 @@
 class TestQgsRasterColorRampShader : public QObject
 {
+  private slots:
+    void regression() {}
 };
"""

    command = _test_command(
        {"repo": "qgis/QGIS", "version": "35852", "test_patch": ""}, patch
    )

    assert command == "echo UNSUPPORTED_GENERATED_TEST && false"


def test_qgis_test_generation_runs_python_test_file_outside_curated_path(monkeypatch):
    # The curated `test_generation_python_test` names the file the
    # *original* PR's own test lived in; the model may legitimately write
    # its regression test in a different Python test file. That file must
    # still be run directly instead of silently falling back to the fixed
    # curated ctest command for an unrelated test.
    fixed = "ctest --test-dir build -V -R '^PyQgsRasterColorRampShader$'"
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAP_REPO_VERSION_TO_SPECS",
        {
            "qgis/QGIS": {
                "35852": {
                    "test_cmd": [fixed],
                    "test_generation_use_spec_cmd": True,
                    "test_generation_python_test": (
                        "tests/src/python/test_qgsrastercolorrampshader.py"
                    ),
                }
            }
        },
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.get_test_cmds",
        lambda _instance: [fixed],
    )
    path = "tests/src/python/test_qgsotherfile.py"
    patch = f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -10,6 +10,9 @@ class TestQgsOtherFile(unittest.TestCase):

         pass

+    def test_regression(self):
+        pass
+
"""

    command = _test_command(
        {"repo": "qgis/QGIS", "version": "35852", "test_patch": ""}, patch
    )

    assert "ctest" not in command
    assert command.endswith(
        f"/testbed/{path} TestQgsOtherFile.test_regression"
    )


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


def test_openmm_test_generation_keeps_resolved_nodeid_from_other_file():
    # A patch touching two wrapper test files: one added method resolves to
    # a full nodeid (class visible in the diff hunk context), the other's
    # enclosing class isn't visible in its hunk header. The first file's
    # resolved nodeid must not be silently dropped just because a second
    # file needs a `-k` filter.
    patch = """diff --git a/wrappers/python/tests/TestForceA.py b/wrappers/python/tests/TestForceA.py
--- a/wrappers/python/tests/TestForceA.py
+++ b/wrappers/python/tests/TestForceA.py
@@ -1,3 +1,6 @@
 import unittest

+def test_regression_a():
+    assert True
+
diff --git a/wrappers/python/tests/TestForceB.py b/wrappers/python/tests/TestForceB.py
--- a/wrappers/python/tests/TestForceB.py
+++ b/wrappers/python/tests/TestForceB.py
@@ -55,6 +55,9 @@ def helper():

         self.assertTrue(True)

+    def test_regression_b(self):
+        self.assertTrue(True)
+
"""

    targets, pytest_filter = _openmm_generated_pytest_targets(patch)

    assert targets == ["TestForceA.py", "TestForceB.py"]
    assert pytest_filter == "test_regression_a or test_regression_b"


def test_openmm_shared_header_cpp_test_targets_reference_wrapper():
    # OpenMM's per-force/integrator C++ tests are shared header files
    # (tests/TestX.h) included by a pre-existing TestReferenceX.cpp wrapper
    # that CMake already builds; a patch that only touches the header must
    # resolve to that existing target instead of being rejected outright.
    patch = """diff --git a/tests/TestNonbondedForce.h b/tests/TestNonbondedForce.h
--- a/tests/TestNonbondedForce.h
+++ b/tests/TestNonbondedForce.h
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, [])

    assert plan.failure_reason is None
    assert plan.paths == ("tests/TestNonbondedForce.h",)
    assert plan.build_targets == ("TestReferenceNonbondedForce",)
    assert plan.commands == (
        "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
        "OPENMM_PLUGIN_DIR=$PWD/build ./build/TestReferenceNonbondedForce",
    )


def test_openmm_shared_header_target_match_is_exact_not_suffix():
    # `TestReferenceCustomNonbondedForce` and `TestReferenceNonbondedForce`
    # both end with "NonbondedForce"; an unanchored `endswith` match could
    # pick the wrong (structurally different) binary for a header patch
    # targeting the plain NonbondedForce family. Verify the Custom variant,
    # listed first, is not mistakenly selected.
    patch = """diff --git a/tests/TestNonbondedForce.h b/tests/TestNonbondedForce.h
--- a/tests/TestNonbondedForce.h
+++ b/tests/TestNonbondedForce.h
@@ -1 +1,2 @@
+void testRegression() {}
"""
    commands = [
        "cmake --build build --target TestReferenceCustomNonbondedForce",
        "./build/TestReferenceCustomNonbondedForce",
        "cmake --build build --target TestReferenceNonbondedForce",
        "./build/TestReferenceNonbondedForce",
    ]

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, commands)

    assert plan.failure_reason is None
    assert plan.build_targets == ("TestReferenceNonbondedForce",)
    assert plan.commands == (
        "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
        "OPENMM_PLUGIN_DIR=$PWD/build ./build/TestReferenceNonbondedForce",
    )


def test_openmm_shared_header_uses_curated_opencl_backend_target():
    patch = """diff --git a/tests/TestNonbondedForce.h b/tests/TestNonbondedForce.h
--- a/tests/TestNonbondedForce.h
+++ b/tests/TestNonbondedForce.h
@@ -1 +1,2 @@
+void testRegression() {}
"""
    command = (
        "OCL_ICD_VENDORS=/tmp/vendors "
        "LD_LIBRARY_PATH=$PWD/build ./build/TestOpenCLNonbondedForce"
    )

    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm"}, patch, [command]
    )

    assert plan.build_targets == ("TestOpenCLNonbondedForce",)
    assert plan.commands[0].endswith("./build/TestOpenCLNonbondedForce")


def test_openmm_cpp_test_accepts_companion_cmake_registration():
    patch = """diff --git a/tests/CMakeLists.txt b/tests/CMakeLists.txt
--- a/tests/CMakeLists.txt
+++ b/tests/CMakeLists.txt
@@ -1 +1,2 @@
+target_compile_definitions(TestDocumentation PRIVATE SOURCE_DIR=\"/testbed\")
diff --git a/tests/TestDocumentation.cpp b/tests/TestDocumentation.cpp
new file mode 100644
--- /dev/null
+++ b/tests/TestDocumentation.cpp
@@ -0,0 +1 @@
+int main() { return 0; }
"""

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, [])

    assert plan.failure_reason is None
    assert plan.paths == ("tests/TestDocumentation.cpp",)
    assert plan.build_targets == ("TestDocumentation",)


def test_openmm_accepts_source_inspection_python_test_outside_wrapper_tree():
    path = "platforms/reference/tests/TestReferencePMEComments.py"
    patch = f"""diff --git a/{path} b/{path}
new file mode 100644
--- /dev/null
+++ b/{path}
@@ -0,0 +1,2 @@
+def test_comments():
+    assert True
"""

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, [])

    assert plan.failure_reason is None
    assert plan.paths == (path,)
    assert plan.commands == (
        f"PYTHONPATH=/testbed:${{PYTHONPATH:-}} python -m pytest -xvs {path}",
    )


def test_openmm_source_inspection_python_test_does_not_build_wrappers():
    path = "platforms/reference/tests/TestReferencePMEComments.py"
    plan = GeneratedTestExecutionPlan(
        languages=("python",), paths=(path,), commands=("python -m pytest",)
    )
    spec = {
        "build_after_test_patch": [
            "cmake -B build -S . -DOPENMM_BUILD_PYTHON_WRAPPERS=ON",
            "cmake --build build --parallel $(nproc)",
        ]
    }

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    assert "-DOPENMM_BUILD_PYTHON_WRAPPERS=OFF" in commands[0]
    assert not any("PythonInstall" in command for command in commands)


def test_openmm_legacy_python_build_converts_python2_swig_output():
    plan = GeneratedTestExecutionPlan(
        languages=("python",),
        paths=("wrappers/python/tests/TestForceField.py",),
        commands=("python -m pytest",),
    )
    spec = {
        "build_after_test_patch": [
            "cmake -B build -S . -DOPENMM_BUILD_PYTHON_WRAPPERS=ON",
            "cmake --build build --parallel $(nproc)",
        ]
    }

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    python_install = next(command for command in commands if "PythonInstall" in command)
    assert "python -m lib2to3 -w -n" in python_install
    assert "if [ ! -d wrappers/python/openmm ]" in python_install


def test_rdkit_indented_method_with_unknown_class_uses_pytest_filter():
    path = "Code/ForceField/Wrap/testConstraints.py"
    patch = f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -308,2 +308,4 @@ existing_method(self):
+  def testMMFFZeroDisplacement(self):
+    assert True
"""

    plan = _special_repo_execution_plan(
        {"repo": "rdkit/rdkit"}, patch, []
    )

    assert plan.failure_reason is None
    assert f"{path}::testMMFFZeroDisplacement" not in plan.commands[0]
    assert path in plan.commands[0]
    assert "-k 'testMMFFZeroDisplacement'" in plan.commands[0]


def test_openmm_plugin_shared_header_cpp_test_targets_reference_wrapper():
    patch = """diff --git a/plugins/rpmd/tests/TestRpmd.h b/plugins/rpmd/tests/TestRpmd.h
--- a/plugins/rpmd/tests/TestRpmd.h
+++ b/plugins/rpmd/tests/TestRpmd.h
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, [])

    assert plan.failure_reason is None
    assert plan.build_targets == ("TestReferenceRpmd",)


def test_openmm_plugin_test_enables_matching_plugin_cmake_flag():
    # A generated test under plugins/<name>/tests/ resolves to a
    # TestReference<Name> build target, but that target only exists once the
    # plugin's own CMake option is turned on. The default configure line
    # doesn't enable any plugin, so "cmake --build ... --target
    # TestReferenceAmoebaVdwForce" used to fail with "No rule to make
    # target". The retargeted configure command must turn the matching
    # -DOPENMM_BUILD_<NAME>_PLUGIN=ON flag on.
    spec = {
        "build_after_test_patch": [
            "cmake -B build -S . -DCMAKE_BUILD_TYPE=Release "
            "-DOPENMM_BUILD_CUDA_LIB=OFF -DOPENMM_BUILD_OPENCL_LIB=OFF "
            "-DOPENMM_BUILD_HIP_LIB=OFF -DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF",
            "cmake --build build --parallel $(nproc) --target TestReferenceAmoebaVdwForce",
        ],
    }
    plan = GeneratedTestExecutionPlan(
        languages=("cpp",),
        paths=("plugins/amoeba/tests/TestAmoebaVdwForce.h",),
        build_targets=("TestReferenceAmoebaVdwForce",),
    )

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    configure = next(
        c for c in commands if c.startswith("cmake ") and " -B " in c
    )
    assert "-DOPENMM_BUILD_AMOEBA_PLUGIN=ON" in configure


def test_openmm_cuda_only_generated_test_uses_real_gpu_spec():
    patch = """diff --git a/platforms/cuda/tests/TestCudaMultipleForces.cpp b/platforms/cuda/tests/TestCudaMultipleForces.cpp
--- a/platforms/cuda/tests/TestCudaMultipleForces.cpp
+++ b/platforms/cuda/tests/TestCudaMultipleForces.cpp
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""

    spec = SPECS_OPENMM["4364"]
    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm", "version": "4364"}, patch, spec["test_cmd"]
    )

    assert plan.failure_reason is None
    assert plan.build_targets == ("TestCudaMultipleForces",)


def test_openmm_cuda_only_generated_test_without_cuda_spec_is_non_evaluable():
    patch = """diff --git a/platforms/cuda/tests/TestCudaMultipleForces.cpp b/platforms/cuda/tests/TestCudaMultipleForces.cpp
--- a/platforms/cuda/tests/TestCudaMultipleForces.cpp
+++ b/platforms/cuda/tests/TestCudaMultipleForces.cpp
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, [])

    assert plan.failure_reason == "non_evaluable_spec"


def test_openmm_opencl_retarget_preserves_runtime_prefix():
    patch = """diff --git a/platforms/opencl/tests/TestOpenCLCustomExternalForce.cpp b/platforms/opencl/tests/TestOpenCLCustomExternalForce.cpp
--- a/platforms/opencl/tests/TestOpenCLCustomExternalForce.cpp
+++ b/platforms/opencl/tests/TestOpenCLCustomExternalForce.cpp
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""
    spec = SPECS_OPENMM["1382"]

    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm", "version": "1382"}, patch, spec["test_cmd"]
    )

    assert "OCL_ICD_VENDORS=/tmp/swebench-opencl-vendors" in plan.commands[0]
    assert "NVIDIA_OPENCL_UNAVAILABLE" in plan.commands[0]


def test_openmm_gpu_opencl_spec_pins_and_validates_nvidia_icd():
    spec = SPECS_OPENMM["1382"]

    setup = "\n".join(spec["build_after_test_patch"])
    command = spec["test_cmd"][0]
    assert "libnvidia-opencl.so.1" in setup
    assert "OCL_ICD_VENDORS=/tmp/swebench-opencl-vendors" in command
    assert "clinfo -l" in command
    assert "grep -qi NVIDIA" in command
    assert "/tmp/swebench_pocl_cpu_compat.so" not in command


def test_openmm_cpp_retarget_forces_build_testing_on():
    spec = {
        "build_after_test_patch": [
            "cmake -B build -S . -DBUILD_TESTING=OFF",
            "cmake --build build --target Existing",
        ]
    }
    plan = GeneratedTestExecutionPlan(
        languages=("cpp",), build_targets=("Generated",)
    )

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    configure = next(command for command in commands if command.startswith("cmake -B"))
    assert "-DBUILD_TESTING=ON" in configure
    assert "-DBUILD_TESTING=OFF" not in configure


def test_openmm_cuda_retarget_recognizes_export_prefixed_configure():
    spec = {
        "build_after_test_patch": [
            "export PATH=/usr/local/cuda/bin:$PATH && "
            "cmake -B build -S . -DOPENMM_BUILD_CUDA_LIB=ON -DBUILD_TESTING=OFF",
            "cmake --build build --target Existing",
        ]
    }
    plan = GeneratedTestExecutionPlan(
        languages=("cpp",), build_targets=("Generated",)
    )

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    configure_commands = [command for command in commands if "cmake -B build" in command]
    assert len(configure_commands) == 1
    assert "-DOPENMM_BUILD_CUDA_LIB=ON" in configure_commands[0]
    assert "-DBUILD_TESTING=ON" in configure_commands[0]


def test_openmm_cuda_plan_ignores_unbuilt_opencl_variant():
    patch = """diff --git a/platforms/cuda/tests/TestCudaForce.cpp b/platforms/cuda/tests/TestCudaForce.cpp
--- a/platforms/cuda/tests/TestCudaForce.cpp
+++ b/platforms/cuda/tests/TestCudaForce.cpp
@@ -1 +1,2 @@
+void generated() {}
 void existing();
diff --git a/platforms/opencl/tests/TestOpenCLForce.cpp b/platforms/opencl/tests/TestOpenCLForce.cpp
--- a/platforms/opencl/tests/TestOpenCLForce.cpp
+++ b/platforms/opencl/tests/TestOpenCLForce.cpp
@@ -1 +1,2 @@
+void generated() {}
 void existing();
"""
    spec = SPECS_OPENMM["4364"]

    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm", "version": "4364"}, patch, spec["test_cmd"]
    )

    assert plan.build_targets == ("TestCudaForce",)
    assert plan.paths == ("platforms/cuda/tests/TestCudaForce.cpp",)


def test_openmm_gold_fix_confined_to_gpu_platforms_is_non_evaluable():
    # A generated tests/TestX.h patch always gets retargeted onto the
    # Reference-platform "TestReference<Name>" build target (see
    # test_openmm_shared_header_cpp_test_targets_reference_wrapper), since
    # that's the only variant buildable in this no-GPU environment. If the
    # *gold* patch that actually fixes the issue only touches
    # platforms/common|cuda|opencl/ (GPU-only code with no Reference
    # equivalent), the Reference binary's behavior is identical before and
    # after the fix, so the generated test can never distinguish base from
    # gold regardless of what it asserts -- this must be flagged
    # non_evaluable_spec up front rather than surfacing as a spurious
    # base_did_not_fail/gold_did_not_pass "model failure".
    generated_patch = """diff --git a/tests/TestCustomNonbondedForce.h b/tests/TestCustomNonbondedForce.h
--- a/tests/TestCustomNonbondedForce.h
+++ b/tests/TestCustomNonbondedForce.h
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""
    gold_patch = """diff --git a/platforms/common/src/kernels/customNonbondedGroups.cc b/platforms/common/src/kernels/customNonbondedGroups.cc
--- a/platforms/common/src/kernels/customNonbondedGroups.cc
+++ b/platforms/common/src/kernels/customNonbondedGroups.cc
@@ -1,2 +1,2 @@
-old kernel code
+fixed kernel code
"""

    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm", "patch": gold_patch}, generated_patch, []
    )

    assert plan.failure_reason == "non_evaluable_spec"


def test_openmm_gold_fix_touching_reference_platform_is_still_evaluable():
    # Sanity check for the veto above: when the gold fix also touches
    # platforms/reference/ (or any non-GPU-only path), the Reference build
    # target genuinely changes behavior between base and gold, so the
    # generated test must still be run normally.
    generated_patch = """diff --git a/tests/TestNonbondedForce.h b/tests/TestNonbondedForce.h
--- a/tests/TestNonbondedForce.h
+++ b/tests/TestNonbondedForce.h
@@ -1,3 +1,4 @@
+void testNewCase() {}
 void runPlatformTests();
"""
    gold_patch = """diff --git a/platforms/reference/src/ReferenceKernels.cpp b/platforms/reference/src/ReferenceKernels.cpp
--- a/platforms/reference/src/ReferenceKernels.cpp
+++ b/platforms/reference/src/ReferenceKernels.cpp
@@ -1,2 +1,2 @@
-old code
+fixed code
"""

    plan = _special_repo_execution_plan(
        {"repo": "openmm/openmm", "patch": gold_patch}, generated_patch, []
    )

    assert plan.failure_reason is None
    assert plan.build_targets == ("TestReferenceNonbondedForce",)


def test_openmm_native_python_spec_patches_swig_source_not_build_copy():
    # CMake copies wrappers/python/src/swig_doxygen/swig_lib/python/extend.i
    # fresh into the build tree on every configure/build. The old sed target
    # (build/python/src/swig_lib/python/extend.i) was both the wrong path
    # (missing the swig_doxygen segment) and gets overwritten by that copy
    # even when corrected, so SWIG still saw the unpatched '# Look' line.
    # Patching the source copy survives the CMake-copy step.
    commands = SPECS_OPENMM["3923"]["build_after_test_patch"]
    sed_command = next(c for c in commands if "extend.i" in c and "sed -i" in c)

    assert "wrappers/python/src/swig_doxygen/swig_lib/python/extend.i" in sed_command
    assert "build/python/src/swig_lib/python/extend.i" not in sed_command


def test_openmm_python_plan_retarget_patches_swig_source_not_build_copy():
    spec = {
        "build_after_test_patch": [
            "cmake -B build -S . -DCMAKE_BUILD_TYPE=Release "
            "-DOPENMM_BUILD_CUDA_LIB=OFF -DOPENMM_BUILD_OPENCL_LIB=OFF "
            "-DOPENMM_BUILD_HIP_LIB=OFF -DOPENMM_BUILD_PYTHON_WRAPPERS=ON "
            "-DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF",
            "cmake --build build --parallel $(nproc) --target install",
        ],
    }
    plan = GeneratedTestExecutionPlan(languages=("python",), build_targets=())

    commands = _patch_driven_build_commands("openmm/openmm", spec, plan)

    sed_command = next(c for c in commands if "extend.i" in c and "sed -i" in c)
    assert "wrappers/python/src/swig_doxygen/swig_lib/python/extend.i" in sed_command
    assert "build/python/src/swig_lib/python/extend.i" not in sed_command


def test_openmm_python_test_fixtures_do_not_veto_accepted_test():
    # Non-source data fixtures shipped alongside a generated Python test
    # (e.g. wrappers/python/tests/systems/*.gro/*.top) are not tests
    # themselves and must not cause the whole plan to be rejected.
    patch = """diff --git a/wrappers/python/tests/TestGromacsTopFile.py b/wrappers/python/tests/TestGromacsTopFile.py
--- a/wrappers/python/tests/TestGromacsTopFile.py
+++ b/wrappers/python/tests/TestGromacsTopFile.py
@@ -1 +1,2 @@
+def test_generated(): pass
 pass
diff --git a/wrappers/python/tests/systems/tip4p.gro b/wrappers/python/tests/systems/tip4p.gro
new file mode 100644
--- /dev/null
+++ b/wrappers/python/tests/systems/tip4p.gro
@@ -0,0 +1 @@
+data
diff --git a/wrappers/python/tests/systems/tip4p.top b/wrappers/python/tests/systems/tip4p.top
new file mode 100644
--- /dev/null
+++ b/wrappers/python/tests/systems/tip4p.top
@@ -0,0 +1 @@
+data
"""

    plan = _special_repo_execution_plan({"repo": "openmm/openmm"}, patch, [])

    assert plan.failure_reason is None
    assert plan.paths == ("wrappers/python/tests/TestGromacsTopFile.py",)
    assert plan.evidence["rejected_paths"] == ()


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
    assert result["failure_reason"] == "invalid_test_spec"
    assert result["evaluation_stage"] == "resolve_test_spec"
    assert result["evaluation_wall_time_seconds"] >= 0
    report = json.loads(
        (tmp_path / "run/model/demo__repo-1/report.json").read_text()
    )
    assert "image build failed" in report["demo__repo-1"]["error"]


def test_empty_prediction_with_inference_error_is_errored(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.close_logger",
        lambda *_args: None,
    )

    result = _evaluate_one(
        {"instance_id": "demo__repo-1"},
        {
            "model_patch": "",
            "model_name_or_path": "model",
            "error": "provider: Insufficient Balance",
        },
        "run",
        object(),
        str(tmp_path),
        1,
    )

    assert result["status"] == "errored"
    assert result["failure_reason"] == "inference_error"
    assert result["error"] == "provider: Insufficient Balance"


def test_empty_prediction_timeout_is_no_pred(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.close_logger",
        lambda *_args: None,
    )

    result = _evaluate_one(
        {"instance_id": "demo__repo-1"},
        {
            "model_patch": "diff --git a/test.py b/test.py\n",
            "model_name_or_path": "model",
            "error": "timeout",
        },
        "run",
        object(),
        str(tmp_path),
        1,
    )

    assert result["status"] == "no-pred"
    assert result["failure_reason"] == ""
    assert result["error"] == "timeout"


def test_evaluation_rejects_runaway_cached_patch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.MAX_GENERATED_TEST_PATCH_BYTES",
        10,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.test_generation_eval.close_logger",
        lambda *_args: None,
    )

    result = _evaluate_one(
        {"instance_id": "demo__repo-1"},
        {"model_patch": "x" * 11, "model_name_or_path": "model"},
        "run",
        object(),
        str(tmp_path),
        1,
    )

    assert result["status"] == "errored"
    assert result["failure_reason"] == "prediction_patch_too_large"
    assert "11 bytes" in result["error"]
