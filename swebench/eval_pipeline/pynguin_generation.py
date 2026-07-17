"""Repository-level scheduler for the single-module Pynguin CLI."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path


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
        path for path in repo_dir.rglob("tests")
        if path.is_dir()
        and not any(part.startswith(".") for part in path.relative_to(repo_dir).parts)
    )
    return candidates[0] if candidates else repo_dir / "tests"


def _run(command: list[str], repo_dir: Path, timeout: float, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=repo_dir, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=max(0.01, timeout),
    )


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
) -> dict:
    """Install and schedule Pynguin under one end-to-end deadline."""
    started = time.monotonic()
    deadline = started + total_budget
    env = {
        **os.environ,
        "PYTHONHASHSEED": str(seed),
        # Pynguin refuses to execute the subject under test unless callers
        # explicitly acknowledge that generated inputs may invoke unsafe code.
        "PYNGUIN_DANGER_AWARE": "1",
    }
    attempts: list[dict] = []
    successful: list[str] = []
    output_chunks: list[str] = []
    test_dir = conventional_test_directory(repo_dir)
    scratch = repo_dir / ".pynguin-generation"

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

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
                "timed_out": status == "timeout" or remaining() <= 0,
                "test_directory": str(test_dir.relative_to(repo_dir)),
                "diagnostic_output_tail": "".join(output_chunks)[-8000:],
            },
        }

    try:
        if setup_command:
            setup = _run(["/bin/bash", "-c", setup_command], repo_dir, remaining(), env)
            output_chunks.append(setup.stdout or "")
            if setup.returncode:
                return _result("setup_failed", setup.returncode)
        install = _run(
            ["python", "-m", "pip", "install", "--disable-pip-version-check", f"pynguin=={version}"],
            repo_dir, remaining(), env,
        )
        output_chunks.append(install.stdout or "")
        if install.returncode:
            return _result("installation_failed", install.returncode)
        version_check = _run(
            ["python", "-c", "import importlib.metadata; print(importlib.metadata.version('pynguin'))"],
            repo_dir, remaining(), env,
        )
        output_chunks.append(version_check.stdout or "")
        if version_check.returncode:
            return _result("import_failed", version_check.returncode)

        for module, path in rank_pynguin_modules(baseline_coverage, explicit_modules):
            if remaining() <= 0:
                break
            import_check = _run(
                ["python", "-c", f"import {module}"], repo_dir,
                min(remaining(), 30), env,
            )
            if import_check.returncode:
                attempts.append({"module": module, "path": path, "exit_code": import_check.returncode,
                                 "status": "not_importable"})
                continue
            shutil.rmtree(scratch, ignore_errors=True)
            scratch.mkdir(parents=True)
            slice_seconds = max(1, min(module_slice, int(remaining())))
            command = [
                "python", "-m", "pynguin", "--project-path", str(repo_dir),
                "--module-name", module, "--output-path", str(scratch),
                "--algorithm", "DYNAMOSA", "--assertion-generation", assertion_mode,
                "--seed", str(seed), "--maximum-search-time", str(slice_seconds),
            ]
            module_started = time.monotonic()
            try:
                completed = _run(command, repo_dir, remaining(), env)
                code, timed_out = completed.returncode, False
                module_output = completed.stdout or ""
                output_chunks.append(module_output)
            except subprocess.TimeoutExpired as exc:
                code, timed_out = None, True
                raw = exc.stdout or ""
                module_output = raw if isinstance(raw, str) else raw.decode(errors="replace")
                output_chunks.append(module_output)
            generated = sorted(scratch.rglob("test_*.py"))
            for index, source in enumerate(generated):
                test_dir.mkdir(parents=True, exist_ok=True)
                stem = "test_pynguin_" + module.replace(".", "_")
                suffix = f"_{index + 1}" if len(generated) > 1 else ""
                destination = test_dir / f"{stem}{suffix}.py"
                destination.write_text(source.read_text())
            if generated:
                successful.append(module)
            attempts.append({
                "module": module, "path": path, "exit_code": code,
                "timed_out": timed_out, "generated_files": len(generated),
                "runtime_seconds": round(time.monotonic() - module_started, 6),
                "status": "generated" if generated else "no_tests_generated",
                "output_tail": module_output[-2000:] if code else "",
            })
        _run(["git", "add", "-N", str(test_dir.relative_to(repo_dir))], repo_dir, min(remaining(), 10), env)
        diff = _run(["git", "diff", "--", str(test_dir.relative_to(repo_dir))], repo_dir, min(remaining(), 10), env)
        patch = diff.stdout or ""
        return _result("success" if patch else "no_tests_generated", 0, patch)
    except subprocess.TimeoutExpired:
        return _result("timeout", None)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def generate_pynguin_prediction(
    instance: dict,
    baseline_coverage: dict,
    out_dir: Path,
    github_token: str | None = None,
    **options,
) -> dict:
    """Generate the standard prediction contract in a clean fixed-commit clone."""
    from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit

    out_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = None
    try:
        repo_dir = _clone_repo_at_commit(
            instance.get("repo_url") or instance["repo"], instance["base_commit"],
            github_token, tmp_root=out_dir / "worktrees",
        )
        prediction = run_pynguin_generation(
            repo_dir, baseline_coverage,
            setup_command=instance.get("coverage_setup_command"), **options,
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
