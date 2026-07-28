"""Independently evaluate test patches for coverage and mutation improvement."""
from __future__ import annotations

import json
import logging
import re
import shutil
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import docker

from swebench.eval_pipeline.host_environment import isolated_python_environment
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
_MUTATION_SKIPPED = "MUTATION_SKIPPED_NO_SELECTED_MODULES"
_MUTMUT_COMPATIBILITY_DIR = ".coverage-generation-mutmut-compatibility"

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
    if not isinstance(payload, str):
        return None
    data = None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", payload):
        try:
            candidate, _end = decoder.raw_decode(payload[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "files" in candidate:
            data = candidate
            break
    if data is None:
        return None
    files = data.get("files") or {}
    matched: list[tuple[str, dict]] = []
    normalized_targets = [target.replace("\\", "/").lstrip("./") for target in targets]
    for path, info in files.items():
        normalized = path.replace("\\", "/").lstrip("./")
        selected = (
            any(
                normalized == target or normalized.endswith("/" + target)
                for target in normalized_targets
            )
            if normalized_targets
            else normalized.endswith(".py")
            and not _is_test_path(normalized)
            and normalized.rsplit("/", 1)[-1].lower() not in _TEST_CONFIG_NAMES
            and not any(
                part.lower() in {
                    ".git", ".tox", ".venv", "build", "dist", "site-packages",
                    "venv", "__pycache__",
                }
                for part in normalized.split("/")[:-1]
            )
        )
        if selected:
            matched.append((normalized, info.get("summary") or {}))
    if not matched:
        return None
    statements = sum(int(item.get("num_statements", 0)) for _, item in matched)
    covered_lines = sum(int(item.get("covered_lines", 0)) for _, item in matched)
    branches = sum(int(item.get("num_branches", 0)) for _, item in matched)
    covered_branches = sum(int(item.get("covered_branches", 0)) for _, item in matched)
    file_summaries = {
        path: {
            "line_coverage": (
                100.0 * int(summary.get("covered_lines", 0))
                / int(summary.get("num_statements", 0))
                if int(summary.get("num_statements", 0)) else 100.0
            ),
            "branch_coverage": (
                100.0 * int(summary.get("covered_branches", 0))
                / int(summary.get("num_branches", 0))
                if int(summary.get("num_branches", 0)) else 100.0
            ),
            **{
                key: int(summary.get(key, 0))
                for key in (
                    "covered_lines", "num_statements", "covered_branches", "num_branches"
                )
            },
        }
        for path, summary in matched
    }
    return {
        "target_file_count": len(matched),
        "scope": "targeted" if normalized_targets else "repository",
        "line_coverage": 100.0 * covered_lines / statements if statements else 100.0,
        "branch_coverage": 100.0 * covered_branches / branches if branches else 100.0,
        "covered_lines": covered_lines,
        "num_statements": statements,
        "covered_branches": covered_branches,
        "num_branches": branches,
        "files": file_summaries,
    }


def format_baseline_coverage_report(coverage: dict | None, max_files: int = 200) -> str:
    """Format a compact, poorest-first repository coverage report for the agent."""
    if not coverage:
        return "Coverage report unavailable. Run coverage yourself before editing tests."
    files = coverage.get("files") or {}
    ranked = sorted(
        files.items(),
        key=lambda item: (
            item[1].get("line_coverage", 100.0),
            item[1].get("branch_coverage", 100.0),
            item[0],
        ),
    )
    lines = [
        f"Repository totals: line {coverage['line_coverage']:.2f}%, "
        f"branch {coverage['branch_coverage']:.2f}%, {len(files)} source files.",
        "Per-file coverage (poorest first):",
    ]
    for path, summary in ranked[:max_files]:
        lines.append(
            f"- {path}: line {summary['line_coverage']:.2f}% "
            f"({summary['covered_lines']}/{summary['num_statements']}), "
            f"branch {summary['branch_coverage']:.2f}% "
            f"({summary['covered_branches']}/{summary['num_branches']})"
        )
    if len(ranked) > max_files:
        lines.append(f"- ... {len(ranked) - max_files} additional files omitted")
    return "\n".join(lines)


def select_mutation_targets(
    before: dict | None, after: dict | None, explicit_targets: list[str] | None = None
) -> list[str]:
    """Select explicit modules or modules whose coverage increased after the patch."""
    if explicit_targets:
        return sorted(set(explicit_targets))
    before_files = (before or {}).get("files") or {}
    after_files = (after or {}).get("files") or {}
    return sorted(
        path
        for path, post in after_files.items()
        if path in before_files
        and (
            post.get("covered_lines", 0) > before_files[path].get("covered_lines", 0)
            or post.get("covered_branches", 0)
            > before_files[path].get("covered_branches", 0)
        )
    )


def exclude_mutation_targets(
    targets: list[str], excluded_targets: list[str] | None
) -> tuple[list[str], list[str]]:
    """Apply an explicit tool-compatibility exclusion to a mutation target set."""
    excluded = set(excluded_targets or [])
    applied = sorted(set(targets) & excluded)
    return sorted(set(targets) - excluded), applied


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


def parse_mutation_progress(text: str) -> dict | None:
    """Return transparent partial mutmut progress without treating it as a score."""
    matches = re.findall(
        r"(\d+)/(\d+)\s+🎉\s*(\d+)\s+⏰\s*(\d+)\s+"
        r"🤔\s*(\d+)\s+🙁\s*(\d+)\s+🔇\s*(\d+)",
        text,
    )
    if not matches:
        return None
    processed, expected, killed, timeout, suspicious, survived, skipped = map(
        int, matches[-1]
    )
    return {
        "processed": processed,
        "expected": expected,
        "killed": killed,
        "timeout": timeout,
        "suspicious": suspicious,
        "survived": survived,
        "skipped": skipped,
    }


def mutation_exit_is_fatal(exit_code: int | None) -> bool:
    """Mutmut 2 uses bit 0 for internal/tool errors; other bits are outcomes."""
    return exit_code is None or bool(exit_code & 1)


def _mutmut_sqlite_compatibility_lines() -> list[str]:
    """Make mutmut 2's Pony/SQLite cache wait for short parent/worker locks."""
    sitecustomize = """from pony.orm import Database

_original_bind = Database.bind

def _coverage_generation_bind(self, *args, **kwargs):
    provider = kwargs.get("provider") or (args[0] if args else None)
    if provider == "sqlite":
        kwargs.setdefault("timeout", 60.0)
    return _original_bind(self, *args, **kwargs)

Database.bind = _coverage_generation_bind
"""
    return [
        f"mkdir -p {_MUTMUT_COMPATIBILITY_DIR}",
        (
            f"printf %s {shlex.quote(sitecustomize)} > "
            f"{_MUTMUT_COMPATIBILITY_DIR}/sitecustomize.py"
        ),
    ]


def _with_mutmut_compatibility(command: str) -> str:
    return (
        f'PYTHONPATH="$PWD/{_MUTMUT_COMPATIBILITY_DIR}'
        '${PYTHONPATH:+:$PYTHONPATH}" '
        f"{command}"
    )


def _coverage_phase_timeout(instance: dict, requested_timeout: int) -> int:
    """Honor a profile minimum for repositories with expensive repeated suites."""
    return max(requested_timeout, int(instance.get("coverage_phase_timeout", 0)))


def _is_flaky(main_exit: int | None, repeat_exits: list[int | None]) -> bool:
    return main_exit is not None and any(code is None or code != main_exit for code in repeat_exits)


def _tool_install_lines(instance: dict) -> list[str]:
    tool_install = instance.get("coverage_tool_install_command")
    if tool_install:
        return [tool_install]
    old_python_unsupported = [] if instance.get("mutation_command") else [
        f"  {_MUTATION_UNSUPPORTED}=1",
        f"  echo {_MUTATION_UNSUPPORTED}=1",
    ]
    return [
        "if python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then",
        "  python -m pip install --disable-pip-version-check pytest coverage 'mutmut<3'",
        "elif python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 7) else 1)'; then",
        "  python -m pip install --disable-pip-version-check 'pytest<8' coverage 'mutmut<3'",
        "elif python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 6) else 1)'; then",
        "  python -m pip install --disable-pip-version-check 'pytest<7' 'coverage<6' 'mutmut<2'",
        "else",
        "  python -m pip install --disable-pip-version-check 'pytest<6' 'coverage<6'",
        *old_python_unsupported,
        "fi",
    ]


def _extract_block(output: str, start: str, end: str) -> str:
    start_matches = list(re.finditer(rf"(?m)^{re.escape(start)}\s*$", output))
    if not start_matches:
        return ""
    block_start = start_matches[-1].end()
    end_match = re.search(rf"(?m)^{re.escape(end)}\s*$", output[block_start:])
    if not end_match:
        return ""
    return output[block_start:block_start + end_match.start()].strip()


def _module_level_pytest_files(patch: str) -> list[str]:
    """Find Biopython test files containing added module-level pytest tests."""
    current = None
    matched: set[str] = set()
    for line in patch.splitlines():
        header = re.match(r"^diff --git a/(.+) b/(.+)$", line)
        if header:
            current = header.group(2)
            continue
        if (
            current
            and Path(current).parts[:1] == ("Tests",)
            and Path(current).name.startswith("test_")
            and Path(current).suffix == ".py"
            and re.match(r"^\+(?:async\s+)?def\s+test_", line)
        ):
            matched.add(current)
    return sorted(matched)


def _phase_script(instance: dict, apply_patch: bool, flaky_runs: int) -> str:
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    pytest_command = instance.get("coverage_test_command") or "python -m pytest"
    coverage_command = instance.get("coverage_command") or "python -m coverage run --branch -m pytest"
    coverage_results_command = instance.get("coverage_results_command") or (
        "python -m coverage json -o /tmp/coverage.json"
    )
    targets = infer_coverage_targets(instance)
    default_mutation = "mutmut run --paths-to-mutate=" + shlex.quote(",".join(targets))
    mutation_command = instance.get("mutation_command") or default_mutation
    mutation_compatibility = []
    if not instance.get("mutation_command"):
        mutation_compatibility = _mutmut_sqlite_compatibility_lines()
        mutation_command = _with_mutmut_compatibility(mutation_command)
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
    lines += _tool_install_lines(instance)
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
        coverage_results_command.replace("{output}", "/tmp/coverage.json"),
        f"echo {_COVERAGE_START}; cat /tmp/coverage.json 2>/dev/null || true; echo {_COVERAGE_END}",
    ]
    for index in range(flaky_runs):
        lines += [f"{pytest_command}", f"echo REPEAT_RUN_{index + 1}_EXIT=$?"]
    lines += mutation_compatibility
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


def _standalone_phase_script(
    instance: dict,
    patch_path: Path,
    apply_patch: bool,
    flaky_runs: int,
) -> str:
    """Build a host-side phase script for a clean standalone repository clone."""
    pytest_command = instance.get("coverage_test_command") or "python -m pytest"
    coverage_command = instance.get("coverage_command") or (
        "python -m coverage run --branch --source=. -m pytest"
    )
    coverage_output = "/tmp/coverage-generation.json"
    coverage_results_command = instance.get("coverage_results_command") or (
        "python -m coverage json -o {output}"
    )
    supplemental_pytest_files = (
        _module_level_pytest_files(patch_path.read_text())
        if apply_patch and patch_path.exists()
        and instance.get("mutation_test_style") == "biopython"
        else []
    )
    supplemental_pytest = "python -m pytest -- " + " ".join(
        shlex.quote(path) for path in supplemental_pytest_files
    )
    supplemental_coverage = instance.get("coverage_pytest_command")
    if supplemental_coverage and supplemental_pytest_files:
        supplemental_coverage += " -- " + " ".join(
            shlex.quote(path) for path in supplemental_pytest_files
        )
    lines = [
        "#!/bin/bash",
        "set -uxo pipefail",
        f"git reset --hard {shlex.quote(instance['base_commit'])}",
        "git clean -fdx",
    ]
    absolute_patch_path = patch_path.resolve()
    if apply_patch:
        lines += [
            f"git apply -v {shlex.quote(str(absolute_patch_path))} || "
            f"git apply -v --3way {shlex.quote(str(absolute_patch_path))} || "
            f"patch --batch --fuzz=5 -p1 -i {shlex.quote(str(absolute_patch_path))} || "
            f"{{ echo {PATCH_FAILED}; exit 11; }}",
            f"echo {PATCH_APPLIED}",
        ]
    if supplemental_pytest_files:
        quoted_files = " ".join(shlex.quote(path) for path in supplemental_pytest_files)
        lines += [
            "run_without_generated_pytests() {",
            "  local command=$1 status path stash",
            "  stash=$(mktemp -d)",
            f"  for path in {quoted_files}; do mv \"$path\" \"$stash/$(basename \"$path\")\"; done",
            "  eval \"$command\"",
            "  status=$?",
            f"  for path in {quoted_files}; do mv \"$stash/$(basename \"$path\")\" \"$path\"; done",
            "  rmdir \"$stash\"",
            "  return $status",
            "}",
        ]
    setup_command = instance.get("coverage_setup_command")
    if setup_command:
        lines += [setup_command, "SETUP_EXIT=$?"]
    else:
        lines.append("SETUP_EXIT=0")
    lines += _tool_install_lines({**instance, "mutation_command": "coverage-phase"})
    phase_commands = [pytest_command, coverage_command]
    if supplemental_pytest_files:
        phase_commands.extend([supplemental_pytest, supplemental_coverage or ""])
    tool_checks = []
    if any("pytest" in command for command in phase_commands):
        tool_checks.append("python -c 'import pytest'")
    if any(
        "python -m coverage" in command or command.lstrip().startswith("coverage ")
        for command in phase_commands
    ):
        tool_checks.append("python -m coverage --version")
    tools_check = " && ".join(tool_checks) or "true"
    primary_test_command = (
        f"run_without_generated_pytests {shlex.quote(pytest_command)}"
        if supplemental_pytest_files else pytest_command
    )
    primary_coverage_command = (
        f"run_without_generated_pytests {shlex.quote(coverage_command)}"
        if supplemental_pytest_files else coverage_command
    )
    lines += [
        tools_check,
        "TOOLS_EXIT=$?",
        primary_test_command,
        "PRIMARY_TEST_EXIT=$?",
    ]
    if supplemental_pytest_files:
        lines += [
            supplemental_pytest,
            "GENERATED_PYTEST_EXIT=$?",
            "PYTEST_EXIT=$PRIMARY_TEST_EXIT",
            '[ "$PYTEST_EXIT" -ne 0 ] || PYTEST_EXIT=$GENERATED_PYTEST_EXIT',
        ]
    else:
        lines.append("PYTEST_EXIT=$PRIMARY_TEST_EXIT")
    lines += [
        "python -m coverage erase",
        primary_coverage_command,
        "PRIMARY_COVERAGE_EXIT=$?",
    ]
    if supplemental_pytest_files and supplemental_coverage:
        lines += [
            supplemental_coverage,
            "GENERATED_COVERAGE_EXIT=$?",
            "COVERAGE_TEST_EXIT=$PRIMARY_COVERAGE_EXIT",
            '[ "$COVERAGE_TEST_EXIT" -ne 0 ] || COVERAGE_TEST_EXIT=$GENERATED_COVERAGE_EXIT',
        ]
    else:
        lines.append("COVERAGE_TEST_EXIT=$PRIMARY_COVERAGE_EXIT")
    lines += [
        coverage_results_command.replace("{output}", shlex.quote(coverage_output)),
        f"echo {_COVERAGE_START}; cat {coverage_output} 2>/dev/null || true; echo {_COVERAGE_END}",
    ]
    for index in range(flaky_runs):
        repeat_var = f"REPEAT_RUN_{index + 1}_EXIT"
        lines += [primary_test_command, "PRIMARY_REPEAT_EXIT=$?"]
        if supplemental_pytest_files:
            lines += [
                supplemental_pytest,
                "GENERATED_REPEAT_EXIT=$?",
                f"{repeat_var}=$PRIMARY_REPEAT_EXIT",
                f'[ "${repeat_var}" -ne 0 ] || {repeat_var}=$GENERATED_REPEAT_EXIT',
                f"echo {repeat_var}=${{{repeat_var}}}",
            ]
        else:
            lines.append(f"echo {repeat_var}=$PRIMARY_REPEAT_EXIT")
    lines += [
        "echo SETUP_EXIT=$SETUP_EXIT",
        "echo TOOLS_EXIT=$TOOLS_EXIT",
        "echo PYTEST_EXIT=$PYTEST_EXIT",
        "echo COVERAGE_TEST_EXIT=$COVERAGE_TEST_EXIT",
        "exit 0",
    ]
    return "\n".join(lines) + "\n"


def _standalone_mutation_script(
    instance: dict,
    patch_path: Path,
    apply_patch: bool,
    targets: list[str],
) -> str:
    """Build a mutation-only script scoped to agent-selected production modules."""
    quoted_targets = shlex.quote(",".join(targets))
    custom_command = instance.get("mutation_command")
    runner_setup: list[str] = []
    mutation_test_style = instance.get("mutation_test_style")
    if not custom_command and mutation_test_style in {"biopython", "pytest_generated"}:
        patch_info = inspect_test_patch(patch_path.read_text())
        test_files = sorted({
            path
            for path in patch_info.get("changed_files", [])
            if _is_test_path(path)
            and (
                Path(path).name.startswith("test_")
                or Path(path).name.endswith("_test.py")
            )
            and Path(path).suffix == ".py"
        })
        tests_dir = instance.get("mutation_tests_dir") or (
            "Tests" if mutation_test_style == "biopython" else "tests"
        )
        runner = ".coverage-generation-mutmut-runner.sh"
        runner_lines = ["#!/bin/bash", "set -uo pipefail", "tests=()"]
        for path in test_files:
            runner_lines.append(
                f"[ ! -f {shlex.quote(path)} ] || tests+=({shlex.quote(path)})"
            )
        runner_lines += [
            "if [ ${#tests[@]} -eq 0 ]; then",
            # Keep before/after selection symmetric when the patch creates every
            # touched test module. Expanding only the baseline to the full suite
            # makes mutation scores incomparable and can be prohibitively slow.
            "  exit 0",
            "fi",
            'exec python -m pytest -- "${tests[@]}"',
        ]
        runner_content = "\n".join(runner_lines) + "\n"
        runner_setup = [
            f"printf %s {shlex.quote(runner_content)} > {runner}",
            f"chmod +x {runner}",
        ]
        mutation_command = (
            "mutmut run --paths-to-mutate=" + quoted_targets
            + " --tests-dir=" + shlex.quote(tests_dir)
            + " --runner=" + shlex.quote(f"./{runner}")
        )
    else:
        mutation_command = (
            custom_command.replace("{targets}", quoted_targets)
            if custom_command and "{targets}" in custom_command
            else custom_command
            if custom_command
            else "mutmut run --paths-to-mutate=" + quoted_targets
        )
    mutation_compatibility = []
    if not custom_command:
        mutation_compatibility = _mutmut_sqlite_compatibility_lines()
        mutation_command = _with_mutmut_compatibility(mutation_command)
    mutation_results_command = instance.get("mutation_results_command") or "mutmut results"
    mutation_export_lines = []
    if not custom_command:
        exporter = Path(__file__).with_name("mutation_export.py").resolve()
        mutation_export_lines = [
            "if [ -f .mutmut-cache ]; then",
            f"  python {shlex.quote(str(exporter))} "
            "--cache .mutmut-cache --output .mutation-details.json || true",
            "fi",
        ]
    lines = [
        "#!/bin/bash",
        "set -uxo pipefail",
        f"git reset --hard {shlex.quote(instance['base_commit'])}",
        "git clean -fdx",
    ]
    absolute_patch_path = patch_path.resolve()
    if apply_patch:
        lines += [
            f"git apply -v {shlex.quote(str(absolute_patch_path))} || "
            f"git apply -v --3way {shlex.quote(str(absolute_patch_path))} || "
            f"patch --batch --fuzz=5 -p1 -i {shlex.quote(str(absolute_patch_path))} || "
            f"{{ echo {PATCH_FAILED}; exit 11; }}",
            f"echo {PATCH_APPLIED}",
        ]
    setup_command = instance.get("coverage_setup_command")
    lines += [setup_command, "SETUP_EXIT=$?"] if setup_command else ["SETUP_EXIT=0"]
    lines += _tool_install_lines(instance)
    lines += runner_setup
    lines += mutation_compatibility
    lines += [
        f"echo {_MUTATION_START}",
        f"if [ \"${{{_MUTATION_UNSUPPORTED}:-0}}\" = 1 ]; then",
        "  MUTATION_EXIT=125",
        "else",
        f"  {mutation_command}",
        "  MUTATION_EXIT=$?",
        f"  {mutation_results_command} 2>&1 || true",
        "fi",
        f"echo {_MUTATION_END}",
        *mutation_export_lines,
        "echo SETUP_EXIT=$SETUP_EXIT",
        "echo MUTATION_EXIT=$MUTATION_EXIT",
        "exit 0",
    ]
    return "\n".join(lines) + "\n"


def _run_standalone_phase(
    instance: dict,
    patch_path: Path,
    apply_patch: bool,
    flaky_runs: int,
    out_dir: Path,
    name: str,
    timeout: int,
    github_token: str | None,
) -> tuple[str, bool, float]:
    from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit

    started = time.perf_counter()
    repo_dir = None
    script_path = out_dir / f"{name}.sh"
    script_path.write_text(
        _standalone_phase_script(instance, patch_path, apply_patch, flaky_runs)
    )
    try:
        repo_dir = _clone_repo_at_commit(
            instance.get("repo_url") or instance["repo"],
            instance["base_commit"],
            github_token,
            tmp_root=out_dir / "worktrees",
        )
        try:
            with isolated_python_environment(
                out_dir / "environments",
                instance.get("coverage_python_executable"),
            ) as environment:
                completed = subprocess.run(
                    ["/bin/bash", str(script_path.resolve())],
                    cwd=repo_dir,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                )
            output, timed_out = completed.stdout or "", False
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout or ""
            output = raw if isinstance(raw, str) else raw.decode(errors="replace")
            timed_out = True
        (out_dir / f"{name}.log").write_text(output)
        return output, timed_out, time.perf_counter() - started
    finally:
        if repo_dir:
            shutil.rmtree(repo_dir, ignore_errors=True)


def _run_standalone_mutation_phase(
    instance: dict,
    patch_path: Path,
    apply_patch: bool,
    targets: list[str],
    out_dir: Path,
    name: str,
    timeout: int,
    github_token: str | None,
) -> tuple[str, bool, float]:
    """Run one clean, target-scoped mutation phase."""
    from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit

    started = time.perf_counter()
    repo_dir = None
    script_path = out_dir / f"{name}.sh"
    script_path.write_text(
        _standalone_mutation_script(instance, patch_path, apply_patch, targets)
    )
    try:
        repo_dir = _clone_repo_at_commit(
            instance.get("repo_url") or instance["repo"],
            instance["base_commit"],
            github_token,
            tmp_root=out_dir / "worktrees",
        )
        try:
            with isolated_python_environment(
                out_dir / "environments",
                instance.get("coverage_python_executable"),
            ) as environment:
                completed = subprocess.run(
                    ["/bin/bash", str(script_path.resolve())],
                    cwd=repo_dir,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                )
            output, timed_out = completed.stdout or "", False
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout or ""
            output = raw if isinstance(raw, str) else raw.decode(errors="replace")
            timed_out = True
        (out_dir / f"{name}.log").write_text(output)
        details_path = repo_dir / ".mutation-details.json"
        if details_path.is_file():
            shutil.copy2(details_path, out_dir / f"{name}.mutants.json")
        return output, timed_out, time.perf_counter() - started
    finally:
        if repo_dir:
            shutil.rmtree(repo_dir, ignore_errors=True)


def _exit_code(output: str, name: str) -> int | None:
    matches = re.findall(rf"(?m)^{re.escape(name)}=(\d+)\s*$", output)
    return int(matches[-1]) if matches else None


def prepare_standalone_coverage_baseline(
    instance: dict,
    run_id: str,
    log_dir: str = "logs/run_evaluation",
    timeout: int = 3600,
    flaky_runs: int = 2,
    github_token: str | None = None,
) -> dict:
    """Measure whole-repository baseline coverage before agent inference."""
    out_dir = Path(log_dir) / run_id / "baseline" / instance["instance_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    placeholder_patch = out_dir / "unused.patch"
    placeholder_patch.write_text("")
    output, timed_out, runtime = _run_standalone_phase(
        instance,
        placeholder_patch,
        False,
        flaky_runs,
        out_dir,
        "baseline_coverage",
        _coverage_phase_timeout(instance, timeout),
        github_token,
    )
    coverage = parse_coverage_json(
        _extract_block(output, _COVERAGE_START, _COVERAGE_END), []
    )
    result = {
        "output": output,
        "coverage": coverage,
        "timed_out": timed_out,
        "runtime": runtime,
        "setup_exit": _exit_code(output, "SETUP_EXIT"),
        "tools_exit": _exit_code(output, "TOOLS_EXIT"),
        "test_exit": _exit_code(output, "PYTEST_EXIT"),
        "coverage_test_exit": _exit_code(output, "COVERAGE_TEST_EXIT"),
        "repeat_exits": [
            _exit_code(output, f"REPEAT_RUN_{index + 1}_EXIT")
            for index in range(flaky_runs)
        ],
    }
    serializable = {key: value for key, value in result.items() if key != "output"}
    (out_dir / "baseline.json").write_text(json.dumps(serializable, indent=2))
    return result


def standalone_baseline_failure(baseline: dict) -> str:
    """Return why a baseline is invalid, or an empty string when usable."""
    if baseline.get("timed_out"):
        return "baseline_timeout"
    if baseline.get("setup_exit") != 0:
        return "baseline_repository_setup_failed"
    if baseline.get("tools_exit") != 0:
        return "baseline_test_or_coverage_tools_unavailable"
    if baseline.get("test_exit") != 0:
        return "baseline_tests_failed"
    if baseline.get("coverage_test_exit") != 0:
        return "baseline_coverage_test_failed"
    if baseline.get("coverage") is None:
        return "baseline_coverage_unavailable"
    repeat_exits = baseline.get("repeat_exits") or []
    if any(exit_code != 0 for exit_code in repeat_exits):
        return "baseline_test_suite_flaky_or_failed"
    return ""


def classify_coverage_result(before: dict | None, after: dict | None, patch_info: dict,
                             before_test_exit: int | None, after_test_exit: int | None,
                             patch_applied: bool, timed_out: bool,
                             coverage_test_failed: bool = False,
                             mutation_before: dict | None = None,
                             mutation_after: dict | None = None,
                             mutation_timed_out: bool = False,
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
    if mutation_timed_out:
        return "partial", "mutation_evaluation_timeout"
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


def _mark_inference_completion(result: dict, prediction: dict | None) -> dict:
    """Preserve scientific metrics while flagging an interrupted agent result."""
    inference_error = (prediction or {}).get("error")
    result["inference_completed"] = not bool(inference_error)
    if inference_error:
        result["inference_error"] = inference_error
        result["failure_reason"] = result.get("failure_reason") or inference_error
        if result.get("status") == "resolved":
            result["coverage_status"] = "resolved"
            result["status"] = "partial"
    return result


def run_standalone_coverage_evaluation(
    instance: dict,
    prediction: dict | None,
    run_id: str,
    log_dir: str = "logs/run_evaluation",
    timeout: int = 3600,
    flaky_runs: int = 2,
    github_token: str | None = None,
    baseline: dict | None = None,
    run_mutation: bool = True,
) -> dict:
    """Evaluate one repo/commit directly, without SWE-bench issue or Docker metadata."""
    started = time.perf_counter()
    iid = instance["instance_id"]
    model_dir = ((prediction or {}).get("model_name_or_path") or "unknown").replace("/", "__")
    out_dir = Path(log_dir) / run_id / model_dir / iid
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    patch = (prediction or {}).get("model_patch") or ""
    patch_info = inspect_test_patch(patch)
    targets = infer_coverage_targets(instance)
    if not patch.strip():
        inference_error = (prediction or {}).get("error") or "empty_prediction"
        baseline = baseline or {}
        baseline_repeats = baseline.get("repeat_exits") or []
        result = {
            "status": "no-pred",
            "failure_reason": inference_error,
            "error": inference_error,
            **patch_info,
            "standalone": True,
            "coverage_targets": targets,
            "coverage_scope": "repository",
            "mutation_targets": [],
            "mutation_skipped_no_selected_modules": True,
            "repo_url": instance.get("repo_url") or instance.get("repo"),
            "base_commit": instance["base_commit"],
            "setup_before_exit_code": baseline.get("setup_exit"),
            "tools_before_exit_code": baseline.get("tools_exit"),
            "base_tests_passed": baseline.get("test_exit") == 0,
            "base_coverage_tests_passed": baseline.get("coverage_test_exit") == 0,
            "baseline_flaky": any(code != 0 for code in baseline_repeats),
            "coverage_before": baseline.get("coverage"),
            "before_wall_time_seconds": round(float(baseline.get("runtime", 0.0)), 6),
            "inference_metrics": (prediction or {}).get("metrics", {}),
            "evaluation_wall_time_seconds": round(time.perf_counter() - started, 6),
        }
        _mark_inference_completion(result, prediction)
        report_path.write_text(json.dumps({iid: result}, indent=2))
        return result

    patch_path = out_dir / "generated_test.patch"
    patch_path.write_text(patch)
    try:
        if baseline is None:
            before_output, before_timeout, before_runtime = _run_standalone_phase(
                instance, patch_path, False, flaky_runs, out_dir, "before",
                _coverage_phase_timeout(instance, timeout),
                github_token,
            )
            before_cov = parse_coverage_json(
                _extract_block(before_output, _COVERAGE_START, _COVERAGE_END), []
            )
            before_exit = _exit_code(before_output, "PYTEST_EXIT")
            before_coverage_exit = _exit_code(before_output, "COVERAGE_TEST_EXIT")
            before_setup_exit = _exit_code(before_output, "SETUP_EXIT")
            before_tools_exit = _exit_code(before_output, "TOOLS_EXIT")
            baseline_repeat_exits = [
                _exit_code(before_output, f"REPEAT_RUN_{i + 1}_EXIT")
                for i in range(flaky_runs)
            ]
        else:
            before_output = baseline.get("output", "")
            before_timeout = bool(baseline.get("timed_out"))
            before_runtime = float(baseline.get("runtime", 0.0))
            before_cov = baseline.get("coverage")
            before_exit = baseline.get("test_exit")
            before_coverage_exit = baseline.get("coverage_test_exit")
            before_setup_exit = baseline.get("setup_exit")
            before_tools_exit = baseline.get("tools_exit")
            baseline_repeat_exits = baseline.get("repeat_exits") or []
        after_output, after_timeout, after_runtime = _run_standalone_phase(
            instance, patch_path, True, flaky_runs, out_dir, "after",
            _coverage_phase_timeout(instance, timeout), github_token
        )
        after_cov = parse_coverage_json(
            _extract_block(after_output, _COVERAGE_START, _COVERAGE_END), []
        )
        after_exit = _exit_code(after_output, "PYTEST_EXIT")
        after_coverage_exit = _exit_code(after_output, "COVERAGE_TEST_EXIT")
        after_setup_exit = _exit_code(after_output, "SETUP_EXIT")
        after_tools_exit = _exit_code(after_output, "TOOLS_EXIT")
        after_repeat_exits = [
            _exit_code(after_output, f"REPEAT_RUN_{i + 1}_EXIT") for i in range(flaky_runs)
        ]
        baseline_flaky = _is_flaky(before_exit, baseline_repeat_exits)
        generated_tests_flaky = _is_flaky(after_exit, after_repeat_exits)
        selected_mutation_targets = (
            select_mutation_targets(before_cov, after_cov, targets)
            if run_mutation else []
        )
        mutation_targets, mutation_excluded_targets = exclude_mutation_targets(
            selected_mutation_targets, instance.get("mutation_excluded_targets")
        )
        before_mut = after_mut = None
        before_mutation_exit = after_mutation_exit = 125
        mutation_before_setup_exit = mutation_after_setup_exit = None
        mutation_before_timeout = mutation_after_timeout = False
        mutation_before_runtime = mutation_after_runtime = 0.0
        mutation_before_output = mutation_after_output = _MUTATION_SKIPPED
        if mutation_targets:
            (
                mutation_before_output,
                mutation_before_timeout,
                mutation_before_runtime,
            ) = _run_standalone_mutation_phase(
                instance, patch_path, False, mutation_targets, out_dir,
                "mutation_before", timeout, github_token,
            )
            (
                mutation_after_output,
                mutation_after_timeout,
                mutation_after_runtime,
            ) = _run_standalone_mutation_phase(
                instance, patch_path, True, mutation_targets, out_dir,
                "mutation_after", timeout, github_token,
            )
            before_mut = parse_mutation_results(
                _extract_block(mutation_before_output, _MUTATION_START, _MUTATION_END)
            )
            after_mut = parse_mutation_results(
                _extract_block(mutation_after_output, _MUTATION_START, _MUTATION_END)
            )
            before_mutation_exit = _exit_code(mutation_before_output, "MUTATION_EXIT")
            after_mutation_exit = _exit_code(mutation_after_output, "MUTATION_EXIT")
            mutation_before_setup_exit = _exit_code(mutation_before_output, "SETUP_EXIT")
            mutation_after_setup_exit = _exit_code(mutation_after_output, "SETUP_EXIT")
        usable_before_mut = None if mutation_exit_is_fatal(before_mutation_exit) else before_mut
        usable_after_mut = None if mutation_exit_is_fatal(after_mutation_exit) else after_mut
        if before_timeout or after_timeout:
            status, reason = "errored", "evaluation_timeout"
        elif PATCH_APPLIED not in after_output:
            status, reason = "errored", "test_patch_failed"
        elif (
            before_setup_exit != 0
            or after_setup_exit != 0
            or mutation_before_setup_exit not in {None, 0}
            or mutation_after_setup_exit not in {None, 0}
        ):
            status, reason = "errored", "repository_setup_failed"
        elif before_tools_exit != 0 or after_tools_exit != 0:
            status, reason = "errored", "test_or_coverage_tools_unavailable"
        else:
            status, reason = classify_coverage_result(
                before_cov,
                after_cov,
                patch_info,
                before_exit,
                after_exit,
                PATCH_APPLIED in after_output,
                before_timeout or after_timeout,
                coverage_test_failed=(before_coverage_exit != 0 or after_coverage_exit != 0),
                mutation_before=usable_before_mut,
                mutation_after=usable_after_mut,
                mutation_timed_out=mutation_before_timeout or mutation_after_timeout,
                baseline_flaky=baseline_flaky,
                generated_tests_flaky=generated_tests_flaky,
            )
        result = {
            "status": status,
            "failure_reason": reason,
            **patch_info,
            "standalone": True,
            "repo_url": instance.get("repo_url") or instance.get("repo"),
            "base_commit": instance["base_commit"],
            "coverage_targets": targets,
            "coverage_scope": "repository",
            "mutation_targets": mutation_targets,
            "mutation_excluded_targets": mutation_excluded_targets,
            "mutation_skipped_no_selected_modules": not mutation_targets,
            "test_patch_applied": PATCH_APPLIED in after_output,
            "setup_before_exit_code": before_setup_exit,
            "setup_after_exit_code": after_setup_exit,
            "tools_before_exit_code": before_tools_exit,
            "tools_after_exit_code": after_tools_exit,
            "base_tests_passed": before_exit == 0,
            "after_tests_passed": after_exit == 0,
            "base_coverage_tests_passed": before_coverage_exit == 0,
            "after_coverage_tests_passed": after_coverage_exit == 0,
            "baseline_flaky": baseline_flaky,
            "generated_tests_flaky": generated_tests_flaky,
            "flaky": baseline_flaky or generated_tests_flaky,
            "baseline_repeat_exit_codes": baseline_repeat_exits,
            "after_repeat_exit_codes": after_repeat_exits,
            "flaky_run_exit_codes": after_repeat_exits,
            "coverage_before": before_cov,
            "coverage_after": after_cov,
            "coverage_line_delta": (
                after_cov["line_coverage"] - before_cov["line_coverage"]
                if before_cov and after_cov else None
            ),
            "coverage_branch_delta": (
                after_cov["branch_coverage"] - before_cov["branch_coverage"]
                if before_cov and after_cov else None
            ),
            "mutation_before": before_mut,
            "mutation_after": after_mut,
            "mutation_before_partial": (
                parse_mutation_progress(mutation_before_output)
                if mutation_before_timeout else None
            ),
            "mutation_after_partial": (
                parse_mutation_progress(mutation_after_output)
                if mutation_after_timeout else None
            ),
            "mutation_before_exit_code": before_mutation_exit,
            "mutation_after_exit_code": after_mutation_exit,
            "mutation_before_timed_out": mutation_before_timeout,
            "mutation_after_timed_out": mutation_after_timeout,
            "mutation_setup_before_exit_code": mutation_before_setup_exit,
            "mutation_setup_after_exit_code": mutation_after_setup_exit,
            "mutation_before_tool_error": bool(mutation_targets)
            and mutation_exit_is_fatal(before_mutation_exit),
            "mutation_after_tool_error": bool(mutation_targets)
            and mutation_exit_is_fatal(after_mutation_exit),
            "mutation_unsupported_python": (
                f"{_MUTATION_UNSUPPORTED}=1" in mutation_before_output
                or f"{_MUTATION_UNSUPPORTED}=1" in mutation_after_output
            ),
            "mutation_score_delta": (
                usable_after_mut["score"] - usable_before_mut["score"]
                if usable_before_mut and usable_after_mut else None
            ),
            "before_wall_time_seconds": round(before_runtime, 6),
            "after_wall_time_seconds": round(after_runtime, 6),
            "mutation_before_wall_time_seconds": round(mutation_before_runtime, 6),
            "mutation_after_wall_time_seconds": round(mutation_after_runtime, 6),
            "inference_metrics": (prediction or {}).get("metrics", {}),
        }
    except Exception as exc:
        logger.exception("standalone coverage-generation evaluation failed for %s", iid)
        result = {
            "status": "errored",
            "failure_reason": "evaluation_exception",
            "error": f"{type(exc).__name__}: {exc}",
            **patch_info,
            "standalone": True,
            "repo_url": instance.get("repo_url") or instance.get("repo"),
            "base_commit": instance["base_commit"],
            "coverage_targets": targets,
            "inference_metrics": (prediction or {}).get("metrics", {}),
        }
    _mark_inference_completion(result, prediction)
    result["evaluation_wall_time_seconds"] = round(time.perf_counter() - started, 6)
    report_path.write_text(json.dumps({iid: result}, indent=2))
    return result


def common_improved_modules(
    baseline_coverage: dict | None, arm_results: list[dict],
    explicit_targets: list[str] | None = None,
) -> list[str]:
    """Form one deterministic mutation target union across generator arms."""
    if explicit_targets:
        return sorted(set(explicit_targets))
    targets: set[str] = set()
    for result in arm_results:
        targets.update(
            select_mutation_targets(baseline_coverage, result.get("coverage_after"), None)
        )
    return sorted(targets)


def limit_mutation_targets(
    targets: list[str],
    baseline_coverage: dict | None,
    arm_results: list[dict],
    statement_budget: int,
) -> tuple[list[str], list[str]]:
    """Keep the highest-value modules within a deterministic statement budget."""
    if statement_budget <= 0:
        return sorted(set(targets)), []
    baseline_files = (baseline_coverage or {}).get("files") or {}

    def priority(path: str) -> tuple[int, int, str]:
        before = baseline_files.get(path) or {}
        gain = 0
        for result in arm_results:
            after = ((result.get("coverage_after") or {}).get("files") or {}).get(path)
            if after:
                gain += max(0, after.get("covered_lines", 0) - before.get("covered_lines", 0))
                gain += max(
                    0,
                    after.get("covered_branches", 0)
                    - before.get("covered_branches", 0),
                )
        statements = int(before.get("num_statements", 0))
        return -gain, statements, path

    ranked_targets = sorted(set(targets), key=priority)
    selected: list[str] = []
    used = 0
    for path in ranked_targets:
        statements = int((baseline_files.get(path) or {}).get("num_statements", 0))
        if statements and used + statements > statement_budget:
            continue
        selected.append(path)
        used += statements
    # A budget smaller than every candidate should still produce a mutation
    # measurement rather than silently disabling the phase.
    if not selected and ranked_targets:
        selected.append(ranked_targets[0])
    excluded = sorted(set(targets) - set(selected))
    return sorted(selected), excluded


def freeze_agent_selected_targets(
    baseline_coverage: dict | None,
    agent_result: dict,
    statement_budget: int = 500,
    excluded_targets: list[str] | None = None,
    importable_modules: set[str] | None = None,
) -> dict:
    """Freeze shared targets using only a valid agent arm's coverage gains.

    The returned manifest is deliberately self-contained so later Pynguin and
    mutation stages never need to inspect either arm while choosing targets.
    """
    from swebench.eval_pipeline.pynguin_generation import module_name_from_path

    validity_checks = {
        "patch_present": bool(agent_result.get("changed_files")),
        "tests_only_patch": agent_result.get("tests_only_patch") is True,
        "no_existing_test_lines_removed": (
            agent_result.get("no_existing_test_lines_removed") is True
        ),
        "patch_applied": agent_result.get("test_patch_applied") is True,
        "tests_passed": agent_result.get("after_tests_passed") is True,
        "coverage_tests_passed": (
            agent_result.get("after_coverage_tests_passed") is True
        ),
        "non_flaky": not bool(agent_result.get("flaky")),
    }
    valid_agent_patch = all(validity_checks.values())
    before_files = (baseline_coverage or {}).get("files") or {}
    after_files = ((agent_result.get("coverage_after") or {}).get("files") or {})
    compatibility_exclusions = set(excluded_targets or [])
    candidates: list[dict] = []

    if valid_agent_patch:
        for path, after in after_files.items():
            before = before_files.get(path)
            if before is None:
                continue
            line_gain = max(
                0, int(after.get("covered_lines", 0))
                - int(before.get("covered_lines", 0))
            )
            branch_gain = max(
                0, int(after.get("covered_branches", 0))
                - int(before.get("covered_branches", 0))
            )
            if line_gain + branch_gain <= 0:
                continue
            module = module_name_from_path(path)
            reason = ""
            if module is None:
                reason = "not_importable_path"
            elif path in compatibility_exclusions:
                reason = "mutmut_incompatible"
            elif importable_modules is not None and module not in importable_modules:
                reason = "not_importable"
            candidates.append({
                "path": path,
                "module": module or "",
                "covered_line_gain": line_gain,
                "covered_branch_gain": branch_gain,
                "total_gain": line_gain + branch_gain,
                "baseline_statements": int(before.get("num_statements", 0)),
                "selected": False,
                "exclusion_reason": reason,
            })

    candidates.sort(
        key=lambda item: (
            -item["total_gain"],
            item["baseline_statements"],
            item["path"],
        )
    )
    used_statements = 0
    rank = 0
    for candidate in candidates:
        rank += 1
        candidate["rank"] = rank
        if candidate["exclusion_reason"]:
            continue
        statements = candidate["baseline_statements"]
        if (
            statement_budget > 0
            and statements
            and used_statements + statements > statement_budget
        ):
            candidate["exclusion_reason"] = "statement_budget"
            continue
        candidate["selected"] = True
        used_statements += statements

    selected = [item for item in candidates if item["selected"]]
    failure_reason = ""
    if not valid_agent_patch:
        failure_reason = "invalid_agent_patch"
    elif not selected:
        failure_reason = "no_agent_selected_targets"
    return {
        "protocol": "agent_led_shared_targets",
        "selection_source": "agent_coverage_delta_only",
        "valid_agent_patch": valid_agent_patch,
        "validity_checks": validity_checks,
        "statement_budget": statement_budget,
        "selected_statement_count": used_statements,
        "target_paths": [item["path"] for item in selected],
        "import_modules": [item["module"] for item in selected],
        "targets": candidates,
        "failure_reason": failure_reason,
    }


def apply_target_importability_results(
    manifest: dict, module_attempts: list[dict]
) -> dict:
    """Finalize generic import exclusions from pristine-checkout preflights."""
    not_importable = {
        attempt.get("module")
        for attempt in module_attempts
        if attempt.get("status") == "not_importable"
    }
    for target in manifest.get("targets") or []:
        if target.get("selected") and target.get("module") in not_importable:
            target["selected"] = False
            target["exclusion_reason"] = "not_importable"
    selected = [
        target for target in manifest.get("targets") or []
        if target.get("selected")
    ]
    manifest["target_paths"] = [target["path"] for target in selected]
    manifest["import_modules"] = [target["module"] for target in selected]
    manifest["selected_statement_count"] = sum(
        int(target.get("baseline_statements", 0)) for target in selected
    )
    if not selected and manifest.get("valid_agent_patch"):
        manifest["failure_reason"] = "no_agent_selected_targets"
    return manifest


def _eligible_for_mutation(result: dict) -> bool:
    """Mutation is meaningful only for a valid patch whose tests pass."""
    return (
        result.get("after_tests_passed") is not False
        and result.get("tests_only_patch") is not False
        and result.get("no_existing_test_lines_removed") is not False
    )


def evaluate_common_mutation_targets(
    instance: dict,
    predictions: dict[str, dict],
    arm_results: dict[str, dict],
    baseline: dict,
    run_id: str,
    log_dir: str = "logs/run_evaluation",
    timeout: int = 3600,
    github_token: str | None = None,
    frozen_target_manifest: dict | None = None,
) -> tuple[dict, dict[str, dict]]:
    """Evaluate original and every generator against an identical module union.

    Under generated-test profiles, each arm uses only that arm's touched test
    modules; this is explicitly reported as marginal mutation effectiveness.
    """
    eligible_results = [
        result for result in arm_results.values() if _eligible_for_mutation(result)
    ]
    if frozen_target_manifest is not None:
        targets = list(frozen_target_manifest.get("target_paths") or [])
        compatibility_excluded_targets = [
            item["path"]
            for item in frozen_target_manifest.get("targets") or []
            if item.get("exclusion_reason") == "mutmut_incompatible"
        ]
        budget_excluded_targets = [
            item["path"]
            for item in frozen_target_manifest.get("targets") or []
            if item.get("exclusion_reason") == "statement_budget"
        ]
    else:
        selected_targets = common_improved_modules(
            baseline.get("coverage"), eligible_results,
            infer_coverage_targets(instance),
        )
        compatible_targets, compatibility_excluded_targets = exclude_mutation_targets(
            selected_targets, instance.get("mutation_excluded_targets")
        )
        targets, budget_excluded_targets = limit_mutation_targets(
            compatible_targets,
            baseline.get("coverage"),
            eligible_results,
            int(instance.get("mutation_target_statement_budget", 500)),
        )
    excluded_targets = sorted(
        set(compatibility_excluded_targets) | set(budget_excluded_targets)
    )
    root = Path(log_dir) / run_id / "comparison" / instance["instance_id"]
    root.mkdir(parents=True, exist_ok=True)
    def run_arm(name: str, patch: str, apply_patch: bool, eligible: bool = True) -> dict:
        arm_dir = root / name
        arm_dir.mkdir(parents=True, exist_ok=True)
        patch_path = arm_dir / "generated_test.patch"
        patch_path.write_text(patch)
        if not targets or not eligible:
            return {
                "mutation": None, "exit_code": 125, "timed_out": False,
                "setup_exit_code": None, "runtime": 0.0,
                "tool_error": False, "unsupported": False, "partial": None,
            }
        target_groups = (
            [[target] for target in targets]
            if frozen_target_manifest is not None else [targets]
        )
        outputs: list[str] = []
        timed_out = False
        runtime = 0.0
        setup_exit_codes: list[int | None] = []
        exit_codes: list[int | None] = []
        mutations: list[dict] = []
        module_scores: dict[str, float | None] = {}
        per_group_timeout = max(1, timeout // max(1, len(target_groups)))
        for index, group in enumerate(target_groups):
            output, group_timed_out, group_runtime = _run_standalone_mutation_phase(
                instance, patch_path, apply_patch, group, arm_dir,
                f"mutation_{index:03d}", per_group_timeout, github_token,
            )
            outputs.append(output)
            timed_out = timed_out or group_timed_out
            runtime += group_runtime
            exit_codes.append(_exit_code(output, "MUTATION_EXIT"))
            setup_exit_codes.append(_exit_code(output, "SETUP_EXIT"))
            parsed = parse_mutation_results(
                _extract_block(output, _MUTATION_START, _MUTATION_END)
            )
            if parsed:
                mutations.append(parsed)
            if frozen_target_manifest is not None:
                module_scores[group[0]] = (parsed or {}).get("score")
        output = "\n".join(outputs)
        exit_code = next(
            (code for code in exit_codes if mutation_exit_is_fatal(code)),
            exit_codes[-1] if exit_codes else 125,
        )
        mutation = None
        if mutations:
            counts = {
                key: sum(int(item.get(key, 0)) for item in mutations)
                for key in ("killed", "survived", "timeout", "suspicious", "skipped")
            }
            total = sum(counts[key] for key in (
                "killed", "survived", "timeout", "suspicious"
            ))
            mutation = {
                **counts,
                "total": total,
                "score": 100.0 * counts["killed"] / total if total else None,
                "score_killed_only": (
                    100.0 * counts["killed"] / total if total else None
                ),
                "score_killed_or_timeout": (
                    100.0 * (counts["killed"] + counts["timeout"]) / total
                    if total else None
                ),
                "score_definition": (
                    "100 * killed / "
                    "(killed + timeout + survived + suspicious)"
                ),
            }
        return {
            "mutation": mutation,
            "module_scores": module_scores,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "setup_exit_code": next(
                (code for code in setup_exit_codes if code not in {None, 0}),
                setup_exit_codes[-1] if setup_exit_codes else None,
            ),
            "runtime": runtime,
            "tool_error": mutation_exit_is_fatal(exit_code),
            "unsupported": f"{_MUTATION_UNSUPPORTED}=1" in output,
            "partial": parse_mutation_progress(output) if timed_out else None,
        }

    original_mutation = run_arm("original", "", False)
    original = {
        "method": "original", "method_version": instance.get("base_commit", ""),
        "seed": "",
        "status": "resolved", "failure_reason": "",
        "coverage_before": baseline.get("coverage"),
        "coverage_after": baseline.get("coverage"),
        "coverage_line_delta": 0.0, "coverage_branch_delta": 0.0,
        "mutation_targets": targets,
        "mutation_excluded_targets": excluded_targets,
        "mutation_budget_excluded_targets": budget_excluded_targets,
        "target_provenance": (
            "agent_coverage_delta_only"
            if frozen_target_manifest is not None else "cross_arm_coverage_union"
        ),
        "target_manifest": frozen_target_manifest or {},
        "comparison_protocol": (
            "agent_led_shared_targets"
            if frozen_target_manifest is not None else "independent"
        ),
        "target_selection_failure": (
            (frozen_target_manifest or {}).get("failure_reason", "")
        ),
        "mutation_skipped_ineligible": False,
        "mutation_after": original_mutation["mutation"],
        "mutation_module_scores": original_mutation.get("module_scores") or {},
        "mutation_after_partial": original_mutation["partial"],
        "mutation_after_exit_code": original_mutation["exit_code"],
        "mutation_after_timed_out": original_mutation["timed_out"],
        "mutation_after_tool_error": original_mutation["tool_error"],
        "mutation_policy": (
            "touched-test-files-only marginal mutation effectiveness"
            if instance.get("mutation_test_style")
            in {"biopython", "pytest_generated"}
            else "full configured test command"
        ),
        "flaky": any(code != 0 for code in (baseline.get("repeat_exits") or [])),
        "evaluation_wall_time_seconds": (
            float(baseline.get("runtime", 0.0)) + original_mutation["runtime"]
        ),
    }
    baseline_score = (original_mutation.get("mutation") or {}).get("score")
    for name, result in arm_results.items():
        prediction = predictions.get(name) or {}
        patch = prediction.get("model_patch") or ""
        arm_mutation = run_arm(
            name, patch, bool(patch.strip()), _eligible_for_mutation(result)
        )
        result.update({
            "method": name,
            "method_version": (prediction.get("metrics") or {}).get("version", ""),
            "seed": (prediction.get("metrics") or {}).get("seed", ""),
            "mutation_targets": targets,
            "mutation_excluded_targets": excluded_targets,
            "mutation_budget_excluded_targets": budget_excluded_targets,
            "target_provenance": (
                "agent_coverage_delta_only"
                if frozen_target_manifest is not None else "cross_arm_coverage_union"
            ),
            "target_manifest": frozen_target_manifest or {},
            "comparison_protocol": (
                "agent_led_shared_targets"
                if frozen_target_manifest is not None else "independent"
            ),
            "target_selection_failure": (
                (frozen_target_manifest or {}).get("failure_reason", "")
            ),
            "mutation_skipped_no_selected_modules": not targets,
            "mutation_skipped_ineligible": not _eligible_for_mutation(result),
            "mutation_before": original_mutation["mutation"],
            "mutation_after": arm_mutation["mutation"],
            "mutation_module_scores": arm_mutation.get("module_scores") or {},
            "mutation_before_partial": original_mutation["partial"],
            "mutation_after_partial": arm_mutation["partial"],
            "mutation_before_exit_code": original_mutation["exit_code"],
            "mutation_after_exit_code": arm_mutation["exit_code"],
            "mutation_before_timed_out": original_mutation["timed_out"],
            "mutation_after_timed_out": arm_mutation["timed_out"],
            "mutation_before_tool_error": original_mutation["tool_error"],
            "mutation_after_tool_error": arm_mutation["tool_error"],
            "mutation_policy": original["mutation_policy"],
        })
        after_score = (arm_mutation.get("mutation") or {}).get("score")
        result["mutation_score_delta"] = (
            after_score - baseline_score
            if after_score is not None and baseline_score is not None else None
        )
        result["mutation_after_wall_time_seconds"] = arm_mutation["runtime"]
        result["evaluation_wall_time_seconds"] = (
            float(result.get("evaluation_wall_time_seconds", 0.0))
            + arm_mutation["runtime"]
        )
        _refresh_status_after_common_mutation(
            result,
            baseline_score,
            after_score,
            arm_mutation["timed_out"],
        )
    return original, arm_results


def _refresh_status_after_common_mutation(
    result: dict,
    baseline_score: float | None,
    after_score: float | None,
    mutation_timed_out: bool,
) -> None:
    """Finalize a no-gain classification after the deferred common mutation run."""
    if result.get("failure_reason") != "no_coverage_or_mutation_improvement":
        return
    if (
        baseline_score is not None
        and after_score is not None
        and after_score > baseline_score
    ):
        result["status"] = "resolved"
        result["failure_reason"] = ""
    elif mutation_timed_out:
        result["status"] = "partial"
        result["failure_reason"] = "mutation_evaluation_timeout"


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
