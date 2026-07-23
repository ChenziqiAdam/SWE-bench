"""Repository-level scheduler for the single-module Pynguin CLI."""
from __future__ import annotations

import ast
import os
import re
import signal
import shutil
import subprocess
import time
from pathlib import Path


PYNGUIN_POSTPROCESSING_VERSION = 7
PYNGUIN_MODULE_SHUTDOWN_GRACE_SECONDS = 10


_NONCALLABLE_SIGNATURE_COMPAT_SOURCE = """\
import inspect as _pynguin_inspect
import sys as _pynguin_sys

_pynguin_original_signature = _pynguin_inspect.signature

def _pynguin_safe_signature(obj, *args, **kwargs):
    caller = _pynguin_sys._getframe(1).f_globals.get("__name__", "")
    if obj is None and caller == "pynguin.analyses.typesystem":
        return _pynguin_inspect.Signature(parameters=[
            _pynguin_inspect.Parameter(
                "args", kind=_pynguin_inspect.Parameter.VAR_POSITIONAL
            ),
            _pynguin_inspect.Parameter(
                "kwargs", kind=_pynguin_inspect.Parameter.VAR_KEYWORD
            ),
        ])
    return _pynguin_original_signature(obj, *args, **kwargs)

_pynguin_inspect.signature = _pynguin_safe_signature
"""


_OFFLINE_GUARD_SOURCE = """
import pytest as _pynguin_pytest
import socket as _pynguin_socket

def _pynguin_block_network(*args, **kwargs):
    _pynguin_pytest.xfail("Pynguin test requires network access")

@_pynguin_pytest.fixture(autouse=True)
def _pynguin_offline_network(monkeypatch):
    monkeypatch.setattr(_pynguin_socket, "create_connection", _pynguin_block_network)
    monkeypatch.setattr(_pynguin_socket, "getaddrinfo", _pynguin_block_network)
    monkeypatch.setattr(_pynguin_socket, "gethostbyname", _pynguin_block_network)
    monkeypatch.setattr(_pynguin_socket, "gethostbyname_ex", _pynguin_block_network)
    monkeypatch.setattr(_pynguin_socket.socket, "connect", _pynguin_block_network)
    monkeypatch.setattr(_pynguin_socket.socket, "connect_ex", _pynguin_block_network)
"""


class _PortablePynguinTransformer(ast.NodeTransformer):
    """Repair exporter-only imports and remove checkout-specific assertions."""

    def __init__(self, checkout_path: str):
        self.checkout_path = checkout_path
        self.rewritten_imports = 0
        self.removed_assertions = 0
        self.removed_strict_xfail_tests = 0

    def visit_Import(self, node: ast.Import):  # noqa: N802
        replacements: list[ast.stmt] = []
        retained = []
        for alias in node.names:
            if "." in alias.name and alias.asname:
                replacements.append(
                    ast.Assign(
                        targets=[ast.Name(id=alias.asname, ctx=ast.Store())],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="_pynguin_importlib", ctx=ast.Load()),
                                attr="import_module",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Constant(alias.name)],
                            keywords=[],
                        ),
                    )
                )
                self.rewritten_imports += 1
            else:
                retained.append(alias)
        if retained:
            replacements.insert(0, ast.Import(names=retained))
        return replacements

    def visit_Assert(self, node: ast.Assert):  # noqa: N802
        if any(
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and self.checkout_path in child.value
            for child in ast.walk(node)
        ):
            self.removed_assertions += 1
            return None
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):  # noqa: N802
        if _has_strict_xfail(node):
            self.removed_strict_xfail_tests += 1
            return None
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):  # noqa: N802
        if _has_strict_xfail(node):
            self.removed_strict_xfail_tests += 1
            return None
        return self.generic_visit(node)


def _has_strict_xfail(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a test is decorated with ``xfail(strict=True)``."""
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "xfail"
        ):
            continue
        for keyword in decorator.keywords:
            if (
                keyword.arg == "strict"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                return True
    return False


def _imports_scheduled_module(source: str, module: str) -> bool:
    """Reject exporter output that does not import its scheduled SUT module."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            alias.name == module for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return True
    return False


def _contains_test_function(source: str) -> bool:
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
        for node in ast.parse(source).body
    )


def sanitize_pynguin_test(
    source: str,
    repo_dir: Path,
    warning_filters: list[str] | None = None,
) -> tuple[str, dict[str, int]]:
    """Make exported tests portable and prevent uncontrolled network I/O."""
    tree = ast.parse(source)
    transformer = _PortablePynguinTransformer(str(repo_dir.resolve()))
    tree = transformer.visit(tree)
    insert_at = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        insert_at = 1
    while (
        insert_at < len(tree.body)
        and isinstance(tree.body[insert_at], ast.ImportFrom)
        and tree.body[insert_at].module == "__future__"
    ):
        insert_at += 1
    prefix = ast.parse(_OFFLINE_GUARD_SOURCE).body
    filters = warning_filters or []
    if filters:
        prefix.extend(
            ast.parse(
                "pytestmark = [\n"
                + "\n".join(
                    f"    _pynguin_pytest.mark.filterwarnings({item!r}),"
                    for item in filters
                )
                + "\n]\n"
            ).body
        )
    if transformer.rewritten_imports:
        prefix.insert(
            0,
            ast.Import(
                names=[ast.alias(name="importlib", asname="_pynguin_importlib")]
            ),
        )
    tree.body[insert_at:insert_at] = prefix
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", {
        "rewritten_import_count": transformer.rewritten_imports,
        "removed_nonportable_assertion_count": transformer.removed_assertions,
        "removed_strict_xfail_test_count": transformer.removed_strict_xfail_tests,
        "network_guard_injected_count": 1,
        "warning_filter_count": len(filters),
    }


def prune_failing_pynguin_tests(
    test_files: list[Path],
    repo_dir: Path,
    pytest_output: str,
) -> int:
    """Remove exported test functions reported as failed by repository pytest."""
    failed_by_file: dict[str, set[str]] = {}
    for match in re.finditer(r"(?m)^FAILED\s+(.+?)(?:\s+-\s+.*)?$", pytest_output):
        nodeid = match.group(1).strip()
        parts = nodeid.split("::")
        if len(parts) < 2:
            continue
        path = parts[0].replace("\\", "/")
        function = parts[1].split("[", 1)[0]
        failed_by_file.setdefault(path.casefold(), set()).add(function)

    removed = 0
    for test_file in test_files:
        relative = test_file.relative_to(repo_dir).as_posix()
        failed_names = failed_by_file.get(relative.casefold()) or failed_by_file.get(
            str(test_file).casefold()
        )
        if not failed_names or not test_file.exists():
            continue
        tree = ast.parse(test_file.read_text())
        retained = []
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in failed_names
            ):
                removed += 1
            else:
                retained.append(node)
        tree.body = retained
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")
            for node in tree.body
        ):
            test_file.unlink()
            continue
        ast.fix_missing_locations(tree)
        test_file.write_text(ast.unparse(tree) + "\n")
    return removed


def module_name_from_path(path: str) -> str | None:
    """Translate a production Python path into an import name."""
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized.endswith(".py") or "/tests/" in f"/{normalized.lower()}/":
        return None
    parts = normalized[:-3].split("/")
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def rank_pynguin_modules(
    coverage: dict | None, explicit_modules: list[str] | None = None
) -> list[tuple[str, str]]:
    """Return deterministic ``(module, path)`` targets, most uncovered first."""
    files = (coverage or {}).get("files") or {}
    explicit = set(explicit_modules or [])
    ranked = []
    seen: set[str] = set()
    for path, summary in files.items():
        module = module_name_from_path(path)
        if not module or (explicit and module not in explicit and path not in explicit):
            continue
        uncovered_branches = summary.get("num_branches", 0) - summary.get(
            "covered_branches", 0
        )
        uncovered_lines = summary.get("num_statements", 0) - summary.get(
            "covered_lines", 0
        )
        if explicit or uncovered_branches > 0 or uncovered_lines > 0:
            ranked.append((-uncovered_branches, -uncovered_lines, module, path))
            seen.add(module)
    for requested in sorted(explicit):
        module = module_name_from_path(requested) if requested.endswith(".py") else requested
        if module and module not in seen:
            ranked.append((0, 0, module, requested if requested.endswith(".py") else ""))
    return [(module, path) for _, _, module, path in sorted(ranked)]


def conventional_test_directory(repo_dir: Path) -> Path:
    """Choose the repository's existing conventional test directory."""
    for name in ("Tests", "tests", "test"):
        candidate = repo_dir / name
        if candidate.is_dir():
            return candidate
    candidates = sorted(
        (
            path for path in repo_dir.rglob("tests")
            if path.is_dir()
            and not any(
                part.startswith(".") for part in path.relative_to(repo_dir).parts
            )
        ),
        key=lambda path: (len(path.relative_to(repo_dir).parts), str(path)),
    )
    return candidates[0] if candidates else repo_dir / "tests"


def _run(command: list[str], repo_dir: Path, timeout: float, env: dict) -> subprocess.CompletedProcess:
    """Run a command and kill its whole process group on timeout."""
    effective_timeout = max(0.01, timeout)
    process = subprocess.Popen(
        command,
        cwd=repo_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=effective_timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError):
            process.kill()
        stdout, _ = process.communicate()
        raise subprocess.TimeoutExpired(
            command, effective_timeout, output=stdout
        ) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout=stdout)


def run_pynguin_generation(
    repo_dir: Path,
    baseline_coverage: dict,
    *,
    version: str = "0.45.0",
    seed: int = 0,
    total_budget: int = 900,
    module_slice: int = 60,
    assertion_mode: str = "SIMPLE",
    explicit_modules: list[str] | None = None,
    setup_command: str | None = None,
    warning_filters: list[str] | None = None,
    ignore_noncallable_signatures: bool = False,
    base_environment: dict[str, str] | None = None,
) -> dict:
    """Install and schedule Pynguin under one end-to-end deadline."""
    started = time.monotonic()
    deadline = started + total_budget
    finalization_reserve = min(10.0, max(1.0, total_budget * 0.1))
    env = {
        **(base_environment or os.environ),
        "PYTHONHASHSEED": str(seed),
        # Pynguin refuses to execute the subject under test unless callers
        # explicitly acknowledge that generated inputs may invoke unsafe code.
        "PYNGUIN_DANGER_AWARE": "1",
    }
    attempts: list[dict] = []
    successful: list[str] = []
    output_chunks: list[str] = []
    rewritten_import_count = 0
    removed_nonportable_assertion_count = 0
    removed_strict_xfail_test_count = 0
    removed_failing_test_count = 0
    rejected_mismatched_module_count = 0
    network_guard_injected_count = 0
    validation_runs = 0
    validation_exit_code: int | None = None
    validation_timed_out = False
    validation_output_tail = ""
    exported_test_files: list[Path] = []
    test_dir = conventional_test_directory(repo_dir)
    scratch = repo_dir / ".pynguin-generation"
    compatibility_dir = repo_dir / ".pynguin-compatibility"

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    def generation_remaining() -> float:
        return max(0.0, remaining() - finalization_reserve)

    def _result(status: str, exit_code: int | None, patch: str = "") -> dict:
        return {
            "model_name_or_path": "pynguin",
            "model_patch": patch,
            "error": "" if status == "success" else status,
            "metrics": {
                "method": "pynguin",
                "version": version,
                "seed": seed,
                "algorithm": "DYNAMOSA",
                "assertion_mode": assertion_mode,
                "total_budget_seconds": total_budget,
                "module_slice_seconds": module_slice,
                "attempted_modules": [item["module"] for item in attempts],
                "successful_modules": successful,
                "module_attempts": attempts,
                "exit_code": exit_code,
                "wall_time_seconds": round(time.monotonic() - started, 6),
                "timed_out": (
                    status == "timeout"
                    or generation_remaining() <= 0
                    or any(item.get("timed_out") for item in attempts)
                ),
                "test_directory": str(test_dir.relative_to(repo_dir)),
                "postprocessing_version": PYNGUIN_POSTPROCESSING_VERSION,
                "rewritten_import_count": rewritten_import_count,
                "removed_nonportable_assertion_count": (
                    removed_nonportable_assertion_count
                ),
                "removed_strict_xfail_test_count": (
                    removed_strict_xfail_test_count
                ),
                "removed_failing_test_count": removed_failing_test_count,
                "rejected_mismatched_module_count": (
                    rejected_mismatched_module_count
                ),
                "network_guard_injected_count": network_guard_injected_count,
                "validation_runs": validation_runs,
                "validation_exit_code": validation_exit_code,
                "validation_timed_out": validation_timed_out,
                "validation_output_tail": validation_output_tail,
                "warning_filters": warning_filters or [],
                "ignore_noncallable_signatures": ignore_noncallable_signatures,
                "diagnostic_output_tail": "".join(output_chunks)[-8000:],
            },
        }

    try:
        # Install the generator first so its pytest<9 constraint is established
        # before repository setup commands that request an otherwise unbounded
        # pytest. This also avoids trying to downgrade a concurrently modified
        # shared environment.
        install = _run(
            ["python", "-m", "pip", "install", "--disable-pip-version-check", f"pynguin=={version}"],
            repo_dir, remaining(), env,
        )
        output_chunks.append(install.stdout or "")
        if install.returncode:
            return _result("installation_failed", install.returncode)
        if setup_command:
            setup = _run(["/bin/bash", "-c", setup_command], repo_dir, remaining(), env)
            output_chunks.append(setup.stdout or "")
            if setup.returncode:
                return _result("setup_failed", setup.returncode)
        version_check = _run(
            ["python", "-c", "import importlib.metadata; print(importlib.metadata.version('pynguin'))"],
            repo_dir, remaining(), env,
        )
        output_chunks.append(version_check.stdout or "")
        if version_check.returncode:
            return _result("import_failed", version_check.returncode)

        generation_env = env
        if ignore_noncallable_signatures:
            compatibility_dir.mkdir()
            (compatibility_dir / "sitecustomize.py").write_text(
                _NONCALLABLE_SIGNATURE_COMPAT_SOURCE
            )
            existing_pythonpath = env.get("PYTHONPATH", "")
            generation_env = {
                **env,
                "PYTHONPATH": str(compatibility_dir)
                + (os.pathsep + existing_pythonpath if existing_pythonpath else ""),
            }

        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        for attempt_index, (module, path) in enumerate(
            rank_pynguin_modules(baseline_coverage, explicit_modules)
        ):
            if generation_remaining() <= 0:
                break
            import_check = _run(
                ["python", "-c", f"import {module}"], repo_dir,
                min(generation_remaining(), 30), generation_env,
            )
            if import_check.returncode:
                attempts.append({"module": module, "path": path, "exit_code": import_check.returncode,
                                 "status": "not_importable"})
                continue
            module_scratch = scratch / (
                f"{attempt_index:04d}-"
                + re.sub(r"[^A-Za-z0-9_.-]", "_", module)
            )
            module_scratch.mkdir()
            slice_seconds = max(1, min(module_slice, int(generation_remaining())))
            command = [
                "python", "-m", "pynguin", "--project-path", str(repo_dir),
                "--module-name", module, "--output-path", str(module_scratch),
                "--algorithm", "DYNAMOSA", "--assertion-generation", assertion_mode,
                "--seed", str(seed), "--maximum-search-time", str(slice_seconds),
            ]
            module_started = time.monotonic()
            try:
                # Pynguin's internal search timer does not cover every analysis,
                # assertion-generation, and shutdown path. Enforce the advertised
                # per-module slice externally, with a small finalization grace.
                outer_slice_timeout = min(
                    generation_remaining(),
                    slice_seconds + PYNGUIN_MODULE_SHUTDOWN_GRACE_SECONDS,
                )
                completed = _run(command, repo_dir, outer_slice_timeout, generation_env)
                code, timed_out = completed.returncode, False
                module_output = completed.stdout or ""
                output_chunks.append(module_output)
            except subprocess.TimeoutExpired as exc:
                code, timed_out = None, True
                raw = exc.stdout or ""
                module_output = raw if isinstance(raw, str) else raw.decode(errors="replace")
                output_chunks.append(module_output)
            generated = sorted(module_scratch.rglob("test_*.py"))
            attempt_rewritten_imports = 0
            attempt_removed_assertions = 0
            attempt_removed_strict_xfails = 0
            attempt_network_guards = 0
            attempt_rejected_mismatches = 0
            attempt_accepted_files = 0
            for index, source in enumerate(generated):
                raw_source = source.read_text()
                if not _imports_scheduled_module(raw_source, module):
                    attempt_rejected_mismatches += 1
                    continue
                test_dir.mkdir(parents=True, exist_ok=True)
                stem = "test_pynguin_" + module.replace(".", "_")
                suffix = f"_{index + 1}" if len(generated) > 1 else ""
                destination = test_dir / f"{stem}{suffix}.py"
                sanitized, sanitation = sanitize_pynguin_test(
                    raw_source, repo_dir, warning_filters
                )
                attempt_rewritten_imports += sanitation["rewritten_import_count"]
                attempt_removed_assertions += sanitation[
                    "removed_nonportable_assertion_count"
                ]
                attempt_removed_strict_xfails += sanitation[
                    "removed_strict_xfail_test_count"
                ]
                attempt_network_guards += sanitation["network_guard_injected_count"]
                if not _contains_test_function(sanitized):
                    continue
                destination.write_text(sanitized)
                exported_test_files.append(destination)
                attempt_accepted_files += 1
            rewritten_import_count += attempt_rewritten_imports
            removed_nonportable_assertion_count += attempt_removed_assertions
            removed_strict_xfail_test_count += attempt_removed_strict_xfails
            rejected_mismatched_module_count += attempt_rejected_mismatches
            network_guard_injected_count += attempt_network_guards
            accepted_files = attempt_accepted_files
            if accepted_files:
                successful.append(module)
            attempts.append({
                "module": module, "path": path, "exit_code": code,
                "timed_out": timed_out, "generated_files": len(generated),
                "runtime_seconds": round(time.monotonic() - module_started, 6),
                "status": "generated" if accepted_files else "no_tests_generated",
                "rewritten_import_count": attempt_rewritten_imports,
                "removed_nonportable_assertion_count": attempt_removed_assertions,
                "removed_strict_xfail_test_count": attempt_removed_strict_xfails,
                "rejected_mismatched_module_count": attempt_rejected_mismatches,
                "network_guard_injected_count": attempt_network_guards,
                "output_tail": module_output[-2000:] if code else "",
            })
        # Validate exported tests under the repository's own pytest settings.
        # Remove only explicitly failed test functions; collection/tool failures
        # remain visible to the independent evaluator instead of being hidden.
        for _ in range(3):
            current_files = sorted(path for path in exported_test_files if path.exists())
            if not current_files or remaining() <= 1:
                break
            validation_runs += 1
            try:
                validation = _run(
                    [
                        "python", "-m", "pytest", "-q", "--tb=short", "--color=no",
                        *[str(path.relative_to(repo_dir)) for path in current_files],
                    ],
                    repo_dir,
                    min(remaining() - 0.5, max(1.0, finalization_reserve / 2)),
                    env,
                )
            except subprocess.TimeoutExpired as exc:
                validation_timed_out = True
                raw = exc.stdout or ""
                validation_output = (
                    raw if isinstance(raw, str) else raw.decode(errors="replace")
                )
                validation_output_tail = validation_output[-8000:]
                output_chunks.append(validation_output)
                break
            validation_exit_code = validation.returncode
            validation_output = validation.stdout or ""
            validation_output_tail = validation_output[-8000:]
            output_chunks.append(validation_output)
            if validation.returncode == 0:
                break
            pruned = prune_failing_pynguin_tests(
                current_files, repo_dir, validation_output
            )
            removed_failing_test_count += pruned
            if not pruned:
                break

        # Finalization must not discard tests already copied from completed
        # modules merely because the search phase consumed its deadline.
        finalize_timeout = max(1.0, finalization_reserve / 2)
        _run(
            ["git", "add", "-N", str(test_dir.relative_to(repo_dir))],
            repo_dir, finalize_timeout, env,
        )
        diff = _run(
            ["git", "diff", "--", str(test_dir.relative_to(repo_dir))],
            repo_dir, finalize_timeout, env,
        )
        patch = diff.stdout or ""
        return _result("success" if patch else "no_tests_generated", 0, patch)
    except subprocess.TimeoutExpired:
        return _result("timeout", None)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(compatibility_dir, ignore_errors=True)


def generate_pynguin_prediction(
    instance: dict,
    baseline_coverage: dict,
    out_dir: Path,
    github_token: str | None = None,
    **options,
) -> dict:
    """Generate the standard prediction contract in a clean fixed-commit clone."""
    from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
    from swebench.eval_pipeline.host_environment import isolated_python_environment

    out_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = None
    try:
        repo_dir = _clone_repo_at_commit(
            instance.get("repo_url") or instance["repo"], instance["base_commit"],
            github_token, tmp_root=out_dir / "worktrees",
        )
        with isolated_python_environment(out_dir / "environments") as environment:
            prediction = run_pynguin_generation(
                repo_dir,
                baseline_coverage,
                setup_command=instance.get("coverage_setup_command"),
                base_environment=environment,
                **options,
            )
    except Exception as exc:
        prediction = {
            "model_name_or_path": "pynguin", "model_patch": "",
            "error": "generation_exception",
            "metrics": {"method": "pynguin", "error": f"{type(exc).__name__}: {exc}"},
        }
    finally:
        if repo_dir:
            shutil.rmtree(repo_dir, ignore_errors=True)
    prediction["instance_id"] = instance["instance_id"]
    (out_dir / "prediction.json").write_text(__import__("json").dumps(prediction, indent=2))
    return prediction
