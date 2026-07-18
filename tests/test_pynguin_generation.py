import csv
import subprocess
import sys
from pathlib import Path

from swebench.eval_pipeline.coverage_generation_eval import common_improved_modules
from swebench.eval_pipeline.pynguin_generation import (
    conventional_test_directory,
    module_name_from_path,
    rank_pynguin_modules,
    run_pynguin_generation,
)
from swebench.eval_pipeline.report import render_coverage_comparison_table
from swebench.eval_pipeline.run_pipeline import (
    _retain_cached_pynguin_prediction,
    _reuse_cached_pynguin_prediction,
    parse_args,
)


def test_pynguin_cli_defaults_and_overrides(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline"])
    defaults = parse_args()
    assert defaults.traditional_test_generator is None
    assert defaults.pynguin_version == "0.45.0"
    assert defaults.pynguin_seed == 0
    assert defaults.pynguin_total_budget == 900
    assert defaults.pynguin_module_slice == 60
    assert defaults.pynguin_assertion_mode == "SIMPLE"
    assert defaults.skip_pynguin is False
    assert defaults.force_pynguin is False

    monkeypatch.setattr(sys, "argv", [
        "run_pipeline", "--traditional_test_generator", "pynguin",
        "--pynguin_seed", "7", "--pynguin_module", "pkg.core",
        "--skip_pynguin", "--force_pynguin",
    ])
    overridden = parse_args()
    assert overridden.traditional_test_generator == "pynguin"
    assert overridden.pynguin_seed == 7
    assert overridden.pynguin_module == ["pkg.core"]
    assert overridden.skip_pynguin is True
    assert overridden.force_pynguin is True


def test_force_pynguin_cache_precedence(monkeypatch):
    def options(*flags):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", *flags])
        return parse_args()

    assert _reuse_cached_pynguin_prediction(options()) is True
    assert _reuse_cached_pynguin_prediction(options("--force_pynguin")) is False
    assert _reuse_cached_pynguin_prediction(options("--force_inference")) is False
    assert _reuse_cached_pynguin_prediction(
        options("--force_pynguin", "--force_inference", "--skip_pynguin")
    ) is True


def test_failed_pynguin_regeneration_retains_nonempty_cache():
    cached = {
        "model_patch": "diff --git a/tests/test_old.py b/tests/test_old.py\n",
        "error": "",
        "metrics": {"version": "0.45.0"},
    }
    generated = {
        "model_patch": "",
        "error": "timeout",
        "metrics": {
            "wall_time_seconds": 900.1,
            "timed_out": True,
            "attempted_modules": ["pkg.a"],
            "successful_modules": ["pkg.a"],
        },
    }
    retained = _retain_cached_pynguin_prediction(cached, generated)
    assert retained["model_patch"] == cached["model_patch"]
    assert retained["metrics"]["last_regeneration_failure"] == {
        "error": "timeout",
        "wall_time_seconds": 900.1,
        "timed_out": True,
        "attempted_module_count": 1,
        "successful_modules": ["pkg.a"],
    }
    assert "last_regeneration_failure" not in cached["metrics"]
    assert _retain_cached_pynguin_prediction(cached, {**generated, "model_patch": "new"})[
        "model_patch"
    ] == "new"


def test_module_resolution_and_uncovered_ranking_are_deterministic():
    assert module_name_from_path("src/pkg/core.py") == "pkg.core"
    assert module_name_from_path("Bio/Align/__init__.py") == "Bio.Align"
    coverage = {"files": {
        "src/pkg/a.py": {
            "covered_lines": 5, "num_statements": 10,
            "covered_branches": 0, "num_branches": 2,
        },
        "src/pkg/b.py": {
            "covered_lines": 0, "num_statements": 20,
            "covered_branches": 0, "num_branches": 1,
        },
        "src/pkg/full.py": {
            "covered_lines": 1, "num_statements": 1,
            "covered_branches": 0, "num_branches": 0,
        },
    }}
    assert rank_pynguin_modules(coverage) == [
        ("pkg.a", "src/pkg/a.py"), ("pkg.b", "src/pkg/b.py")
    ]
    assert rank_pynguin_modules(coverage, ["pkg.b"]) == [
        ("pkg.b", "src/pkg/b.py")
    ]
    assert rank_pynguin_modules(coverage, ["pkg.explicit"]) == [
        ("pkg.explicit", "")
    ]


def test_test_directory_selection_including_biopython(tmp_path):
    (tmp_path / "Tests").mkdir()
    assert conventional_test_directory(tmp_path) == tmp_path / "Tests"


def test_common_mutation_union_and_no_gain_case():
    baseline = {"files": {
        "pkg/a.py": {"covered_lines": 1, "covered_branches": 0},
        "pkg/b.py": {"covered_lines": 1, "covered_branches": 0},
    }}
    arms = [
        {"coverage_after": {"files": {
            "pkg/a.py": {"covered_lines": 2, "covered_branches": 0},
            "pkg/b.py": {"covered_lines": 1, "covered_branches": 0},
        }}},
        {"coverage_after": {"files": {
            "pkg/a.py": {"covered_lines": 1, "covered_branches": 0},
            "pkg/b.py": {"covered_lines": 1, "covered_branches": 1},
        }}},
    ]
    assert common_improved_modules(baseline, arms) == ["pkg/a.py", "pkg/b.py"]
    assert common_improved_modules(baseline, []) == []
    assert common_improved_modules(baseline, [], ["pkg/fixed.py"]) == ["pkg/fixed.py"]


def test_comparison_csv_has_one_row_per_arm(tmp_path):
    output = tmp_path / "comparison.csv"
    targets = ["pkg/a.py"]
    rows = [
        {"method": method, "status": "resolved", "mutation_targets": targets,
         "coverage_after": {"line_coverage": 50.0, "branch_coverage": 25.0}}
        for method in ("original", "pynguin", "agent")
    ]
    render_coverage_comparison_table(rows, str(output))
    with output.open(newline="") as handle:
        saved = list(csv.DictReader(handle))
    assert [row["method"] for row in saved] == ["original", "pynguin", "agent"]
    assert {row["mutation_targets"] for row in saved} == {"pkg/a.py"}


def test_scheduler_applies_seed_slice_and_emits_patch(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    calls = []

    def fake_run(command, repo_dir, timeout, env):
        calls.append((command, timeout, env.copy()))
        if command[:3] == ["python", "-m", "pynguin"]:
            output = Path(command[command.index("--output-path") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "test_generated.py").write_text("def test_x():\n    assert 1\n")
        stdout = (
            "diff --git a/tests/test_pynguin_pkg_core.py b/tests/test_pynguin_pkg_core.py\n"
            if command[:2] == ["git", "diff"] else ""
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 2,
            "covered_branches": 0, "num_branches": 1,
        }}},
        seed=11, total_budget=20, module_slice=7,
    )
    pynguin_call = next(call for call in calls if call[0][:3] == ["python", "-m", "pynguin"])
    assert pynguin_call[2]["PYTHONHASHSEED"] == "11"
    assert pynguin_call[2]["PYNGUIN_DANGER_AWARE"] == "1"
    assert pynguin_call[0][pynguin_call[0].index("--maximum-search-time") + 1] == "7"
    assert result["model_patch"].startswith("diff --git")
    assert result["metrics"]["successful_modules"] == ["pkg.core"]
    assert result["metrics"]["module_attempts"][0]["exit_code"] == 0
    finalization_calls = [call for call in calls if call[0][:2] == ["git", "add"]]
    assert finalization_calls[0][1] >= 1


def test_scheduler_collects_tests_after_module_timeout(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            output = Path(command[command.index("--output-path") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "test_generated.py").write_text("def test_x():\n    assert 1\n")
            raise subprocess.TimeoutExpired(command, timeout, output="partial output")
        stdout = (
            "diff --git a/tests/test_pynguin_pkg_core.py "
            "b/tests/test_pynguin_pkg_core.py\n"
            if command[:2] == ["git", "diff"] else ""
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 1,
            "covered_branches": 0, "num_branches": 0,
        }}},
        total_budget=10,
    )
    assert result["model_patch"].startswith("diff --git")
    assert result["metrics"]["successful_modules"] == ["pkg.core"]
    assert result["metrics"]["module_attempts"][0]["timed_out"] is True
    assert result["metrics"]["timed_out"] is True


def test_scheduler_reports_install_failure(tmp_path, monkeypatch):
    def fake_run(command, repo_dir, timeout, env):
        return subprocess.CompletedProcess(command, 2, stdout="offline")

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(tmp_path, {"files": {}}, total_budget=10)
    assert result["error"] == "installation_failed"
    assert result["metrics"]["exit_code"] == 2
    assert result["metrics"]["diagnostic_output_tail"] == "offline"


def test_scheduler_preserves_failed_module_diagnostics(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            return subprocess.CompletedProcess(command, 255, stdout="missing acknowledgement")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 1,
            "covered_branches": 0, "num_branches": 0,
        }}},
        total_budget=10,
    )
    attempt = result["metrics"]["module_attempts"][0]
    assert attempt["exit_code"] == 255
    assert attempt["output_tail"] == "missing acknowledgement"
