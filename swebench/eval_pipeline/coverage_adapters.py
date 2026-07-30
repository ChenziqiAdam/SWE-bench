"""Language-specific policy for standalone coverage-generation experiments."""
from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

CPP_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
IGNORED_SOURCE_PARTS = {
    ".git", "_deps", "build", "cmake-build-debug", "cmake-build-release",
    "external", "extern", "third_party", "third-party", "vendor", "vendored",
}
COVERAGE_GIT_EXCLUDES = [
    ":(exclude)build",
    ":(exclude)build/**",
    ":(exclude)cmake-build-*",
    ":(exclude)cmake-build-*/**",
]


def strip_cpp_coverage_artifacts(patch: str) -> str:
    """Remove generated build/helper diff blocks from a captured C++ patch."""
    blocks = []
    current: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    kept = []
    for block in blocks:
        header = block[0]
        path = header.split(" b/", 1)[-1].strip()
        if (
            path == ".git/coverage-runner"
            or path == "build"
            or path.startswith("build/")
            or path.startswith("cmake-build-")
        ):
            continue
        kept.extend(block)
    return "".join(kept)


def is_cpp_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    candidate = Path(normalized)
    if candidate.suffix.lower() not in CPP_EXTENSIONS:
        return False
    parts = [part.lower() for part in candidate.parts[:-1]]
    name = candidate.name.lower()
    return (
        any(part in {"test", "tests", "testing", "unittest", "unittests"} for part in parts)
        or name.startswith("test_")
        or candidate.name.startswith("Test")
        or name.endswith(("_test.c", "_test.cc", "_test.cpp", "_test.cxx"))
    )


def is_test_local_cmake(path: str) -> bool:
    candidate = Path(path.replace("\\", "/").lstrip("./"))
    return (
        candidate.name == "CMakeLists.txt"
        and any(
            part.lower() in {"test", "tests", "testing", "unittest", "unittests"}
            for part in candidate.parts[:-1]
        )
    )


def detect_coverage_language(repo_dir: str | Path, profile_language: str | None = None) -> str:
    """Detect an unambiguous Python or CMake/C++ repository."""
    if profile_language:
        return profile_language
    root = Path(repo_dir)
    has_cmake = (root / "CMakeLists.txt").is_file()
    has_cpp = any(
        path.suffix.lower() in CPP_EXTENSIONS
        for path in root.rglob("*")
        if not any(part.lower() in IGNORED_SOURCE_PARTS for part in path.parts)
    )
    has_python = any(
        path.suffix == ".py"
        for path in root.rglob("*.py")
        if not any(part.lower() in IGNORED_SOURCE_PARTS for part in path.parts)
    )
    cpp = has_cmake and has_cpp
    if cpp and has_python:
        raise ValueError(
            "mixed Python and CMake/C++ repository; pass --coverage_language explicitly"
        )
    if cpp:
        return "cpp"
    if has_python:
        return "python"
    raise ValueError(
        "could not detect a supported coverage language; pass "
        "--coverage_language {python,cpp}"
    )


def discover_cpp_sources(
    repo_dir: str | Path, source_roots: list[str] | None = None
) -> list[str]:
    root = Path(repo_dir).resolve()
    search_roots = [root / item for item in source_roots] if source_roots else [root]
    discovered = []
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in CPP_EXTENSIONS:
                continue
            relative = path.resolve().relative_to(root)
            normalized_parts = {part.lower() for part in relative.parts}
            if normalized_parts & IGNORED_SOURCE_PARTS or is_cpp_test_path(relative.as_posix()):
                continue
            discovered.append(relative.as_posix())
    return sorted(set(discovered))


def parse_gcovr_json(payload: str, targets: list[str] | None = None) -> dict | None:
    """Normalize gcovr 8 JSON-summary output to the coverage.py result schema."""
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return None
    normalized_targets = [
        path.replace("\\", "/").lstrip("./") for path in (targets or [])
    ]
    selected = []
    for item in data["files"]:
        path = str(item.get("filename") or item.get("file") or "").replace("\\", "/")
        path = path.lstrip("./")
        if not path or is_cpp_test_path(path):
            continue
        if normalized_targets and not any(
            path == target or path.endswith("/" + target) for target in normalized_targets
        ):
            continue
        if not normalized_targets and (
            Path(path).suffix.lower() not in CPP_EXTENSIONS
            or {part.lower() for part in Path(path).parts} & IGNORED_SOURCE_PARTS
        ):
            continue
        selected.append((path, item))
    if not selected:
        return None

    def count(info: dict, singular: str) -> tuple[int, int]:
        total = int(info.get(f"{singular}_total", 0) or 0)
        covered = int(info.get(f"{singular}_covered", 0) or 0)
        return covered, total

    summaries = {}
    for path, info in selected:
        covered_lines, statements = count(info, "line")
        covered_branches, branches = count(info, "branch")
        summaries[path] = {
            "line_coverage": 100.0 * covered_lines / statements if statements else 100.0,
            "branch_coverage": (
                100.0 * covered_branches / branches if branches else 100.0
            ),
            "covered_lines": covered_lines,
            "num_statements": statements,
            "covered_branches": covered_branches,
            "num_branches": branches,
        }
    statements = sum(item["num_statements"] for item in summaries.values())
    covered_lines = sum(item["covered_lines"] for item in summaries.values())
    branches = sum(item["num_branches"] for item in summaries.values())
    covered_branches = sum(item["covered_branches"] for item in summaries.values())
    return {
        "target_file_count": len(summaries),
        "scope": "targeted" if normalized_targets else "repository",
        "line_coverage": 100.0 * covered_lines / statements if statements else 100.0,
        "branch_coverage": 100.0 * covered_branches / branches if branches else 100.0,
        "covered_lines": covered_lines,
        "num_statements": statements,
        "covered_branches": covered_branches,
        "num_branches": branches,
        "files": summaries,
    }


@dataclass(frozen=True)
class CoverageCommands:
    setup: str
    test: str
    reset: str
    run: str
    report: str


def default_commands(language: str, source_roots: list[str] | None = None) -> CoverageCommands:
    if language == "python":
        return CoverageCommands(
            "python -m pip install -e . pytest",
            "python -m pytest",
            "python -m coverage erase",
            "python -m coverage run --branch --source=. -m pytest",
            "python -m coverage json -o {output}",
        )
    if language != "cpp":
        raise ValueError(f"unsupported coverage language: {language}")
    roots = source_roots or ["."]
    root_args = " ".join(f"--filter {root}" for root in roots)
    return CoverageCommands(
        "cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug "
        "-DBUILD_TESTING=ON -DCMAKE_C_FLAGS=--coverage "
        "-DCMAKE_CXX_FLAGS=--coverage -DCMAKE_EXE_LINKER_FLAGS=--coverage "
        "&& cmake --build build",
        "ctest --test-dir build --output-on-failure",
        "find build -name '*.gcda' -delete",
        "ctest --test-dir build --output-on-failure",
        f"gcovr --root . {root_args} --json-summary {{output}}",
    )


def install_coverage_runner(repo_dir: str | Path, instance: dict) -> Path | None:
    """Install the untracked agent-facing C++ build/test/coverage helper."""
    if instance.get("coverage_language") != "cpp":
        return None
    root = Path(repo_dir)
    helper = root / ".git" / "coverage-runner"
    setup = instance.get("coverage_setup_command") or default_commands("cpp").setup
    tests = instance.get("coverage_test_command") or default_commands("cpp").test
    reset = instance.get("coverage_reset_command") or default_commands("cpp").reset
    coverage = instance.get("coverage_command") or tests
    report = instance.get("coverage_results_command") or default_commands("cpp").report
    config = helper.with_name("coverage-runner.json")
    config.write_text(json.dumps({
        "image": instance["coverage_container_image"],
        "timeout": int(instance.get("coverage_phase_timeout") or 14400),
        "setup": setup,
        "test": tests,
        "reset": reset,
        "coverage": coverage,
        "report": report.replace(
            "{output}", ".git/coverage-summary.json"
        ),
    }, indent=2))
    runner_python = shlex.quote(sys.executable)
    runner_config = shlex.quote(str(config))
    script = "\n".join([
        "#!/bin/bash",
        "set -euo pipefail",
        'cd "$(git rev-parse --show-toplevel)"',
        f"exec {runner_python} -m swebench.eval_pipeline.cpp_coverage_runner "
        f"--config {runner_config} \"$@\"",
        "",
    ])
    helper.write_text(script)
    os.chmod(helper, 0o755)
    return helper
