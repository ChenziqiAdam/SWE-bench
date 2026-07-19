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
from pathlib import Path, PurePosixPath

import docker

from swebench.eval_pipeline.instance_builder import _is_test_path
from swebench.eval_pipeline.prediction_utils import read_prediction_rows
from swebench.harness.constants import (
    END_TEST_OUTPUT,
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

GENERATED_TEST_PATCH = "/tmp/generated_test.patch"
GOLD_PATCH = "/tmp/gold.patch"
GEN_APPLY_PASS = "GENERATED_TEST_PATCH_APPLIED"
GEN_APPLY_FAIL = "GENERATED_TEST_PATCH_FAILED"
GOLD_APPLY_PASS = "GOLD_PATCH_APPLIED"
GOLD_APPLY_FAIL = "GOLD_PATCH_FAILED"
BUILD_FAIL = "GENERATED_TEST_BUILD_FAILED"


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
    no_tests_selected: bool = False,
    collection_failed: bool = False,
    non_evaluable: bool = False,
    build_failed: bool = False,
    base_build_failed: bool = False,
    gold_build_failed: bool = False,
) -> dict:
    """Classify strict SWT-Bench-style test-generation results."""
    failure_reason = ""
    if non_evaluable:
        status = "excluded"
        failure_reason = "non_evaluable_spec"
    elif not test_patch_applied or had_runtime_error:
        status = "errored"
        failure_reason = "test_patch_failed_or_timeout"
    elif not gold_patch_applied:
        status = "errored"
        failure_reason = "gold_patch_failed"
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
        status = "errored"
        failure_reason = "test_collection_failed"
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
    return "not evaluable:" in output


def _no_tests_selected(output: str) -> bool:
    return any(
        marker in output
        for marker in (
            " 0 selected",
            "collected 0 items",
            "has no curated generated-test target",
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


def _openmm_generated_pytest_command(
    pytest_targets: list[str],
    pytest_filter: str | None = None,
) -> str:
    setup = (
        "python -m pip install --no-cache-dir openmm numpy scipy pytest && "
        "OPENMM_SITE=$(python -c 'import openmm, os; print(os.path.dirname(openmm.__file__))') && "
        "SIMTK_SITE=$(python -c 'import simtk.openmm, os; print(os.path.dirname(simtk.openmm.__file__))' 2>/dev/null || "
        "python -c 'import site; print(site.getsitepackages()[0] + \"/simtk/openmm\")') && "
        "mkdir -p \"$SIMTK_SITE\" && "
        "if [ ! -f \"$(dirname \"$SIMTK_SITE\")/__init__.py\" ]; then echo '' > \"$(dirname \"$SIMTK_SITE\")/__init__.py\"; fi && "
        "if [ ! -f \"$SIMTK_SITE/__init__.py\" ]; then echo 'from openmm import *' > \"$SIMTK_SITE/__init__.py\"; fi && "
        # Keep pip's complete top-level packages (compiled extension, version
        # module, and simtk compatibility shim).  Old source trees frequently
        # lack generated version.py; copying their __init__.py over the wheel
        # creates a circular/partially-initialized import during collection.
        "if [ -d /testbed/wrappers/python/openmm/app ]; then cp -r /testbed/wrappers/python/openmm/app \"$OPENMM_SITE/\"; fi && "
        "rm -rf \"$SIMTK_SITE/app\" && "
        "if [ -d /testbed/wrappers/python/openmm/app ]; then "
        "cp -r /testbed/wrappers/python/openmm/app \"$SIMTK_SITE/\"; "
        "elif [ -d /testbed/wrappers/python/simtk/openmm/app ]; then "
        "cp -r /testbed/wrappers/python/simtk/openmm/app \"$SIMTK_SITE/\"; "
        "python -m lib2to3 -w -n \"$SIMTK_SITE/app\" >/dev/null 2>&1 || true; "
        "fi && "
        "if [ -d \"$OPENMM_SITE/app/internal\" ] && [ -d \"$SIMTK_SITE/app/internal\" ]; then "
        "cp -n \"$OPENMM_SITE\"/app/internal/compiled* \"$SIMTK_SITE/app/internal/\" 2>/dev/null || true; "
        "fi && "
        "for name in vec3 unit; do "
        "if [ -e \"$OPENMM_SITE/$name.py\" ]; then cp \"$OPENMM_SITE/$name.py\" \"$SIMTK_SITE/\"; fi; "
        "if [ -d \"$OPENMM_SITE/$name\" ]; then cp -r \"$OPENMM_SITE/$name\" \"$SIMTK_SITE/\"; fi; "
        "done; "
        "if [ ! -e \"$SIMTK_SITE/vec3.py\" ]; then echo 'from openmm.vec3 import *' > \"$SIMTK_SITE/vec3.py\"; fi && "
        "if [ ! -e \"$SIMTK_SITE/unit.py\" ] && [ ! -d \"$SIMTK_SITE/unit\" ]; then echo 'from openmm.unit import *' > \"$SIMTK_SITE/unit.py\"; fi && "
        "python -c 'import openmm, simtk.openmm' && "
        "export PYTHONPATH=\"$SIMTK_SITE/app:${PYTHONPATH:-}\""
    )
    command = (
        setup
        + " && cd wrappers/python/tests && python -m pytest -xvs "
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
    for raw in generated_patch.splitlines():
        diff_match = re.match(r"^diff --git a/(\S+) b/\S+", raw)
        if diff_match:
            current_file = diff_match.group(1)
            current_class = None
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
            current_class = hunk_match.group(1) or current_class
            continue
        content = raw[1:] if raw.startswith(("+", " ")) else raw
        class_match = re.match(r"^\s*class\s+([A-Za-z_]\w*)\b", content)
        if class_match:
            current_class = class_match.group(1)
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        test_match = re.match(r"^(\s*)def\s+(test_[A-Za-z_]\w*)\s*\(", content)
        if not test_match:
            continue
        file_name = current_file[len(prefix):]
        test_name = test_match.group(2)
        if not test_match.group(1):
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


def _test_command(instance: dict, generated_patch: str) -> str:
    """Choose the command that runs the generated test patch."""
    if isinstance(get_test_cmds(instance), list):
        commands = get_test_cmds(instance)
    else:
        commands = [get_test_cmds(instance)]

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
    if (
        instance["repo"] == "openmm/openmm"
        and not specs.get("test_generation_use_spec_cmd")
    ):
        pytest_targets, pytest_filter = _openmm_generated_pytest_targets(generated_patch)
        if pytest_targets:
            return _openmm_generated_pytest_command(pytest_targets, pytest_filter)
        if specs.get("test_generation_requires_generated_pytest"):
            version = instance.get("version", "unknown")
            return (
                f"echo 'openmm#{version} has no curated generated pytest target' "
                "&& false"
            )

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


def _build_script(instance: dict, generated_patch: str, apply_gold: bool) -> str:
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    repo_dir = "/testbed"
    base_commit = instance["base_commit"]
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
    if "build" in specs:
        lines += [f"{cmd} || {{ echo {BUILD_FAIL}; exit 13; }}" for cmd in specs["build"]]
    if "build_after_test_patch" in specs:
        lines += [
            f"{cmd} || {{ echo {BUILD_FAIL}; exit 13; }}"
            for cmd in specs["build_after_test_patch"]
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


def _evaluate_one(
    instance: dict,
    prediction: dict | None,
    run_id: str,
    client: docker.DockerClient,
    log_dir: str,
    timeout: int,
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
                "inference_metrics": (prediction or {}).get("metrics", {}),
                "evaluation_wall_time_seconds": round(
                    time.perf_counter() - evaluation_started, 6
                ),
            }
        }
        report_path.write_text(json.dumps(report, indent=2))
        close_logger(inst_logger)
        return report[instance_id]

    generated_patch = prediction["model_patch"]
    container = None
    base_duration = None
    gold_duration = None
    try:
        spec = make_test_spec(instance)
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

        gen_patch_path = out_dir / "generated_test.patch"
        gold_patch_path = out_dir / "gold.patch"
        gen_patch_path.write_text(generated_patch)
        effective_gold_patch, excluded_gold_test_paths = (
            _exclude_gold_test_files(instance.get("patch", "") or "")
        )
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
            had_runtime_error=base_timed_out or gold_timed_out,
            no_tests_selected=_no_tests_selected(base_output) or _no_tests_selected(gold_output),
            collection_failed=_test_collection_failed(base_output)
            or _test_collection_failed(gold_output),
            non_evaluable=_non_evaluable_output(base_output) or _non_evaluable_output(gold_output),
            base_build_failed=BUILD_FAIL in base_output,
            gold_build_failed=BUILD_FAIL in gold_output,
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
                "base_test_wall_time_seconds": round(base_duration, 6),
                "gold_test_wall_time_seconds": round(gold_duration, 6),
                "inference_metrics": prediction.get("metrics", {}),
            }
        }
    except Exception as e:
        inst_logger.exception("test-generation evaluation failed")
        report = {
            instance_id: {
                "status": "errored",
                "failure_reason": "evaluation_exception",
                "error": f"{type(e).__name__}: {e}",
                "test_patch_applied": False,
                "gold_patch_applied": False,
                "base_failed_tests": [],
                "gold_passed_tests": [],
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
    report_path.write_text(json.dumps(report, indent=2))
    return report[instance_id]


def run_test_generation_evaluation(
    instances: list[dict],
    predictions_path: str | Path,
    run_id: str,
    log_dir: str = "logs/run_evaluation",
    max_workers: int = 2,
    timeout: int = 1800,
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
