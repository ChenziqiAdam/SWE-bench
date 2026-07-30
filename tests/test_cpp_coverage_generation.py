import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from swebench.eval_pipeline.coverage_adapters import (
    default_commands,
    detect_coverage_language,
    discover_cpp_sources,
    install_coverage_runner,
    is_cpp_test_path,
    is_test_local_cmake,
    parse_gcovr_json,
    strip_cpp_coverage_artifacts,
)
from swebench.eval_pipeline.coverage_generation_eval import inspect_test_patch
from swebench.eval_pipeline.coverage_generation_eval import _run_cpp_container
from swebench.eval_pipeline.cpp_coverage_runner import run as run_cpp_coverage_runner
from swebench.eval_pipeline.run_pipeline import _standalone_coverage_instance, parse_args


def test_language_detection_rejects_mixed_repository(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("project(demo)\n")
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    assert detect_coverage_language(tmp_path) == "cpp"
    (tmp_path / "tools.py").write_text("")
    with pytest.raises(ValueError, match="mixed Python and CMake/C\\+\\+"):
        detect_coverage_language(tmp_path)
    assert detect_coverage_language(tmp_path, profile_language="cpp") == "cpp"


def test_cpp_source_discovery_excludes_tests_build_and_vendor(tmp_path):
    for relative in [
        "src/core.cpp",
        "include/core.hpp",
        "tests/test_core.cpp",
        "build/generated.cpp",
        "vendor/dependency.cc",
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    assert discover_cpp_sources(tmp_path) == ["include/core.hpp", "src/core.cpp"]


@pytest.mark.parametrize(
    "path",
    ["tests/core.cpp", "src/core_test.cc", "unittest/TestThing.cxx"],
)
def test_cpp_test_paths(path):
    assert is_cpp_test_path(path)
    assert not is_cpp_test_path("src/core.cpp")


def test_cpp_patch_accepts_assertion_frameworks_and_test_local_cmake():
    patch = """\
diff --git a/tests/new_test.cpp b/tests/new_test.cpp
new file mode 100644
--- /dev/null
+++ b/tests/new_test.cpp
@@ -0,0 +1,6 @@
+TEST(Core, Edge) {
+  ASSERT_EQ(run(), 2);
+  CHECK(result);
+  BOOST_CHECK_EQUAL(value, 3);
+  ASSERT_EQUAL_TOL(expected, actual, 1e-6);
+}
diff --git a/tests/CMakeLists.txt b/tests/CMakeLists.txt
--- a/tests/CMakeLists.txt
+++ b/tests/CMakeLists.txt
@@ -1,0 +2 @@
+add_executable(new_test new_test.cpp)
"""
    info = inspect_test_patch(patch, "cpp")
    assert info["tests_only_patch"]
    assert info["added_test_count"] == 1
    assert info["added_assertion_count"] == 4
    assert is_test_local_cmake("tests/CMakeLists.txt")


def test_cpp_patch_rejects_root_cmake_and_deletions():
    root = """\
diff --git a/CMakeLists.txt b/CMakeLists.txt
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -1,0 +2 @@
+add_subdirectory(tests)
"""
    assert inspect_test_patch(root, "cpp")["illegal_changed_files"] == ["CMakeLists.txt"]
    deletion = """\
diff --git a/tests/test_core.cpp b/tests/test_core.cpp
--- a/tests/test_core.cpp
+++ b/tests/test_core.cpp
@@ -1 +1 @@
-ASSERT_TRUE(old_value);
+ASSERT_TRUE(new_value);
"""
    assert not inspect_test_patch(deletion, "cpp")["no_existing_test_lines_removed"]


def test_gcovr_summary_normalizes_to_common_schema():
    payload = json.dumps({
        "format_version": "0.8",
        "files": [
            {
                "filename": "src/core.cpp",
                "line_total": 10,
                "line_covered": 7,
                "branch_total": 4,
                "branch_covered": 2,
            },
            {
                "filename": "tests/test_core.cpp",
                "line_total": 5,
                "line_covered": 5,
                "branch_total": 0,
                "branch_covered": 0,
            },
        ],
    })
    result = parse_gcovr_json(payload)
    assert result["line_coverage"] == 70.0
    assert result["branch_coverage"] == 50.0
    assert list(result["files"]) == ["src/core.cpp"]


def test_cpp_default_commands_and_helper(tmp_path):
    (tmp_path / ".git").mkdir()
    commands = default_commands("cpp", ["src"])
    assert "-G Ninja" in commands.setup
    assert "--json-summary {output}" in commands.report
    helper = install_coverage_runner(
        tmp_path,
        {
            "coverage_language": "cpp",
            "coverage_container_image": "example/coverage:latest",
            "coverage_setup_command": commands.setup,
            "coverage_test_command": commands.test,
            "coverage_reset_command": commands.reset,
            "coverage_command": commands.run,
            "coverage_results_command": commands.report,
        },
    )
    source = helper.read_text()
    config = json.loads((tmp_path / ".git" / "coverage-runner.json").read_text())
    assert "swebench.eval_pipeline.cpp_coverage_runner" in source
    assert config["image"] == "example/coverage:latest"
    assert config["test"] == "ctest --test-dir build --output-on-failure"
    assert "coverage-summary.json" in config["report"]
    assert helper.stat().st_mode & 0o111


def test_cpp_patch_capture_strips_build_artifacts():
    patch = """\
diff --git a/build/generated.cpp b/build/generated.cpp
new file mode 100644
--- /dev/null
+++ b/build/generated.cpp
@@ -0,0 +1 @@
+generated
diff --git a/tests/test_core.cpp b/tests/test_core.cpp
new file mode 100644
--- /dev/null
+++ b/tests/test_core.cpp
@@ -0,0 +1 @@
+ASSERT_TRUE(true);
"""
    cleaned = strip_cpp_coverage_artifacts(patch)
    assert "build/generated.cpp" not in cleaned
    assert "tests/test_core.cpp" in cleaned


def test_openmm_profile_is_cpu_only_and_mutation_unsupported(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--repo_url",
            "https://github.com/openmm/openmm.git",
            "--base_commit",
            "3ff9269047207049c2f4bd3ae960dca7b717d29a",
        ],
    )
    instance = _standalone_coverage_instance(parse_args())
    assert instance["coverage_language"] == "cpp"
    assert "OPENMM_BUILD_CPU_LIB=ON" in instance["coverage_setup_command"]
    assert "OPENMM_BUILD_CUDA_LIB=OFF" in instance["coverage_setup_command"]
    assert "OPENMM_BUILD_SERIALIZATION_TESTS=ON" in instance["coverage_setup_command"]
    assert "python3 ../devtools/run-ctest.py --attempts 0" in instance[
        "coverage_test_command"
    ]
    assert "--timeout 900" in instance["coverage_test_command"]
    assert "Testing/Temporary/LastTestsFailed.log" in instance[
        "coverage_test_command"
    ]
    assert "ctest --output-on-failure --rerun-failed" in instance[
        "coverage_test_command"
    ]
    assert instance["coverage_test_command"].startswith("(cd build &&")
    assert instance["coverage_test_command"].endswith(")")
    assert instance["coverage_tool_install_command"] == "true"
    assert instance["coverage_phase_timeout"] == 14400
    assert "gcovr" in instance["coverage_results_command"]
    assert (
        "--gcov-ignore-parse-errors=suspicious_hits.warn_once_per_file"
        in instance["coverage_results_command"]
    )
    assert (
        "--exclude '.*/(tests?|serialization/tests)/.*'"
        in instance["coverage_results_command"]
    )
    assert instance["mutation_supported"] is False


def test_openmm_retry_command_propagates_retry_status(tmp_path, monkeypatch):
    root = tmp_path / "openmm"
    build = root / "build"
    devtools = root / "devtools"
    fake_bin = root / "bin"
    build.mkdir(parents=True)
    devtools.mkdir()
    fake_bin.mkdir()
    (devtools / "run-ctest.py").write_text(
        "from pathlib import Path\n"
        "failed = Path('Testing/Temporary/LastTestsFailed.log')\n"
        "failed.parent.mkdir(parents=True, exist_ok=True)\n"
        "failed.write_text('1:TimedOutTest\\n')\n"
        "raise SystemExit(1)\n"
    )
    ctest_log = root / "ctest-args.log"
    ctest = fake_bin / "ctest"
    ctest.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$*\" > \"$CTEST_ARGS_LOG\"\n"
        "exit \"${FAKE_CTEST_EXIT:-0}\"\n"
    )
    ctest.chmod(0o755)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--repo_url",
            "https://github.com/openmm/openmm.git",
            "--base_commit",
            "3ff9269047207049c2f4bd3ae960dca7b717d29a",
        ],
    )
    command = _standalone_coverage_instance(parse_args())["coverage_test_command"]
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "CTEST_ARGS_LOG": str(ctest_log),
        "FAKE_CTEST_EXIT": "0",
    }
    completed = subprocess.run(["bash", "-c", command], cwd=root, env=env)
    assert completed.returncode == 0
    assert "--rerun-failed" in ctest_log.read_text()

    env["FAKE_CTEST_EXIT"] = "7"
    completed = subprocess.run(["bash", "-c", command], cwd=root, env=env)
    assert completed.returncode == 7


def test_cpp_rejects_pynguin(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--repo_url",
            "https://github.com/example/cpp.git",
            "--base_commit",
            "a" * 40,
            "--coverage_language",
            "cpp",
            "--traditional_test_generator",
            "pynguin",
        ],
    )
    with pytest.raises(SystemExit, match="Pynguin"):
        _standalone_coverage_instance(parse_args())


def test_cpp_mutation_requires_both_custom_commands(monkeypatch):
    base = [
        "run_pipeline",
        "--repo_url",
        "https://github.com/example/cpp.git",
        "--base_commit",
        "a" * 40,
        "--coverage_language",
        "cpp",
        "--coverage_target",
        "src/core.cpp",
        "--mutation_command",
        "mull {targets}",
    ]
    monkeypatch.setattr(sys, "argv", base)
    assert _standalone_coverage_instance(parse_args())["mutation_supported"] is False
    monkeypatch.setattr(
        sys,
        "argv",
        base + ["--mutation_results_command", "mull-report"],
    )
    assert _standalone_coverage_instance(parse_args())["mutation_supported"] is True


def test_cpp_container_is_offline_unprivileged_and_mount_scoped(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    results = tmp_path / "results"
    repo.mkdir()
    results.mkdir()
    (results / "phase.sh").write_text("#!/bin/bash\n")
    captured = {}

    class Image:
        attrs = {"RepoDigests": ["example@sha256:abc"]}
        id = "sha256:abc"

    class Container:
        def remove(self, force=False):
            captured["removed"] = force

    class Images:
        def get(self, name):
            return Image()

    class Containers:
        def run(self, image, command, **kwargs):
            captured.update(image=image, command=command, kwargs=kwargs)
            return Container()

    class Client:
        images = Images()
        containers = Containers()

        def version(self):
            return {"Platform": {"Name": "Podman Engine"}}

        def close(self):
            captured["closed"] = True

    outputs = iter([
        ("gcc 12.5\ncmake 3.25.1\ngcovr 8.6\n", False, 0.1),
        ("SETUP_EXIT=0\n", False, 0.2),
    ])
    monkeypatch.setattr(
        "swebench.eval_pipeline.coverage_generation_eval.docker.from_env",
        lambda: Client(),
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.coverage_generation_eval.exec_run_with_timeout",
        lambda *args, **kwargs: next(outputs),
    )
    instance = {"coverage_container_image": "example:fixed"}
    _run_cpp_container(instance, repo, results, "phase.sh", "phase", 30)
    options = captured["kwargs"]
    assert options["network_disabled"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["userns_mode"] == "host"
    assert options["user"] == "0:0"
    assert len(options["volumes"]) == 2
    assert options["user"].count(":") == 1
    assert instance["coverage_container_digest"] == "example@sha256:abc"


def test_agent_cpp_runner_uses_same_offline_container_policy(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    config_path = repo / ".git" / "coverage-runner.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({
        "image": "example:fixed",
        "timeout": 30,
        "setup": "cmake --build build",
        "test": "ctest --test-dir build",
        "reset": "true",
        "coverage": "ctest --test-dir build",
        "report": "gcovr --json-summary .git/coverage-summary.json",
    }))
    captured = {}

    class Container:
        def wait(self, timeout):
            captured["timeout"] = timeout
            return {"StatusCode": 0}

        def logs(self, stdout=True, stderr=True):
            return b"ok\n"

        def remove(self, force=False):
            captured["removed"] = force

    class Images:
        def get(self, name):
            captured["image_get"] = name

    class Containers:
        def run(self, image, command, **kwargs):
            captured.update(image=image, command=command, kwargs=kwargs)
            return Container()

    class Client:
        images = Images()
        containers = Containers()

        def version(self):
            return {"Platform": {"Name": "Podman Engine"}}

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(
        "swebench.eval_pipeline.cpp_coverage_runner.docker.from_env",
        lambda: Client(),
    )
    assert run_cpp_coverage_runner(config_path, "test", ["-R", "Focused"]) == 0
    options = captured["kwargs"]
    assert options["network_disabled"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["userns_mode"] == "host"
    assert options["user"] == "0:0"
    assert len(options["volumes"]) == 1
    assert "ctest --test-dir build --output-on-failure -R Focused" in " ".join(
        captured["command"]
    )


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("cmake", "ninja", "gcovr", "c++")),
    reason="C++ coverage integration tools are unavailable",
)
def test_tiny_cmake_ctest_patch_increases_branch_coverage(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "cpp_coverage"
    checkout = tmp_path / "checkout"
    shutil.copytree(fixture, checkout)

    def measure(output_name):
        subprocess.run(
            ["cmake", "-S", ".", "-B", "build", "-G", "Ninja"],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["cmake", "--build", "build"],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        for gcda in (checkout / "build").rglob("*.gcda"):
            gcda.unlink()
        subprocess.run(
            ["ctest", "--test-dir", "build", "--output-on-failure"],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        output = checkout / output_name
        subprocess.run(
            [
                "gcovr", "--root", ".", "--filter", "src",
                "--json-summary", str(output),
            ],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        return parse_gcovr_json(output.read_text())

    before = measure("before.json")
    (checkout / "tests" / "test_edges.cpp").write_text(
        '#include "core.hpp"\n#include <cassert>\n'
        "int main() { assert(classify_number(-2) == -1); "
        "assert(classify_number(0) == 0); }\n"
    )
    with (checkout / "CMakeLists.txt").open("a") as handle:
        handle.write(
            "\nadd_executable(test_edges tests/test_edges.cpp)\n"
            "target_link_libraries(test_edges PRIVATE core)\n"
            "add_test(NAME edges COMMAND test_edges)\n"
        )
    after = measure("after.json")
    assert after["branch_coverage"] > before["branch_coverage"]
