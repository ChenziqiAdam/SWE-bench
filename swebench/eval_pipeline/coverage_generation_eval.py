"""Independently evaluate test patches for coverage and mutation improvement."""
from __future__ import annotations

import json
import logging
import re
import shlex
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import docker

from swebench.eval_pipeline.prediction_utils import read_prediction_rows
from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
from swebench.harness.docker_build import build_container, close_logger, setup_logger
from swebench.harness.docker_utils import cleanup_container, copy_to_container, exec_run_with_timeout
from swebench.harness.test_spec.test_spec import make_test_spec

logger = logging.getLogger(__name__)

GENERATED_TEST_PATCH = "/tmp/generated_test.patch"
PATCH_APPLIED = "COVERAGE_TEST_PATCH_APPLIED"
PATCH_FAILED = "COVERAGE_TEST_PATCH_FAILED"
_COVERAGE_START = "COVERAGE_JSON_START"
_COVERAGE_END = "COVERAGE_JSON_END"
_MUTATION_START = "MUTATION_RESULTS_START"
_MUTATION_END = "MUTATION_RESULTS_END"
_MUTATION_UNSUPPORTED = "MUTATION_UNSUPPORTED_PYTHON"

_TEST_CONFIG_NAMES = {
    "conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "setup.py",
    "tox.ini", "noxfile.py",
}


def infer_coverage_targets(instance: dict) -> list[str]:
    """Return explicit targets, or Python implementation files captured at ingest."""
    explicit = instance.get("coverage_targets") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    if explicit:
        return sorted({str(path).lstrip("./") for path in explicit if str(path).strip()})
    return sorted(
        path.lstrip("./")
        for path in (instance.get("file_contents") or {})
        if path.endswith(".py") and not _is_test_path(path)
    )


def _diff_paths(patch: str) -> list[tuple[str, str]]:
    return sorted(set(re.findall(r"^diff --git a/(.+?) b/(.+)$", patch, re.MULTILINE)))


def _is_test_path(path: str) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    parts = [part for part in path.split("/") if part]
    if not parts or path == "/dev/null":
        return False
    name = parts[-1].lower()
    if name in _TEST_CONFIG_NAMES:
        return False
    return (
        any(part.lower() in {"test", "tests"} for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _count_assertion_evidence(patch: str) -> int:
    """Count added assertion/expected-exception lines, including scientific helpers."""
    pattern = re.compile(
        r"^\+(?!\+\+)\s*(?:"
        r"assert\b|"
        r"(?:with\s+)?(?:[A-Za-z_]\w*\.)*"
        r"(?:assert(?:_[A-Za-z_]\w*|[A-Z]\w*)|raises|warns)\s*\("
        r")",
        re.MULTILINE,
    )
    return len(pattern.findall(patch))


def inspect_test_patch(patch: str) -> dict:
    pairs = _diff_paths(patch)
    paths = sorted({path for pair in pairs for path in pair if path != "/dev/null"})
    illegal = [path for path in paths if not _is_test_path(path)]
    added_tests = len(re.findall(r"^\+\s*(?:async\s+)?def\s+test[_A-Za-z0-9]*\s*\(", patch, re.MULTILINE))
    added_assertions = _count_assertion_evidence(patch)
    removed_test_lines = sum(
        1
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return {
        "changed_files": paths,
        "illegal_changed_files": illegal,
        "tests_only_patch": bool(paths) and not illegal,
        "added_test_count": added_tests,
        "added_assertion_count": added_assertions,
        "added_assertion_evidence_count": added_assertions,
        "removed_test_line_count": removed_test_lines,
        "no_existing_test_lines_removed": removed_test_lines == 0,
        # Compatibility alias. This is only a static deletion check, not proof
        # that fixtures, hooks, or other existing behavior are unchanged.
        "preserves_existing_test_behavior": removed_test_lines == 0,
    }


def parse_coverage_json(payload: str, targets: list[str]) -> dict | None:
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    files = data.get("files") or {}
    matched = []
    normalized_targets = [target.replace("\\", "/").lstrip("./") for target in targets]
    for path, info in files.items():
        normalized = path.replace("\\", "/").lstrip("./")
        if any(normalized == target or normalized.endswith("/" + target) for target in normalized_targets):
            matched.append(info.get("summary") or {})
    if not matched:
        return None
    statements = sum(int(item.get("num_statements", 0)) for item in matched)
    covered_lines = sum(int(item.get("covered_lines", 0)) for item in matched)
    branches = sum(int(item.get("num_branches", 0)) for item in matched)
    covered_branches = sum(int(item.get("covered_branches", 0)) for item in matched)
    return {
        "target_file_count": len(matched),
        "line_coverage": 100.0 * covered_lines / statements if statements else 100.0,
        "branch_coverage": 100.0 * covered_branches / branches if branches else 100.0,
        "covered_lines": covered_lines,
        "num_statements": statements,
        "covered_branches": covered_branches,
        "num_branches": branches,
    }


def parse_mutation_results(text: str) -> dict | None:
    """Parse common mutmut 2/3 textual summaries."""
    counts: dict[str, int] = {}
    aliases = {
        "killed": "killed", "survived": "survived", "timeout": "timeout",
        "suspicious": "suspicious", "skipped": "skipped",
    }
    for label, value in re.findall(
        r"(?im)\b(killed|survived|timeout|suspicious|skipped)\b\s*[:=]?\s*(\d+)", text
    ):
        counts[aliases[label.lower()]] = max(counts.get(aliases[label.lower()], 0), int(value))
    for symbol, key in {
        "🎉": "killed", "⏰": "timeout", "🤔": "suspicious",
        "🙁": "survived", "🔇": "skipped",
    }.items():
        values = [int(value) for value in re.findall(re.escape(symbol) + r"\s*(\d+)", text)]
        if values:
            counts[key] = max(counts.get(key, 0), max(values))
    killed = counts.get("killed", 0)
    timeout = counts.get("timeout", 0)
    survived = counts.get("survived", 0)
    suspicious = counts.get("suspicious", 0)
    total = killed + timeout + survived + suspicious
    if not total:
        match = re.search(r"(?i)killed\s+(\d+)\s+out of\s+(\d+)\s+mutants", text)
        if not match:
            return None
        killed, total = map(int, match.groups())
        survived = total - killed
    killed_only_score = 100.0 * killed / total if total else None
    killed_or_timeout_score = 100.0 * (killed + timeout) / total if total else None
    return {
        **counts,
        "killed": killed,
        "survived": survived,
        "total": total,
        # Conservative primary metric: a timeout is not evidence that a test
        # detected the mutant. Skipped mutants are excluded from the denominator.
        "score": killed_only_score,
        "score_killed_only": killed_only_score,
        "score_killed_or_timeout": killed_or_timeout_score,
        "score_definition": "100 * killed / (killed + timeout + survived + suspicious)",
    }


def mutation_exit_is_fatal(exit_code: int | None) -> bool:
    """Mutmut 2 uses bit 0 for internal/tool errors; other bits are outcomes."""
    return exit_code is None or bool(exit_code & 1)


def _is_flaky(main_exit: int | None, repeat_exits: list[int | None]) -> bool:
    return main_exit is not None and any(code is None or code != main_exit for code in repeat_exits)


def _extract_block(output: str, start: str, end: str) -> str:
    if start not in output or end not in output:
        return ""
    return output.split(start, 1)[1].split(end, 1)[0].strip()


def _phase_script(instance: dict, apply_patch: bool, flaky_runs: int) -> str:
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    pytest_command = instance.get("coverage_test_command") or "python -m pytest"
    coverage_command = instance.get("coverage_command") or "python -m coverage run --branch -m pytest"
    targets = infer_coverage_targets(instance)
    default_mutation = "mutmut run --paths-to-mutate=" + shlex.quote(",".join(targets))
    mutation_command = instance.get("mutation_command") or default_mutation
    mutation_results_command = instance.get("mutation_results_command") or "mutmut results"
    lines = [
        "#!/bin/bash", "set -uxo pipefail",
        "if [ -f /opt/miniconda3/bin/activate ]; then source /opt/miniconda3/bin/activate && conda activate testbed; fi",
        "cd /testbed", "git config --global --add safe.directory /testbed",
        f"git reset --hard {shlex.quote(instance['base_commit'])}", "git clean -fdx",
    ]
    if "eval_commands" in specs:
        lines += specs["eval_commands"]
    if "install" in specs:
        lines.append(specs["install"])
    tool_install = instance.get("coverage_tool_install_command")
    if tool_install:
        lines.append(tool_install)
    else:
        lines += [
            "if python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 7) else 1)'; then",
            "  python -m pip install --disable-pip-version-check coverage 'mutmut<3'",
            "elif python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 6) else 1)'; then",
            "  python -m pip install --disable-pip-version-check 'coverage<6' 'mutmut<2'",
            "else",
            "  python -m pip install --disable-pip-version-check 'coverage<6'",
            *([] if instance.get("mutation_command") else [
                f"  {_MUTATION_UNSUPPORTED}=1",
                f"  echo {_MUTATION_UNSUPPORTED}=1",
            ]),
            "fi",
        ]
    if apply_patch:
        lines += [
            f"git apply -v {GENERATED_TEST_PATCH} || git apply -v --3way {GENERATED_TEST_PATCH} || patch --batch --fuzz=5 -p1 -i {GENERATED_TEST_PATCH} || {{ echo {PATCH_FAILED}; exit 11; }}",
            f"echo {PATCH_APPLIED}",
        ]
    if "build" in specs:
        lines += specs["build"]
    if apply_patch and "build_after_test_patch" in specs:
        lines += specs["build_after_test_patch"]
    lines += [
        pytest_command,
        "PYTEST_EXIT=$?",
        "python -m coverage erase",
        coverage_command,
        "COVERAGE_TEST_EXIT=$?",
        "python -m coverage json -o /tmp/coverage.json",
        f"echo {_COVERAGE_START}; cat /tmp/coverage.json 2>/dev/null || true; echo {_COVERAGE_END}",
    ]
    for index in range(flaky_runs):
        lines += [f"{pytest_command}", f"echo REPEAT_RUN_{index + 1}_EXIT=$?"]
    lines += [
        f"echo {_MUTATION_START}",
        f"if [ \"${{{_MUTATION_UNSUPPORTED}:-0}}\" = 1 ]; then",
        "  MUTATION_EXIT=125",
        "else",
        f"  {mutation_command}", "  MUTATION_EXIT=$?",
        f"  {mutation_results_command} 2>&1 || true", "fi", f"echo {_MUTATION_END}",
        "echo PYTEST_EXIT=$PYTEST_EXIT", "echo COVERAGE_TEST_EXIT=$COVERAGE_TEST_EXIT",
        "echo MUTATION_EXIT=$MUTATION_EXIT", "exit 0",
    ]
    return "\n".join(lines) + "\n"


def _run_script(container, script: str, out_dir: Path, name: str, timeout: int) -> tuple[str, bool, float]:
    path = out_dir / f"{name}.sh"
    path.write_text(script)
    copy_to_container(container, path, PurePosixPath(f"/{name}.sh"))
    output, timed_out, runtime = exec_run_with_timeout(container, f"/bin/bash /{name}.sh", timeout)
    (out_dir / f"{name}.log").write_text(output)
    return output, timed_out, runtime


def _exit_code(output: str, name: str) -> int | None:
    matches = re.findall(rf"(?m)^{re.escape(name)}=(\d+)\s*$", output)
    return int(matches[-1]) if matches else None


def classify_coverage_result(before: dict | None, after: dict | None, patch_info: dict,
                             before_test_exit: int | None, after_test_exit: int | None,
                             patch_applied: bool, timed_out: bool,
                             coverage_test_failed: bool = False,
                             mutation_before: dict | None = None,
                             mutation_after: dict | None = None,
                             baseline_flaky: bool = False,
                             generated_tests_flaky: bool = False) -> tuple[str, str]:
    if timed_out:
        return "errored", "evaluation_timeout"
    if not patch_applied:
        return "errored", "test_patch_failed"
    if not patch_info["tests_only_patch"]:
        return "invalid", "production_or_non_test_files_modified"
    if not patch_info.get(
        "no_existing_test_lines_removed",
        patch_info.get("preserves_existing_test_behavior", True),
    ):
        return "invalid", "existing_test_lines_removed"
    if before_test_exit != 0:
        return "excluded", "base_tests_failed"
    if baseline_flaky:
        return "excluded", "baseline_test_suite_flaky"
    if after_test_exit != 0:
        return "unresolved", "tests_failed_after_patch"
    if generated_tests_flaky:
        return "unresolved", "flaky_generated_tests"
    if coverage_test_failed:
        return "errored", "coverage_test_run_failed"
    if patch_info.get("added_assertion_count", 0) == 0:
        return "invalid", "no_added_assertions"
    if before is None or after is None:
        return "errored", "coverage_unavailable_for_target"
    mutation_improved = (
        mutation_before is not None
        and mutation_after is not None
        and mutation_after.get("score") is not None
        and mutation_before.get("score") is not None
        and mutation_after["score"] > mutation_before["score"]
    )
    if (
        after["line_coverage"] > before["line_coverage"]
        or after["branch_coverage"] > before["branch_coverage"]
        or mutation_improved
    ):
        return "resolved", ""
    return "unresolved", "no_coverage_or_mutation_improvement"


def _evaluate_one(instance: dict, prediction: dict | None, run_id: str, client,
                  log_dir: str, timeout: int, flaky_runs: int) -> dict:
    started = time.perf_counter()
    iid = instance["instance_id"]
    model_dir = ((prediction or {}).get("model_name_or_path") or "unknown").replace("/", "__")
    out_dir = Path(log_dir) / run_id / model_dir / iid
    out_dir.mkdir(parents=True, exist_ok=True)
    inst_logger = setup_logger(iid, out_dir / "coverage_generation.log")
    report_path = out_dir / "report.json"
    patch = (prediction or {}).get("model_patch") or ""
    patch_info = inspect_test_patch(patch)
    targets = infer_coverage_targets(instance)
    if not patch.strip() or not targets:
        result = {
            "status": "no-pred" if not patch.strip() else "excluded",
            "failure_reason": "" if not patch.strip() else "no_coverage_targets",
            **patch_info, "coverage_targets": targets,
            "inference_metrics": (prediction or {}).get("metrics", {}),
            "evaluation_wall_time_seconds": round(time.perf_counter() - started, 6),
        }
        report_path.write_text(json.dumps({iid: result}, indent=2))
        close_logger(inst_logger)
        return result
    container = None
    try:
        spec = make_test_spec(instance)
        try:
            client.containers.get(spec.get_instance_container_name(run_id)).remove(force=True)
        except docker.errors.NotFound:
            pass
        container = build_container(spec, client, run_id, inst_logger, nocache=False, force_rebuild=False)
        container.start()
        patch_path = out_dir / "generated_test.patch"
        patch_path.write_text(patch)
        copy_to_container(container, patch_path, PurePosixPath(GENERATED_TEST_PATCH))
        before_output, before_timeout, before_runtime = _run_script(
            container, _phase_script(instance, False, flaky_runs), out_dir, "before", timeout
        )
        after_output, after_timeout, after_runtime = _run_script(
            container, _phase_script(instance, True, flaky_runs), out_dir, "after", timeout
        )
        before_cov = parse_coverage_json(_extract_block(before_output, _COVERAGE_START, _COVERAGE_END), targets)
        after_cov = parse_coverage_json(_extract_block(after_output, _COVERAGE_START, _COVERAGE_END), targets)
        before_mut = parse_mutation_results(_extract_block(before_output, _MUTATION_START, _MUTATION_END))
        after_mut = parse_mutation_results(_extract_block(after_output, _MUTATION_START, _MUTATION_END))
        before_exit = _exit_code(before_output, "PYTEST_EXIT")
        after_exit = _exit_code(after_output, "PYTEST_EXIT")
        before_coverage_exit = _exit_code(before_output, "COVERAGE_TEST_EXIT")
        after_coverage_exit = _exit_code(after_output, "COVERAGE_TEST_EXIT")
        before_mutation_exit = _exit_code(before_output, "MUTATION_EXIT")
        after_mutation_exit = _exit_code(after_output, "MUTATION_EXIT")
        baseline_repeat_exits = [
            _exit_code(before_output, f"REPEAT_RUN_{i + 1}_EXIT") for i in range(flaky_runs)
        ]
        after_repeat_exits = [
            _exit_code(after_output, f"REPEAT_RUN_{i + 1}_EXIT") for i in range(flaky_runs)
        ]
        baseline_flaky = _is_flaky(before_exit, baseline_repeat_exits)
        generated_tests_flaky = _is_flaky(after_exit, after_repeat_exits)
        usable_before_mut = None if mutation_exit_is_fatal(before_mutation_exit) else before_mut
        usable_after_mut = None if mutation_exit_is_fatal(after_mutation_exit) else after_mut
        status, reason = classify_coverage_result(
            before_cov, after_cov, patch_info, before_exit, after_exit,
            PATCH_APPLIED in after_output, before_timeout or after_timeout,
            coverage_test_failed=(before_coverage_exit != 0 or after_coverage_exit != 0),
            mutation_before=usable_before_mut,
            mutation_after=usable_after_mut,
            baseline_flaky=baseline_flaky,
            generated_tests_flaky=generated_tests_flaky,
        )
        result = {
            "status": status, "failure_reason": reason, **patch_info,
            "coverage_targets": targets, "test_patch_applied": PATCH_APPLIED in after_output,
            "base_tests_passed": before_exit == 0, "after_tests_passed": after_exit == 0,
            "base_coverage_tests_passed": before_coverage_exit == 0,
            "after_coverage_tests_passed": after_coverage_exit == 0,
            "baseline_flaky": baseline_flaky,
            "generated_tests_flaky": generated_tests_flaky,
            "flaky": baseline_flaky or generated_tests_flaky,
            "baseline_repeat_exit_codes": baseline_repeat_exits,
            "after_repeat_exit_codes": after_repeat_exits,
            "flaky_run_exit_codes": after_repeat_exits,
            "coverage_before": before_cov, "coverage_after": after_cov,
            "coverage_line_delta": (after_cov["line_coverage"] - before_cov["line_coverage"]) if before_cov and after_cov else None,
            "coverage_branch_delta": (after_cov["branch_coverage"] - before_cov["branch_coverage"]) if before_cov and after_cov else None,
            "mutation_before": before_mut, "mutation_after": after_mut,
            "mutation_before_exit_code": before_mutation_exit,
            "mutation_after_exit_code": after_mutation_exit,
            "mutation_before_tool_error": mutation_exit_is_fatal(before_mutation_exit),
            "mutation_after_tool_error": mutation_exit_is_fatal(after_mutation_exit),
            "mutation_unsupported_python": (
                f"{_MUTATION_UNSUPPORTED}=1" in before_output
                or f"{_MUTATION_UNSUPPORTED}=1" in after_output
            ),
            "mutation_score_delta": (
                usable_after_mut["score"] - usable_before_mut["score"]
                if usable_before_mut and usable_after_mut else None
            ),
            "before_wall_time_seconds": round(before_runtime, 6),
            "after_wall_time_seconds": round(after_runtime, 6),
            "inference_metrics": (prediction or {}).get("metrics", {}),
        }
    except Exception as exc:
        inst_logger.exception("coverage-generation evaluation failed")
        result = {"status": "errored", "failure_reason": "evaluation_exception",
                  "error": f"{type(exc).__name__}: {exc}", **patch_info,
                  "coverage_targets": targets, "inference_metrics": (prediction or {}).get("metrics", {})}
    finally:
        cleanup_container(client, container, inst_logger)
        close_logger(inst_logger)
    result["evaluation_wall_time_seconds"] = round(time.perf_counter() - started, 6)
    report_path.write_text(json.dumps({iid: result}, indent=2))
    return result


def run_coverage_generation_evaluation(instances: list[dict], predictions_path: str | Path,
                                       run_id: str, log_dir: str = "logs/run_evaluation",
                                       max_workers: int = 2, timeout: int = 3600,
                                       flaky_runs: int = 2) -> dict[str, dict]:
    predictions = {row["instance_id"]: row for row in read_prediction_rows(predictions_path) if row.get("instance_id")}
    results: dict[str, dict] = {}
    client = docker.from_env()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_evaluate_one, inst, predictions.get(inst["instance_id"]), run_id,
                            client, log_dir, timeout, flaky_runs): inst
                for inst in instances
            }
            for future in as_completed(futures):
                inst = futures[future]
                results[inst["instance_id"]] = future.result()
                logger.info("Coverage-generation evaluated %s (%s/%s)", inst["instance_id"], len(results), len(futures))
    finally:
        client.close()
    return results
