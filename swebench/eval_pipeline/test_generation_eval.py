"""Evaluate agent-generated regression tests.

This mode treats ``model_patch`` as a test patch. A success requires the patch
to apply, at least one generated/modified test to fail on the base code, and the
same failing test(s) to pass after the golden patch is applied.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import docker

from swebench.eval_pipeline.instance_builder import _is_test_path
from swebench.eval_pipeline.prediction_utils import read_prediction_rows
from swebench.harness.constants import (
    END_TEST_OUTPUT,
    MAP_REPO_TO_TEST_GENERATION_CAPABILITIES,
    MAP_REPO_VERSION_TO_SPECS,
    START_TEST_OUTPUT,
    TestStatus,
)
from swebench.harness.docker_build import build_container, close_logger, setup_logger
from swebench.harness.docker_utils import (
    cleanup_container,
    copy_to_container,
    exec_run_with_timeout,
)
from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
from swebench.harness.test_spec.python import get_test_directives
from swebench.harness.test_spec.test_spec import make_test_spec
from swebench.harness.test_spec.utils import get_test_cmds

logger = logging.getLogger(__name__)
MAX_GENERATED_TEST_PATCH_BYTES = 1_000_000

GENERATED_TEST_PATCH = "/tmp/generated_test.patch"
GOLD_PATCH = "/tmp/gold.patch"
GEN_APPLY_PASS = "GENERATED_TEST_PATCH_APPLIED"
GEN_APPLY_FAIL = "GENERATED_TEST_PATCH_FAILED"
GOLD_APPLY_PASS = "GOLD_PATCH_APPLIED"
GOLD_APPLY_FAIL = "GOLD_PATCH_FAILED"
BUILD_FAIL = "GENERATED_TEST_BUILD_FAILED"
UNSUPPORTED_GENERATED_TEST = "UNSUPPORTED_GENERATED_TEST"
NO_TESTS_SELECTED = "NO_GENERATED_TESTS_SELECTED"


@dataclass(frozen=True)
class GeneratedTestExecutionPlan:
    """Auditable commands selected from a generated test patch."""

    languages: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    build_targets: tuple[str, ...] = ()
    failure_reason: str | None = None
    evidence: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _passed(status: str | None) -> bool:
    return status in {TestStatus.PASSED.value, TestStatus.XFAIL.value}


def _failed(status: str | None) -> bool:
    return status in {TestStatus.FAILED.value, TestStatus.ERROR.value}


def classify_test_generation_result(
    base_status_map: dict[str, str],
    gold_status_map: dict[str, str],
    test_patch_applied: bool,
    gold_patch_applied: bool,
    had_runtime_error: bool = False,
    base_timed_out: bool = False,
    gold_timed_out: bool = False,
    test_execution_failed: bool = False,
    no_tests_selected: bool = False,
    collection_failed: bool = False,
    non_evaluable: bool = False,
    infrastructure_failed: bool = False,
    build_failed: bool = False,
    base_build_failed: bool = False,
    gold_build_failed: bool = False,
    unsupported_generated_test: bool = False,
) -> dict:
    """Classify strict SWT-Bench-style test-generation results."""
    failure_reason = ""
    if non_evaluable:
        status = "excluded"
        failure_reason = "non_evaluable_spec"
    elif infrastructure_failed:
        status = "excluded"
        failure_reason = "infrastructure_failure"
    elif not test_patch_applied or had_runtime_error:
        status = "errored"
        failure_reason = "test_patch_failed_or_timeout"
    elif not gold_patch_applied:
        status = "errored"
        failure_reason = "gold_patch_failed"
    elif base_timed_out or gold_timed_out:
        status = "unresolved"
        failure_reason = (
            "generated_test_timed_out_on_gold"
            if gold_timed_out
            else "generated_test_timed_out_on_base"
        )
    elif build_failed:
        status = "errored"
        failure_reason = "generated_test_build_failed"
    elif gold_build_failed:
        # A generated test that does not build against the fix is a model/test
        # failure, not an evaluator infrastructure error.
        return {
            "status": "unresolved",
            "failure_reason": "generated_test_did_not_build_on_gold",
            "base_failed_tests": (
                ["generated_test_build"]
                if base_build_failed
                else sorted(t for t, s in base_status_map.items() if _failed(s))
            ),
            "gold_passed_tests": [],
        }
    elif collection_failed:
        status = "unresolved"
        failure_reason = "generated_test_collection_failed"
    elif unsupported_generated_test:
        status = "not_exercised"
        failure_reason = "unsupported_generated_test"
    elif no_tests_selected:
        status = "not_exercised"
        failure_reason = "no_tests_selected"
    elif base_build_failed:
        # A generated regression test may intentionally use an API introduced
        # by the fix.  Failing to compile on base is therefore a valid failing
        # test when the same patch builds and all selected tests pass on gold.
        gold_failed = sorted(t for t, s in gold_status_map.items() if _failed(s))
        gold_passed = sorted(t for t, s in gold_status_map.items() if _passed(s))
        resolved = bool(gold_passed) and not gold_failed
        return {
            "status": "resolved" if resolved else "unresolved",
            "failure_reason": "" if resolved else "gold_did_not_pass",
            "base_failed_tests": ["generated_test_build"],
            "gold_passed_tests": (
                ["generated_test_build"] if resolved else []
            ),
        }
    elif test_execution_failed and (not base_status_map or not gold_status_map):
        status = "unresolved"
        failure_reason = "generated_test_execution_failed"
    elif not base_status_map or not gold_status_map:
        status = "errored"
        failure_reason = "no_parseable_test_status"
    else:
        base_failed = sorted(t for t, s in base_status_map.items() if _failed(s))
        gold_passed = sorted(t for t in base_failed if _passed(gold_status_map.get(t)))
        status = (
            "resolved"
            if base_failed and len(gold_passed) == len(base_failed)
            else "unresolved"
        )
        failure_reason = "" if status == "resolved" else (
            "base_did_not_fail" if not base_failed else "gold_did_not_pass"
        )
        return {
            "status": status,
            "failure_reason": failure_reason,
            "base_failed_tests": base_failed,
            "gold_passed_tests": gold_passed,
        }
    return {
        "status": status,
        "failure_reason": failure_reason,
        "base_failed_tests": [],
        "gold_passed_tests": [],
    }


def _non_evaluable_output(output: str) -> bool:
    return any(
        marker in output
        for marker in (
            "not evaluable:",
            "has no curated generated pytest target",
        )
    )


def _infrastructure_failure_output(output: str) -> bool:
    """Recognize host/toolchain failures unrelated to a generated test oracle."""
    direct_failure = any(
        marker in output
        for marker in (
            "fatal error: GL/gl.h: No such file or directory",
            "error: unknown target CPU 'generic'",
            "ninja: fatal: posix_spawn: Operation not permitted",
            "This test is stochastic and may occasionally fail",
            "CL_KHR_COMMAND_BUFFER_EXTENSION_VERSION > CL_MAKE_VERSION",
            "size of array 'altStackMem' is not an integral constant-expression",
            "call to non-'constexpr' function 'long int sysconf(int)'",
            "CMake 3.23.0 or higher is required",
            "pocl_llvm_build.cc:",
            "LLVM ERROR: Cannot select:",
            "error: cannot convert ‘PyObject*’",
        )
    )
    pocl_runtime_failure = (
        "WARNING: Using an unsupported OpenCL implementation" in output
        and any(
            marker in output
            for marker in (
                "clCreateBuffer (-61)",
                "exception: clCreateKernel",
                "Segmentation fault",
                "Illegal instruction",
            )
        )
    )
    preload_failure = (
        "/tmp/swebench_pocl_cpu_compat.so" in output
        and any(
            marker in output
            for marker in ("Segmentation fault", "Illegal instruction", "Aborted")
        )
    )
    return direct_failure or pocl_runtime_failure or preload_failure


def _no_tests_selected(output: str) -> bool:
    return any(
        marker in output
        for marker in (
            " 0 selected",
            "collected 0 items",
            "No tests were found!!!",
            "has no curated generated-test target",
            NO_TESTS_SELECTED,
        )
    )


def _test_collection_failed(output: str) -> bool:
    """Distinguish broken collection/imports from a valid empty selection."""
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in (
            "error collecting",
            "errors during collection",
            "error during collection",
            "found no collectors",
        )
    )


def _test_execution_failed(output: str) -> bool:
    """Detect a generated test process that failed before a parser status."""
    if START_TEST_OUTPUT not in output:
        return False
    test_output = output.split(START_TEST_OUTPUT, 1)[1]
    return any(
        marker in test_output
        for marker in (
            "Traceback (most recent call last):",
            "ImportError:",
            "ModuleNotFoundError:",
            "Segmentation fault",
            "command not found",
        )
    )


def _exclude_gold_test_files(gold_patch: str) -> tuple[str, list[str]]:
    """Apply only the gold implementation, never PR-authored tests.

    Some C/C++ test files were historically misclassified into the gold patch.
    Applying them can conflict with the independently generated test or make
    unrelated old tests fail after a partial gold extraction.
    """
    sections = re.split(r"(?=^diff --git )", gold_patch, flags=re.MULTILINE)
    kept: list[str] = []
    excluded: set[str] = set()
    for section in sections:
        match = re.match(r"^diff --git a/(.+?) b/(.+)$", section, re.MULTILINE)
        test_paths = (
            {path for path in match.groups() if _is_test_path(path)}
            if match
            else set()
        )
        if test_paths:
            excluded.update(test_paths)
        else:
            kept.append(section)
    return "".join(kept), sorted(excluded)


def _prepare_gold_patch(gold_patch: str) -> tuple[str, list[str], list[str]]:
    """Remove PR tests and binary placeholders unavailable in GitHub patches."""
    without_tests, excluded_tests = _exclude_gold_test_files(gold_patch)
    sections = re.split(r"(?=^diff --git )", without_tests, flags=re.MULTILINE)
    kept: list[str] = []
    excluded_binary: set[str] = set()
    for section in sections:
        match = re.match(r"^diff --git a/(.+?) b/(.+)$", section, re.MULTILINE)
        if match and re.search(r"^Binary files .+ differ$", section, re.MULTILINE):
            excluded_binary.update(match.groups())
        else:
            kept.append(section)
    return "".join(kept), excluded_tests, sorted(excluded_binary)


def _openmm_generated_pytest_command(
    pytest_targets: list[str],
    pytest_filter: str | None = None,
) -> str:
    command = (
        "export LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
        "OPENMM_PLUGIN_DIR=$PWD/build && "
        "cd wrappers/python/tests && python -m pytest -xvs "
        + " ".join(pytest_targets)
    )
    if pytest_filter:
        command += f" -k '{pytest_filter}'"
    return command


def _openmm_generated_pytest_targets(
    generated_patch: str,
) -> tuple[list[str], str | None]:
    """Return generated OpenMM pytest nodeids, falling back to touched files.

    Running an entire touched OpenMM test file can include unrelated legacy
    tests that fail on gold and make the report noisy.  When the generated patch
    adds pytest/unittest test methods, run those nodeids directly.
    """
    prefix = "wrappers/python/tests/"
    files: set[str] = set()
    nodeids: set[str] = set()
    test_names: set[str] = set()
    unknown_class_files: set[str] = set()
    current_file = None
    current_class = None
    current_test = None
    current_test_indentation = None
    for raw in generated_patch.splitlines():
        diff_match = re.match(r"^diff --git a/(\S+) b/\S+", raw)
        if diff_match:
            current_file = diff_match.group(1)
            current_class = None
            current_test = None
            current_test_indentation = None
            if (
                current_file.startswith(prefix)
                and current_file.endswith(".py")
                and re.match(r"(?:Test|test).*\.py$", PurePosixPath(current_file).name)
            ):
                files.add(current_file[len(prefix):])
            continue
        if not current_file or current_file not in {prefix + f for f in files}:
            continue
        hunk_match = re.match(r"^@@.*@@\s*(?:class\s+([A-Za-z_]\w*)\b.*)?$", raw)
        if hunk_match:
            current_class = hunk_match.group(1)
            current_test = None
            current_test_indentation = None
            continue
        content = raw[1:] if raw.startswith(("+", " ")) else raw
        class_match = re.match(r"^\s*class\s+([A-Za-z_]\w*)\b", content)
        if class_match:
            current_class = class_match.group(1)
            current_test = None
            current_test_indentation = None
            continue
        test_match = re.match(r"^(\s*)def\s+(test_[A-Za-z_]\w*)\s*\(", content)
        if test_match:
            current_test = test_match.group(2)
            current_test_indentation = test_match.group(1)
            if not raw.startswith("+"):
                continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        test_name = test_match.group(2) if test_match else current_test
        if not test_name:
            continue
        file_name = current_file[len(prefix):]
        indentation = (
            test_match.group(1)
            if test_match
            else current_test_indentation
        )
        if indentation is None:
            continue
        if not indentation:
            nodeids.add(f"{file_name}::{test_name}")
        elif current_class:
            nodeids.add(f"{file_name}::{current_class}::{test_name}")
        else:
            unknown_class_files.add(file_name)
            test_names.add(test_name)
    if nodeids and not unknown_class_files:
        return sorted(nodeids), None
    if test_names:
        return sorted(unknown_class_files or files), " or ".join(sorted(test_names))
    return sorted(files), None


def _rdkit_generated_unittest_targets(generated_patch: str) -> dict[str, list[str]]:
    """Return added RDKit unittest methods grouped by their Python test file."""
    targets: dict[str, set[str]] = {}
    current_file = None
    current_class = None
    for raw in generated_patch.splitlines():
        diff_match = re.match(r"^diff --git a/(\S+) b/\S+", raw)
        if diff_match:
            current_file = diff_match.group(1)
            current_class = None
            continue
        if not current_file or not current_file.endswith(".py"):
            continue
        hunk_match = re.match(r"^@@.*@@\s*(?:class\s+([A-Za-z_]\w*)\b.*)?$", raw)
        if hunk_match:
            current_class = hunk_match.group(1)
            continue
        content = raw[1:] if raw.startswith(("+", " ")) else raw
        class_match = re.match(r"^\s*class\s+([A-Za-z_]\w*)\b", content)
        if class_match:
            current_class = class_match.group(1)
            continue
        if not raw.startswith("+") or raw.startswith("+++") or not current_class:
            continue
        test_match = re.match(r"^\s+def\s+(test[A-Za-z0-9_]*)\s*\(", content)
        if test_match:
            targets.setdefault(current_file, set()).add(
                f"{current_class}.{test_match.group(1)}"
            )
    return {path: sorted(names) for path, names in sorted(targets.items())}


def _rdkit_test_name_tokens(name: str) -> frozenset[str]:
    """Normalize RDKit Catch source and CTest target names for comparison."""
    words: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", name):
        words.extend(
            re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", part)
        )
    return frozenset(
        word.lower() for word in words if word.lower() not in {"test", "tests"}
    )


def _rdkit_isolated_cpp_commands(
    commands: list[str], generated_patch: str
) -> list[str] | None:
    """Run only configured CTest targets matching generated RDKit test sources."""
    source_tokens: set[frozenset[str]] = set()
    for path in re.findall(r"^diff --git a/(\S+) b/\S+", generated_patch, re.MULTILINE):
        if Path(path).suffix.lower() in {".cc", ".cpp", ".cxx"} and _is_test_path(path):
            tokens = _rdkit_test_name_tokens(PurePosixPath(path).stem)
            if tokens:
                source_tokens.add(tokens)
    if not source_tokens:
        return None

    isolated: list[str] = []
    for command in commands:
        match = re.search(r"-R\s+['\"]?\^([^$'\"]+)\$['\"]?", command)
        if not match:
            continue
        target = match.group(1).replace("\\", "")
        if _rdkit_test_name_tokens(target) in source_tokens:
            isolated.append(command)
    return isolated or None


def _rdkit_isolated_python_commands(
    commands: list[str], generated_patch: str
) -> list[str] | None:
    """Add unittest method selectors to matching RDKit Python commands."""
    targets = _rdkit_generated_unittest_targets(generated_patch)
    if not targets:
        return None
    isolated: list[str] = []
    matched = False
    for command in commands:
        updated = command
        for path, names in targets.items():
            pattern = rf"(\bpython3?\s+{re.escape(path)})(?!\S)"
            if re.search(pattern, updated):
                updated = re.sub(pattern, rf"\1 {' '.join(names)}", updated, count=1)
                matched = True
        isolated.append(updated)
    return isolated if matched else None


def _qgis_isolated_python_command(
    specs: dict,
    generated_patch: str,
) -> str | None:
    """Run only added QGIS unittest methods under the built Python environment."""
    path = specs.get("test_generation_python_test")
    if not path:
        return None
    names = _rdkit_generated_unittest_targets(generated_patch).get(path)
    if not names:
        return None
    return (
        "QGIS_PREFIX_PATH=/testbed/build/output "
        "LD_LIBRARY_PATH=/testbed/build/output/lib:${LD_LIBRARY_PATH:-} "
        "PYTHONPATH=/testbed/build/output/python:"
        "/testbed/build/output/python/plugins:/testbed/tests/src/python:"
        "${PYTHONPATH:-} "
        "QT_QPA_PLATFORM=offscreen xvfb-run -a "
        f"python3 /testbed/{path} {' '.join(names)}"
    )


def _generated_python_test_nodeids(
    generated_patch: str, prefix: str = ""
) -> tuple[list[str], list[str]]:
    """Return touched Python test files and added pytest/unittest node IDs."""
    files: set[str] = set()
    nodeids: set[str] = set()
    current_file = None
    current_class = None
    for raw in generated_patch.splitlines():
        diff_match = re.match(r"^diff --git a/(\S+) b/\S+", raw)
        if diff_match:
            current_file = diff_match.group(1)
            current_class = None
            if current_file.startswith(prefix) and current_file.endswith(".py"):
                files.add(current_file)
            continue
        if current_file not in files:
            continue
        hunk_match = re.match(r"^@@.*@@\s*(?:class\s+([A-Za-z_]\w*)\b.*)?$", raw)
        if hunk_match:
            if hunk_match.group(1):
                current_class = hunk_match.group(1)
            continue
        content = raw[1:] if raw.startswith(("+", " ")) else raw
        class_match = re.match(r"^\s*class\s+([A-Za-z_]\w*)\b", content)
        if class_match:
            current_class = class_match.group(1)
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        test_match = re.match(r"^(\s*)def\s+(test[A-Za-z0-9_]*)\s*\(", content)
        if not test_match:
            continue
        path = current_file[len(prefix):] if prefix else current_file
        if test_match.group(1) and current_class:
            nodeids.add(f"{path}::{current_class}::{test_match.group(2)}")
        else:
            nodeids.add(f"{path}::{test_match.group(2)}")
    return sorted(files), sorted(nodeids)


def _biopython_generated_test_command(generated_patch: str) -> str | None:
    files, nodeids = _generated_python_test_nodeids(generated_patch, "Tests/")
    if not files:
        return None
    targets = nodeids or [path[len("Tests/"):] for path in files]
    return (
        "cd /testbed/Tests && PYTHONPATH=/testbed:${PYTHONPATH:-} "
        "pytest -rA --tb=long -p no:cacheprovider " + " ".join(targets)
    )


def _lammps_generated_test_targets(generated_patch: str) -> list[tuple[str, str]]:
    """Map touched LAMMPS unit-test sources to CMake targets and binaries.

    LAMMPS's top-level CMakeLists.txt sets CMAKE_RUNTIME_OUTPUT_DIRECTORY to
    CMAKE_BINARY_DIR, so every executable (including unittest/* gtest
    binaries) lands flat in build/, not nested under build/unittest/<subdir>/.
    """
    targets: set[tuple[str, str]] = set()
    paths = re.findall(r"^diff --git a/(\S+) b/\S+", generated_patch, re.MULTILINE)
    for path in paths:
        match = re.match(r"unittest/(.+)/([^/]+)\.cpp$", path)
        if match and _is_test_path(path):
            _subdir, stem = match.groups()
            targets.add((stem, f"build/{stem}"))
    return sorted(targets)


def _lammps_generated_test_command(generated_patch: str) -> str | None:
    targets = _lammps_generated_test_targets(generated_patch)
    commands = [binary for _target, binary in targets]
    files, nodeids = _generated_python_test_nodeids(generated_patch)
    test_files = [path for path in files if _is_test_path(path)]
    if test_files:
        selected = [node for node in nodeids if node.split("::", 1)[0] in test_files]
        commands.append(
            "PYTHONPATH=/testbed:${PYTHONPATH:-} python3 -m pytest -rA --tb=long "
            "-p no:cacheprovider " + " ".join(selected or test_files)
        )
    return " && ".join(commands) if commands else None


def _patch_paths(generated_patch: str) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"^diff --git a/(\S+) b/\S+", generated_patch, re.MULTILINE
            )
        )
    )


def _cmake_registered_cpp_targets(generated_patch: str) -> dict[str, str]:
    """Return source basename -> CTest/build target from added registrations."""
    registrations: dict[str, str] = {}
    added = "\n".join(
        line[1:] for line in generated_patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    for match in re.finditer(
        r"rdkit_(?:catch_)?test\s*\(\s*([\w.-]+)\s+([^)]*)\)",
        added,
        re.DOTALL,
    ):
        target, sources = match.groups()
        for source in re.findall(r"[\w./+-]+\.(?:cc|cpp|cxx)", sources):
            registrations[PurePosixPath(source).name] = target
    executables: dict[str, list[str]] = {}
    for match in re.finditer(
        r"add_executable\s*\(\s*([\w.-]+)\s+([^)]*)\)", added, re.DOTALL
    ):
        executable, sources = match.groups()
        executables[executable] = re.findall(
            r"[\w./+-]+\.(?:cc|cpp|cxx)", sources
        )
    ctest_names: dict[str, str] = {}
    for match in re.finditer(
        r"add_test\s*\(\s*(?:NAME\s+)?([\w.-]+)"
        r"(?:\s+COMMAND)?\s+([\w.-]+)",
        added,
        re.DOTALL,
    ):
        test_name, executable = match.groups()
        ctest_names[executable] = test_name
    for executable, sources in executables.items():
        target = ctest_names.get(executable, executable)
        for source in sources:
            registrations[PurePosixPath(source).name] = target
    return registrations


def _configured_ctest_targets(commands: list[str]) -> dict[frozenset[str], str]:
    result = {}
    for command in commands:
        match = re.search(r"-R\s+['\"]?\^([^$'\"]+)\$['\"]?", command)
        if match:
            target = match.group(1).replace("\\", "")
            result[_rdkit_test_name_tokens(target)] = target
    return result


def _combine_selected_commands(commands: tuple[str, ...]) -> str:
    if len(commands) <= 1:
        return commands[0] if commands else ""
    parts = ["_sweb_test_rc=0"]
    parts.extend(f"( {command} ) || _sweb_test_rc=1" for command in commands)
    parts.append("( exit $_sweb_test_rc )")
    return "; ".join(parts)


def _special_repo_execution_plan(
    instance: dict, generated_patch: str, commands: list[str]
) -> GeneratedTestExecutionPlan | None:
    """Create a language-complete plan for the four no-test repositories."""
    repo = instance["repo"]
    capabilities = MAP_REPO_TO_TEST_GENERATION_CAPABILITIES.get(repo)
    if capabilities is None:
        return None
    if any("not evaluable:" in command for command in commands):
        return GeneratedTestExecutionPlan(
            failure_reason="non_evaluable_spec",
            evidence={"spec_commands": tuple(commands)},
        )

    paths = _patch_paths(generated_patch)
    accepted: dict[str, list[str]] = {"cpp": [], "python": []}
    rejected: list[str] = []
    for path in paths:
        suffix = PurePosixPath(path).suffix.lower()
        basename = PurePosixPath(path).name
        language = "python" if suffix == ".py" else (
            "cpp" if suffix in {".cc", ".cpp", ".cxx"} else None
        )
        canonical = False
        if repo == "openmm/openmm":
            canonical = (
                language == "python"
                and path.startswith("wrappers/python/tests/")
                and re.match(r"(?:Test|test).*\.py$", basename) is not None
            ) or (
                language == "cpp" and _is_test_path(path) and basename.startswith("Test")
            )
        elif repo == "rdkit/rdkit":
            canonical = bool(
                language
                and path.startswith(("Code/", "rdkit/", "External/"))
                and _is_test_path(path)
            )
        elif repo == "lammps/lammps":
            canonical = (
                language == "cpp" and re.match(r"unittest/.+/[^/]+\.cpp$", path)
                is not None
            ) or (
                language == "python"
                and path.startswith(("unittest/", "python/tests/"))
                and _is_test_path(path)
            )
        elif repo == "biopython/biopython":
            canonical = (
                language == "python"
                and path.startswith("Tests/")
                and _is_test_path(path)
            )
        if canonical and language in capabilities:
            accepted[language].append(path)
        elif _is_test_path(path) or language is not None:
            rejected.append(path)

    selected_paths = tuple(sorted(accepted["cpp"] + accepted["python"]))
    evidence = {
        "patch_paths": tuple(paths),
        "accepted_paths": selected_paths,
        "rejected_paths": tuple(sorted(rejected)),
    }
    if rejected:
        return GeneratedTestExecutionPlan(
            paths=selected_paths,
            failure_reason="unsupported_generated_test",
            evidence=evidence,
        )
    if not selected_paths:
        return GeneratedTestExecutionPlan(
            failure_reason="no_tests_selected", evidence=evidence
        )

    selected_commands: list[str] = []
    build_targets: list[str] = []
    if accepted["cpp"]:
        if repo == "openmm/openmm":
            registrations = _cmake_registered_cpp_targets(generated_patch)
            build_targets = sorted(
                {
                    registrations.get(
                        PurePosixPath(path).name, PurePosixPath(path).stem
                    )
                    for path in accepted["cpp"]
                }
            )
            selected_commands.extend(
                "LD_LIBRARY_PATH=$PWD/build:${LD_LIBRARY_PATH:-} "
                "OPENMM_PLUGIN_DIR=$PWD/build ./build/" + target
                for target in build_targets
            )
        elif repo == "lammps/lammps":
            targets = _lammps_generated_test_targets(generated_patch)
            build_targets = [target for target, _binary in targets]
            selected_commands.extend(binary for _target, binary in targets)
        elif repo == "rdkit/rdkit":
            registrations = _cmake_registered_cpp_targets(generated_patch)
            configured = _configured_ctest_targets(commands)
            sole_configured = (
                next(iter(configured.values())) if len(configured) == 1 else None
            )
            for path in accepted["cpp"]:
                target = registrations.get(PurePosixPath(path).name)
                if target is None:
                    target = configured.get(
                        _rdkit_test_name_tokens(PurePosixPath(path).stem)
                    )
                target = target or sole_configured
                if target is None:
                    return GeneratedTestExecutionPlan(
                        languages=("cpp",),
                        paths=selected_paths,
                        failure_reason="unsupported_generated_test",
                        evidence={**evidence, "unresolved_cpp_target": (path,)},
                    )
                build_targets.append(target)
            build_targets = sorted(set(build_targets))
            selected_commands.extend(
                "RDBASE=$PWD LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
                f"ctest --test-dir build -V -R '^{re.escape(target)}$'"
                for target in build_targets
            )

    if accepted["python"]:
        if repo == "openmm/openmm":
            targets, pytest_filter = _openmm_generated_pytest_targets(generated_patch)
            selected_commands.append(
                _openmm_generated_pytest_command(targets, pytest_filter)
            )
        elif repo == "biopython/biopython":
            selected_commands.append(_biopython_generated_test_command(generated_patch) or "")
        else:
            files, nodeids = _generated_python_test_nodeids(generated_patch)
            selected = [
                node for node in nodeids
                if node.split("::", 1)[0] in accepted["python"]
            ]
            prefix = (
                "RDBASE=$PWD PYTHONPATH=$PWD "
                "LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-} "
                if repo == "rdkit/rdkit"
                else "PYTHONPATH=/testbed:${PYTHONPATH:-} "
            )
            selected_commands.append(
                prefix + "python3 -m pytest -rA --tb=long -p no:cacheprovider "
                + " ".join(selected or accepted["python"])
            )

    languages = tuple(language for language in ("cpp", "python") if accepted[language])
    return GeneratedTestExecutionPlan(
        languages=languages,
        paths=selected_paths,
        commands=tuple(command for command in selected_commands if command),
        build_targets=tuple(build_targets),
        evidence=evidence,
    )


def _test_command(instance: dict, generated_patch: str) -> str:
    """Choose the command that runs the generated test patch."""
    raw_commands = get_test_cmds(instance)
    commands = raw_commands if isinstance(raw_commands, list) else [raw_commands]

    plan = _special_repo_execution_plan(instance, generated_patch, commands)
    if plan is not None:
        if plan.failure_reason == "unsupported_generated_test":
            return f"echo {UNSUPPORTED_GENERATED_TEST} && false"
        if plan.failure_reason == "no_tests_selected":
            return f"echo {NO_TESTS_SELECTED} && false"
        if plan.failure_reason == "non_evaluable_spec":
            return "echo 'not evaluable: generated test requires unavailable hardware' && false"
        return _combine_selected_commands(plan.commands)

    generated_instance = {**instance, "test_patch": generated_patch}
    directives = get_test_directives(generated_instance)

    # Scientific OpenMM specs normally contain a fixed selector for the
    # original PR test.  In test-generation mode that selector can silently
    # collect zero tests when the model chose a different regression-test name.
    # Run generated test nodeids when discoverable, otherwise touched pytest
    # files, instead of stale fixed selectors.
    specs = MAP_REPO_VERSION_TO_SPECS.get(instance["repo"], {}).get(
        str(instance.get("version", "")), {}
    )
    if instance["repo"] == "qgis/QGIS":
        isolated_command = _qgis_isolated_python_command(specs, generated_patch)
        if isolated_command:
            return isolated_command
    raw = commands[0] if len(commands) == 1 else None
    if raw and specs.get("test_generation_use_spec_cmd"):
        return raw
    if raw and isinstance(raw, str) and instance["repo"] not in {
        "openmm/openmm",
        "rdkit/rdkit",
    }:
        if directives:
            return " ".join([raw, *directives])
    return " && ".join(commands)


def _patch_driven_build_commands(
    repo: str, specs: dict, plan: GeneratedTestExecutionPlan | None
) -> list[str]:
    """Retarget configured builds to every language selected from the patch."""
    original = [*specs.get("build", []), *specs.get("build_after_test_patch", [])]
    if plan is None:
        return original
    if plan.failure_reason:
        return []
    if repo == "lammps/lammps":
        return [
            (
                "cmake --build build --parallel $(nproc) --target "
                + " ".join(plan.build_targets)
            )
            if command.startswith("cmake --build build") and plan.build_targets
            else command
            for command in original
        ]
    if repo not in {"openmm/openmm", "rdkit/rdkit"}:
        return original

    configure = next(
        (command for command in original if command.startswith("cmake ") and " -B " in command),
        None,
    )
    retained = [
        command for command in original
        if not command.startswith("cmake --build ") and command != configure
    ]
    if repo == "rdkit/rdkit":
        configure = configure or (
            "cmake -B build -S . -DCMAKE_BUILD_TYPE=Release "
            "-DRDK_INSTALL_INTREE=ON -DRDK_BUILD_CPP_TESTS=ON "
            "-DRDK_BUILD_PYTHON_WRAPPERS=ON"
        )
        configure = re.sub(
            r"-DRDK_BUILD_CPP_TESTS=(?:ON|OFF)",
            "-DRDK_BUILD_CPP_TESTS=ON",
            configure,
        )
        configure = re.sub(
            r"-DRDK_BUILD_PYTHON_WRAPPERS=(?:ON|OFF)",
            "-DRDK_BUILD_PYTHON_WRAPPERS=ON",
            configure,
        )
        build = (
            "cmake --build build --parallel $(nproc)"
            if "python" in plan.languages
            else "cmake --build build --parallel $(nproc) --target "
            + " ".join(plan.build_targets)
        )
        return [configure, *retained, build]

    configure = configure or (
        "cmake -B build -S . -DCMAKE_BUILD_TYPE=Release "
        "-DOPENMM_BUILD_CUDA_LIB=OFF -DOPENMM_BUILD_OPENCL_LIB=OFF "
        "-DOPENMM_BUILD_HIP_LIB=OFF -DOPENMM_BUILD_C_AND_FORTRAN_WRAPPERS=OFF"
    )
    retained = [
        command for command in retained
        if "OPENMM_SITE=" not in command and "SIMTK_SITE=" not in command
    ]
    wrapper_flag = "ON" if "python" in plan.languages else "OFF"
    if "-DOPENMM_BUILD_PYTHON_WRAPPERS=" in configure:
        configure = re.sub(
            r"-DOPENMM_BUILD_PYTHON_WRAPPERS=(?:ON|OFF)",
            f"-DOPENMM_BUILD_PYTHON_WRAPPERS={wrapper_flag}",
            configure,
        )
    else:
        configure += f" -DOPENMM_BUILD_PYTHON_WRAPPERS={wrapper_flag}"
    if "python" in plan.languages:
        retained.append(
            "if [ -f build/python/src/swig_lib/python/extend.i ]; then "
            "sed -i 's/^# Look/\\/\\/ Look/' "
            "build/python/src/swig_lib/python/extend.i; fi"
        )
    targets = list(plan.build_targets)
    if "python" in plan.languages:
        targets.insert(0, "install")
    build_commands = [
        "cmake --build build --parallel $(nproc) --target " + " ".join(targets)
    ] if targets else []
    if "python" in plan.languages:
        build_commands.append(
            "cmake --build build --parallel $(nproc) --target PythonInstall && "
            "python -c 'import openmm, simtk.openmm'"
        )
    source_setup = (
        ["python -m pip uninstall -y openmm || true"]
        if "python" in plan.languages
        else []
    )
    return [*source_setup, configure, *retained, *build_commands]


def _build_script(instance: dict, generated_patch: str, apply_gold: bool) -> str:
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    repo_dir = "/testbed"
    base_commit = instance["base_commit"]
    raw_commands = get_test_cmds(instance)
    commands = raw_commands if isinstance(raw_commands, list) else [raw_commands]
    plan = _special_repo_execution_plan(instance, generated_patch, commands)
    test_cmd = _test_command(instance, generated_patch)
    lines = [
        "#!/bin/bash",
        "set -uxo pipefail",
        "if [ -f /opt/miniconda3/bin/activate ]; then "
        "source /opt/miniconda3/bin/activate && conda activate testbed; fi",
        f"cd {repo_dir}",
        f"git config --global --add safe.directory {repo_dir}",
        f"git reset --hard {base_commit}",
        "git clean -fdx",
    ]
    if "eval_commands" in specs:
        lines += specs["eval_commands"]
    if "install" in specs:
        lines.append(specs["install"])
    generated_apply = [
        f"git apply -v {GENERATED_TEST_PATCH} "
        f"|| git apply -v --3way {GENERATED_TEST_PATCH} "
        f"|| {{ echo {GEN_APPLY_FAIL}; exit 11; }}",
        f"echo {GEN_APPLY_PASS}",
    ]
    if apply_gold:
        lines += [
            f"test ! -s {GOLD_PATCH} || git apply -v {GOLD_PATCH} "
            f"|| git apply -v --3way {GOLD_PATCH} "
            f"|| {{ echo {GOLD_APPLY_FAIL}; exit 12; }}",
            f"echo {GOLD_APPLY_PASS}",
        ]
    lines += generated_apply
    build_commands = _patch_driven_build_commands(instance["repo"], specs, plan)
    lines += [
        f"{cmd} || {{ echo {BUILD_FAIL}; exit 13; }}" for cmd in build_commands
    ]
    lines += [
        f": '{START_TEST_OUTPUT}'",
        test_cmd,
        f": '{END_TEST_OUTPUT}'",
    ]
    return "\n".join(lines) + "\n"


def _run_script(container, script_text: str, log_dir: Path, name: str, timeout: int) -> tuple[str, bool]:
    script_path = log_dir / f"{name}.sh"
    script_path.write_text(script_text)
    copy_to_container(container, script_path, PurePosixPath(f"/{name}.sh"))
    output, timed_out, _runtime = exec_run_with_timeout(
        container,
        f"/bin/bash /{name}.sh",
        timeout,
    )
    (log_dir / f"{name}.log").write_text(output)
    return output, timed_out


def _parse_status(output: str, instance: dict) -> dict[str, str]:
    parser = MAP_REPO_TO_PARSER.get(instance["repo"])
    if parser is None:
        return {}
    parse_spec = make_test_spec({**instance, "FAIL_TO_PASS": [], "PASS_TO_PASS": []})
    if START_TEST_OUTPUT in output and END_TEST_OUTPUT in output:
        test_output = output.split(START_TEST_OUTPUT, 1)[1].split(END_TEST_OUTPUT, 1)[0]
        parsed = parser(test_output, parse_spec)
        if parsed:
            return parsed
    return parser(output, parse_spec)


def _prediction_map(predictions_path: str | Path) -> dict[str, dict]:
    rows = read_prediction_rows(predictions_path)
    return {row["instance_id"]: row for row in rows if row.get("instance_id")}


def _safe_model_dir(prediction: dict) -> str:
    return (prediction.get("model_name_or_path") or "unknown").replace("/", "__")


def _write_report_and_cleanup_instance_image(
    report_path: Path,
    report: dict,
    instance: dict,
    client: docker.DockerClient,
    clean_images: bool,
) -> None:
    """Persist the report before optionally reclaiming its instance image."""
    report_path.write_text(json.dumps(report, indent=2))
    if not clean_images:
        return

    instance_id = instance["instance_id"]
    try:
        image_name = make_test_spec(instance).instance_image_key
    except Exception as exc:
        logger.warning(
            "Report saved for %s, but its instance image could not be identified: %s",
            instance_id,
            exc,
        )
        return

    try:
        client.images.remove(image_name, force=True)
        logger.info(
            "Report saved for %s; removed instance image %s",
            instance_id,
            image_name,
        )
    except docker.errors.NotFound:
        logger.info(
            "Report saved for %s; instance image %s was already absent",
            instance_id,
            image_name,
        )
    except Exception as exc:
        # A cleanup failure must not discard or relabel a valid scientific result.
        logger.warning(
            "Report saved for %s, but instance image %s could not be removed: %s",
            instance_id,
            image_name,
            exc,
        )


def _evaluate_one(
    instance: dict,
    prediction: dict | None,
    run_id: str,
    client: docker.DockerClient,
    log_dir: str,
    timeout: int,
    clean_images: bool = False,
) -> dict:
    evaluation_started = time.perf_counter()
    instance_id = instance["instance_id"]
    model_dir = _safe_model_dir(prediction or {})
    out_dir = Path(log_dir) / run_id / model_dir / instance_id
    out_dir.mkdir(parents=True, exist_ok=True)
    inst_logger = setup_logger(instance_id, out_dir / "test_generation.log")
    report_path = out_dir / "report.json"

    if prediction is None or not (prediction.get("model_patch") or "").strip():
        report = {
            instance_id: {
                "status": "no-pred",
                "test_patch_applied": False,
                "gold_patch_applied": False,
                "base_failed_tests": [],
                "gold_passed_tests": [],
                "selected_test_languages": [],
                "selected_test_paths": [],
                "selected_test_commands": [],
                "inference_metrics": (prediction or {}).get("metrics", {}),
                "evaluation_wall_time_seconds": round(
                    time.perf_counter() - evaluation_started, 6
                ),
            }
        }
        _write_report_and_cleanup_instance_image(
            report_path, report, instance, client, clean_images
        )
        close_logger(inst_logger)
        return report[instance_id]

    generated_patch = prediction["model_patch"]
    generated_patch_bytes = len(generated_patch.encode())
    if generated_patch_bytes > MAX_GENERATED_TEST_PATCH_BYTES:
        report = {
            instance_id: {
                "status": "errored",
                "failure_reason": "prediction_patch_too_large",
                "error": (
                    f"generated patch is {generated_patch_bytes} bytes; maximum is "
                    f"{MAX_GENERATED_TEST_PATCH_BYTES}"
                ),
                "test_patch_applied": False,
                "gold_patch_applied": False,
                "base_failed_tests": [],
                "gold_passed_tests": [],
                "selected_test_languages": [],
                "selected_test_paths": [],
                "selected_test_commands": [],
                "inference_metrics": prediction.get("metrics", {}),
                "evaluation_wall_time_seconds": round(
                    time.perf_counter() - evaluation_started, 6
                ),
            }
        }
        _write_report_and_cleanup_instance_image(
            report_path, report, instance, client, clean_images
        )
        close_logger(inst_logger)
        return report[instance_id]

    container = None
    base_duration = None
    gold_duration = None
    evaluation_stage = "resolve_test_spec"
    selected_plan: GeneratedTestExecutionPlan | None = None
    try:
        spec = make_test_spec(instance)
        raw_commands = get_test_cmds(instance)
        commands = raw_commands if isinstance(raw_commands, list) else [raw_commands]
        selected_plan = _special_repo_execution_plan(
            instance, generated_patch, commands
        )
        evaluation_stage = "build_instance_image"
        stale_name = spec.get_instance_container_name(run_id)
        try:
            stale = client.containers.get(stale_name)
            stale.remove(force=True)
        except docker.errors.NotFound:
            pass

        container = build_container(
            spec,
            client,
            run_id,
            inst_logger,
            nocache=False,
            force_rebuild=False,
        )
        container.start()
        evaluation_stage = "execute_generated_tests"

        gen_patch_path = out_dir / "generated_test.patch"
        gold_patch_path = out_dir / "gold.patch"
        gen_patch_path.write_text(generated_patch)
        (
            effective_gold_patch,
            excluded_gold_test_paths,
            excluded_gold_binary_paths,
        ) = _prepare_gold_patch(instance.get("patch", "") or "")
        gold_patch_path.write_text(effective_gold_patch)
        copy_to_container(container, gen_patch_path, PurePosixPath(GENERATED_TEST_PATCH))
        copy_to_container(container, gold_patch_path, PurePosixPath(GOLD_PATCH))

        phase_started = time.perf_counter()
        base_output, base_timed_out = _run_script(
            container,
            _build_script(instance, generated_patch, apply_gold=False),
            out_dir,
            "base_generated_tests",
            timeout,
        )
        base_duration = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        gold_output, gold_timed_out = _run_script(
            container,
            _build_script(instance, generated_patch, apply_gold=True),
            out_dir,
            "gold_generated_tests",
            timeout,
        )
        gold_duration = time.perf_counter() - phase_started

        base_status = _parse_status(base_output, instance)
        gold_status = _parse_status(gold_output, instance)
        test_patch_applied = GEN_APPLY_PASS in base_output and GEN_APPLY_PASS in gold_output
        gold_patch_applied = GOLD_APPLY_PASS in gold_output
        classified = classify_test_generation_result(
            base_status,
            gold_status,
            test_patch_applied=test_patch_applied,
            gold_patch_applied=gold_patch_applied,
            base_timed_out=base_timed_out,
            gold_timed_out=gold_timed_out,
            test_execution_failed=_test_execution_failed(base_output)
            or _test_execution_failed(gold_output),
            no_tests_selected=_no_tests_selected(base_output) or _no_tests_selected(gold_output),
            collection_failed=_test_collection_failed(base_output)
            or _test_collection_failed(gold_output),
            non_evaluable=_non_evaluable_output(base_output) or _non_evaluable_output(gold_output),
            infrastructure_failed=_infrastructure_failure_output(base_output)
            or _infrastructure_failure_output(gold_output),
            base_build_failed=BUILD_FAIL in base_output,
            gold_build_failed=BUILD_FAIL in gold_output,
            unsupported_generated_test=(
                UNSUPPORTED_GENERATED_TEST in base_output
                or UNSUPPORTED_GENERATED_TEST in gold_output
            ),
        )
        report = {
            instance_id: {
                **classified,
                "test_patch_applied": test_patch_applied,
                "gold_patch_applied": gold_patch_applied,
                "base_status_count": len(base_status),
                "gold_status_count": len(gold_status),
                "base_timed_out": base_timed_out,
                "gold_timed_out": gold_timed_out,
                "excluded_gold_test_paths": excluded_gold_test_paths,
                "excluded_gold_binary_paths": excluded_gold_binary_paths,
                "selected_test_languages": list(
                    selected_plan.languages if selected_plan else ()
                ),
                "selected_test_paths": list(
                    selected_plan.paths if selected_plan else ()
                ),
                "selected_test_commands": list(
                    selected_plan.commands if selected_plan else ()
                ),
                "selected_test_evidence": (
                    selected_plan.evidence if selected_plan else {}
                ),
                "base_test_wall_time_seconds": round(base_duration, 6),
                "gold_test_wall_time_seconds": round(gold_duration, 6),
                "inference_metrics": prediction.get("metrics", {}),
            }
        }
    except Exception as e:
        inst_logger.exception("test-generation evaluation failed")
        failure_reason = (
            "invalid_test_spec"
            if evaluation_stage == "resolve_test_spec"
            else "evaluation_exception"
        )
        report = {
            instance_id: {
                "status": "errored",
                "failure_reason": failure_reason,
                "evaluation_stage": evaluation_stage,
                "error": f"{type(e).__name__}: {e}",
                "test_patch_applied": False,
                "gold_patch_applied": False,
                "base_failed_tests": [],
                "gold_passed_tests": [],
                "selected_test_languages": list(
                    selected_plan.languages if selected_plan else ()
                ),
                "selected_test_paths": list(
                    selected_plan.paths if selected_plan else ()
                ),
                "selected_test_commands": list(
                    selected_plan.commands if selected_plan else ()
                ),
                "base_test_wall_time_seconds": (
                    round(base_duration, 6) if base_duration is not None else None
                ),
                "gold_test_wall_time_seconds": (
                    round(gold_duration, 6) if gold_duration is not None else None
                ),
                "inference_metrics": prediction.get("metrics", {}),
            }
        }
    finally:
        cleanup_container(client, container, inst_logger)
        close_logger(inst_logger)

    report[instance_id]["evaluation_wall_time_seconds"] = round(
        time.perf_counter() - evaluation_started, 6
    )
    _write_report_and_cleanup_instance_image(
        report_path, report, instance, client, clean_images
    )
    return report[instance_id]


def run_test_generation_evaluation(
    instances: list[dict],
    predictions_path: str | Path,
    run_id: str,
    log_dir: str = "logs/run_evaluation",
    max_workers: int = 2,
    timeout: int = 1800,
    clean_images: bool = False,
) -> dict[str, dict]:
    """Run strict generated-test evaluation for selected instances."""
    predictions = _prediction_map(predictions_path)
    results: dict[str, dict] = {}
    client = docker.from_env()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _evaluate_one,
                    inst,
                    predictions.get(inst["instance_id"]),
                    run_id,
                    client,
                    log_dir,
                    timeout,
                    clean_images,
                ): inst
                for inst in instances
            }
            for fut in as_completed(futures):
                inst = futures[fut]
                results[inst["instance_id"]] = fut.result()
    finally:
        client.close()
    n_success = sum(1 for r in results.values() if r.get("status") == "resolved")
    logger.info(
        "Test-generation evaluation done: %s/%s generated tests succeeded",
        n_success,
        len(results),
    )
    return results
