"""Evaluate agent-generated regression tests.

This mode treats ``model_patch`` as a test patch. A success requires the patch
to apply, at least one generated/modified test to fail on the base code, and the
same failing test(s) to pass after the golden patch is applied.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import docker

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
) -> dict:
    """Classify strict SWT-Bench-style test-generation results."""
    if not test_patch_applied or had_runtime_error:
        status = "errored"
    elif not gold_patch_applied:
        status = "errored"
    elif not base_status_map or not gold_status_map:
        status = "errored"
    else:
        base_failed = sorted(t for t, s in base_status_map.items() if _failed(s))
        gold_passed = sorted(t for t in base_failed if _passed(gold_status_map.get(t)))
        status = (
            "resolved"
            if base_failed and len(gold_passed) == len(base_failed)
            else "unresolved"
        )
        return {
            "status": status,
            "base_failed_tests": base_failed,
            "gold_passed_tests": gold_passed,
        }
    return {
        "status": status,
        "base_failed_tests": [],
        "gold_passed_tests": [],
    }


def _test_command(instance: dict, generated_patch: str) -> str:
    """Choose the command that runs the generated test patch."""
    if isinstance(get_test_cmds(instance), list):
        commands = get_test_cmds(instance)
    else:
        commands = [get_test_cmds(instance)]

    raw = commands[0] if len(commands) == 1 else None
    if raw and isinstance(raw, str) and instance["repo"] not in {
        "openmm/openmm",
        "rdkit/rdkit",
    }:
        generated_instance = {**instance, "test_patch": generated_patch}
        directives = get_test_directives(generated_instance)
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
    lines += [
        f"git apply -v {GENERATED_TEST_PATCH} "
        f"|| git apply -v --3way {GENERATED_TEST_PATCH} "
        f"|| patch --batch --fuzz=5 -p1 -i {GENERATED_TEST_PATCH} "
        f"|| {{ echo {GEN_APPLY_FAIL}; exit 11; }}",
        f"echo {GEN_APPLY_PASS}",
    ]
    if apply_gold:
        lines += [
            f"git apply -v {GOLD_PATCH} "
            f"|| git apply -v --3way {GOLD_PATCH} "
            f"|| patch --batch --fuzz=5 -p1 -i {GOLD_PATCH} "
            f"|| {{ echo {GOLD_APPLY_FAIL}; exit 12; }}",
            f"echo {GOLD_APPLY_PASS}",
        ]
    if "build" in specs:
        lines += specs["build"]
    if "build_after_test_patch" in specs:
        lines += specs["build_after_test_patch"]
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
            }
        }
        report_path.write_text(json.dumps(report, indent=2))
        close_logger(inst_logger)
        return report[instance_id]

    generated_patch = prediction["model_patch"]
    container = None
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
        gold_patch_path.write_text(instance.get("patch", "") or "")
        copy_to_container(container, gen_patch_path, PurePosixPath(GENERATED_TEST_PATCH))
        copy_to_container(container, gold_patch_path, PurePosixPath(GOLD_PATCH))

        base_output, base_timed_out = _run_script(
            container,
            _build_script(instance, generated_patch, apply_gold=False),
            out_dir,
            "base_generated_tests",
            timeout,
        )
        gold_output, gold_timed_out = _run_script(
            container,
            _build_script(instance, generated_patch, apply_gold=True),
            out_dir,
            "gold_generated_tests",
            timeout,
        )

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
            }
        }
    except Exception as e:
        inst_logger.exception("test-generation evaluation failed")
        report = {
            instance_id: {
                "status": "errored",
                "error": f"{type(e).__name__}: {e}",
                "test_patch_applied": False,
                "gold_patch_applied": False,
                "base_failed_tests": [],
                "gold_passed_tests": [],
            }
        }
    finally:
        cleanup_container(client, container, inst_logger)
        close_logger(inst_logger)

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
