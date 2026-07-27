import csv
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from swebench.eval_pipeline.coverage_generation_eval import (
    apply_target_importability_results,
    common_improved_modules,
    freeze_agent_selected_targets,
)
from swebench.eval_pipeline.pynguin_generation import (
    _GENERATION_NETWORK_GUARD_SOURCE,
    _NONCALLABLE_SIGNATURE_COMPAT_SOURCE,
    _run,
    conventional_test_directory,
    module_name_from_path,
    prune_failing_pynguin_tests,
    rank_pynguin_modules,
    run_pynguin_generation,
    sanitize_pynguin_test,
)
from swebench.eval_pipeline.report import render_coverage_comparison_table
from swebench.eval_pipeline.run_pipeline import (
    _matching_cached_pynguin_prediction,
    _retain_cached_pynguin_prediction,
    _reuse_cached_pynguin_prediction,
    _upsert_prediction_by_instance,
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
    assert defaults.pynguin_module_finalization_grace == 30
    assert defaults.pynguin_test_execution_timeout == 1
    assert defaults.pynguin_force_subprocess is False
    assert defaults.pynguin_verbose is False
    assert defaults.pynguin_assertion_mode == "SIMPLE"
    assert defaults.skip_pynguin is False
    assert defaults.force_pynguin is False

    monkeypatch.setattr(sys, "argv", [
        "run_pipeline", "--traditional_test_generator", "pynguin",
        "--pynguin_seed", "7", "--pynguin_module", "pkg.core",
        "--pynguin_module_finalization_grace", "30",
        "--pynguin_test_execution_timeout", "2",
        "--pynguin_force_subprocess",
        "--pynguin_verbose",
        "--skip_pynguin", "--force_pynguin",
    ])
    overridden = parse_args()
    assert overridden.traditional_test_generator == "pynguin"
    assert overridden.pynguin_seed == 7
    assert overridden.pynguin_module == ["pkg.core"]
    assert overridden.pynguin_module_finalization_grace == 30
    assert overridden.pynguin_test_execution_timeout == 2
    assert overridden.pynguin_force_subprocess is True
    assert overridden.pynguin_verbose is True
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


def test_pynguin_cache_is_matched_and_replaced_by_instance(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline"])
    args = parse_args()
    matching_metrics = {
        "version": args.pynguin_version,
        "seed": args.pynguin_seed,
        "total_budget_seconds": args.pynguin_total_budget,
        "module_slice_seconds": args.pynguin_module_slice,
        "module_finalization_grace_seconds": (
            args.pynguin_module_finalization_grace
        ),
        "test_execution_timeout_seconds": args.pynguin_test_execution_timeout,
        "force_subprocess": args.pynguin_force_subprocess,
        "verbose": args.pynguin_verbose,
        "assertion_mode": args.pynguin_assertion_mode,
        "postprocessing_version": 11,
    }
    rows = [
        {"instance_id": "repo-a", "model_patch": "a", "metrics": matching_metrics},
        {"instance_id": "repo-b", "model_patch": "b", "metrics": matching_metrics},
    ]
    assert _matching_cached_pynguin_prediction(rows, "repo-b", args)[
        "model_patch"
    ] == "b"
    assert _matching_cached_pynguin_prediction(rows, "repo-c", args) is None
    replaced = _upsert_prediction_by_instance(
        rows, {"instance_id": "repo-a", "model_patch": "new-a"}
    )
    assert [(row["instance_id"], row["model_patch"]) for row in replaced] == [
        ("repo-b", "b"),
        ("repo-a", "new-a"),
    ]


def test_shared_target_cache_fingerprints_modules_python_budget_and_setup(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "run_pipeline",
        "--comparison_protocol", "agent_led_shared_targets",
        "--shared_generation_budget", "123",
    ])
    args = parse_args()
    metrics = {
        "version": args.pynguin_version,
        "seed": args.pynguin_seed,
        "total_budget_seconds": 123,
        "module_slice_seconds": args.pynguin_module_slice,
        "module_finalization_grace_seconds": (
            args.pynguin_module_finalization_grace
        ),
        "test_execution_timeout_seconds": args.pynguin_test_execution_timeout,
        "force_subprocess": args.pynguin_force_subprocess,
        "verbose": args.pynguin_verbose,
        "assertion_mode": args.pynguin_assertion_mode,
        "postprocessing_version": 11,
        "requested_modules": ["pkg.a"],
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "budget_strategy": "equal_shared_targets",
        "setup_profile_fingerprint": "setup-a",
    }
    rows = [{"instance_id": "repo-a", "metrics": metrics}]
    assert _matching_cached_pynguin_prediction(
        rows, "repo-a", args, ["pkg.a"], "setup-a"
    )
    args.pynguin_force_subprocess = True
    assert _matching_cached_pynguin_prediction(
        rows, "repo-a", args, ["pkg.a"], "setup-a"
    ) is None
    args.pynguin_force_subprocess = False
    args.pynguin_module_finalization_grace = 10
    assert _matching_cached_pynguin_prediction(
        rows, "repo-a", args, ["pkg.a"], "setup-a"
    ) is None
    args.pynguin_module_finalization_grace = 10
    assert _matching_cached_pynguin_prediction(
        rows, "repo-a", args, ["pkg.b"], "setup-a"
    ) is None
    assert _matching_cached_pynguin_prediction(
        rows, "repo-a", args, ["pkg.a"], "setup-b"
    ) is None
    args.shared_generation_budget = 124
    assert _matching_cached_pynguin_prediction(
        rows, "repo-a", args, ["pkg.a"], "setup-a"
    ) is None


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


def test_test_directory_selection_prefers_shallow_package_tests(tmp_path):
    (tmp_path / "geopandas" / "io" / "tests").mkdir(parents=True)
    (tmp_path / "geopandas" / "tests").mkdir()
    assert conventional_test_directory(tmp_path) == tmp_path / "geopandas" / "tests"


def test_pynguin_postprocessing_repairs_shadowed_imports_and_checkout_assertions(
    tmp_path,
):
    source = (
        "import pytest\n"
        "import Bio.PDB.PDBList as module_0\n"
        "import numpy.lib.format as module_1\n\n"
        "def test_case_0():\n"
        "    value = module_0.PDBList()\n"
        f"    assert value.local_pdb == {str(tmp_path)!r}\n"
        "    assert module_1.MAGIC_LEN == 8\n"
    )
    sanitized, metrics = sanitize_pynguin_test(source, tmp_path)
    assert "module_0 = _pynguin_importlib.import_module('Bio.PDB.PDBList')" in sanitized
    assert "module_1 = _pynguin_importlib.import_module('numpy.lib.format')" in sanitized
    assert str(tmp_path) not in sanitized
    assert "assert module_1.MAGIC_LEN == 8" in sanitized
    assert metrics == {
        "rewritten_import_count": 2,
        "removed_nonportable_assertion_count": 1,
        "removed_strict_xfail_test_count": 0,
        "network_guard_injected_count": 1,
        "warning_filter_count": 0,
    }
    assert "def _pynguin_offline_network(monkeypatch):" in sanitized
    compile(sanitized, "<generated>", "exec")


def test_pynguin_postprocessing_adds_only_configured_warning_filters(tmp_path):
    sanitized, metrics = sanitize_pynguin_test(
        "def test_case_0():\n    assert True\n",
        tmp_path,
        ["ignore::astropy.utils.exceptions.AstropyDeprecationWarning"],
    )
    assert "pytestmark = [" in sanitized
    assert "astropy.utils.exceptions.AstropyDeprecationWarning" in sanitized
    assert "filterwarnings('ignore')" not in sanitized
    assert metrics["warning_filter_count"] == 1
    compile(sanitized, "<generated>", "exec")


def test_pynguin_postprocessing_removes_strict_xfail_tests(tmp_path):
    sanitized, metrics = sanitize_pynguin_test(
        "import pytest\n\n"
        "@pytest.mark.xfail(strict=True)\n"
        "def test_unstable_expected_failure():\n"
        "    raise ValueError\n\n"
        "@pytest.mark.xfail\n"
        "def test_non_strict_xfail():\n"
        "    raise ValueError\n\n"
        "def test_passes():\n"
        "    assert True\n",
        tmp_path,
    )

    assert "test_unstable_expected_failure" not in sanitized
    assert "test_non_strict_xfail" in sanitized
    assert "test_passes" in sanitized
    assert metrics["removed_strict_xfail_test_count"] == 1


def test_pynguin_network_guard_xfails_network_calls(tmp_path):
    source = (
        "import socket\n\n"
        "def test_case_0():\n"
        "    socket.getaddrinfo('example.invalid', 443)\n"
    )
    sanitized, _ = sanitize_pynguin_test(source, tmp_path)
    test_file = tmp_path / "test_generated.py"
    test_file.write_text(sanitized)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test_file)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0
    assert "1 xfailed" in completed.stdout


def test_pynguin_postprocessing_prunes_repository_pytest_failures(tmp_path):
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_generated.py"
    test_file.write_text(
        "def test_passes():\n"
        "    assert True\n\n"
        "def test_warning_error():\n"
        "    raise RuntimeWarning('promoted by project pytest config')\n"
    )

    removed = prune_failing_pynguin_tests(
        [test_file],
        tmp_path,
        "FAILED tests/test_generated.py::test_warning_error - RuntimeWarning\n",
    )

    assert removed == 1
    sanitized = test_file.read_text()
    assert "test_passes" in sanitized
    assert "test_warning_error" not in sanitized
    compile(sanitized, "<generated>", "exec")


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


def test_agent_led_targets_depend_only_on_valid_agent_coverage_gain():
    baseline = {"files": {
        "pkg/a.py": {
            "covered_lines": 1, "covered_branches": 0, "num_statements": 200,
        },
        "pkg/b.py": {
            "covered_lines": 1, "covered_branches": 0, "num_statements": 20,
        },
        "pkg/c.py": {
            "covered_lines": 0, "covered_branches": 0, "num_statements": 400,
        },
    }}
    agent = {
        "changed_files": ["tests/test_generated.py"],
        "tests_only_patch": True,
        "no_existing_test_lines_removed": True,
        "test_patch_applied": True,
        "after_tests_passed": True,
        "after_coverage_tests_passed": True,
        "flaky": False,
        "added_test_count": 999,
        "coverage_after": {"files": {
            "pkg/a.py": {"covered_lines": 3, "covered_branches": 1},
            "pkg/b.py": {"covered_lines": 3, "covered_branches": 1},
            "pkg/c.py": {"covered_lines": 1, "covered_branches": 0},
        }},
    }
    manifest = freeze_agent_selected_targets(
        baseline, agent, statement_budget=250
    )
    assert manifest["target_paths"] == ["pkg/b.py", "pkg/a.py"]
    assert manifest["import_modules"] == ["pkg.b", "pkg.a"]
    assert manifest["targets"][2]["exclusion_reason"] == "statement_budget"
    agent["added_test_count"] = 0
    assert freeze_agent_selected_targets(
        baseline, agent, statement_budget=250
    )["target_paths"] == manifest["target_paths"]


def test_agent_led_targets_reject_invalid_or_no_gain_agent():
    baseline = {"files": {
        "pkg/a.py": {
            "covered_lines": 1, "covered_branches": 0, "num_statements": 2,
        },
    }}
    invalid = {
        "changed_files": ["pkg/a.py"],
        "tests_only_patch": False,
        "no_existing_test_lines_removed": True,
        "test_patch_applied": True,
        "after_tests_passed": True,
        "after_coverage_tests_passed": True,
        "flaky": False,
        "coverage_after": {"files": {
            "pkg/a.py": {"covered_lines": 2, "covered_branches": 0},
        }},
    }
    manifest = freeze_agent_selected_targets(baseline, invalid)
    assert manifest["target_paths"] == []
    assert manifest["failure_reason"] == "invalid_agent_patch"


def test_agent_led_target_manifest_applies_pristine_import_preflight():
    manifest = {
        "valid_agent_patch": True,
        "failure_reason": "",
        "targets": [{
            "path": "pkg/a.py",
            "module": "pkg.a",
            "baseline_statements": 3,
            "selected": True,
            "exclusion_reason": "",
        }],
        "target_paths": ["pkg/a.py"],
        "import_modules": ["pkg.a"],
        "selected_statement_count": 3,
    }
    apply_target_importability_results(
        manifest, [{"module": "pkg.a", "status": "not_importable"}]
    )
    assert manifest["target_paths"] == []
    assert manifest["targets"][0]["exclusion_reason"] == "not_importable"
    assert manifest["failure_reason"] == "no_agent_selected_targets"


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
            (output / "test_generated.py").write_text(
                "import pkg.core as module_0\n\n"
                "def test_x():\n    assert 1\n"
            )
        if command[:3] == ["python", "-m", "pynguin"]:
            stdout = "pynguin completed successfully\n"
        elif command[:2] == ["git", "diff"]:
            stdout = (
                "diff --git a/tests/test_pynguin_pkg_core.py "
                "b/tests/test_pynguin_pkg_core.py\n"
            )
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 2,
            "covered_branches": 0, "num_branches": 1,
        }}},
        seed=11,
        total_budget=20,
        module_slice=7,
        force_subprocess=True,
        verbose=True,
        diagnostic_dir=tmp_path / "diagnostics",
    )
    pynguin_call = next(call for call in calls if call[0][:3] == ["python", "-m", "pynguin"])
    assert pynguin_call[2]["PYTHONHASHSEED"] == "11"
    assert pynguin_call[2]["PYNGUIN_DANGER_AWARE"] == "1"
    assert pynguin_call[0][pynguin_call[0].index("--maximum-search-time") + 1] == "7"
    assert (
        pynguin_call[0][
            pynguin_call[0].index("--maximum-test-execution-timeout") + 1
        ]
        == "1"
    )
    assert pynguin_call[0][pynguin_call[0].index("--subprocess") + 1] == "True"
    assert (
        pynguin_call[0][
            pynguin_call[0].index("--subprocess_if_recommended") + 1
        ]
        == "False"
    )
    assert "-v" in pynguin_call[0]
    assert pynguin_call[1] <= 20
    assert result["model_patch"].startswith("diff --git")
    assert result["metrics"]["successful_modules"] == ["pkg.core"]
    assert result["metrics"]["module_finalization_grace_seconds"] == 30
    assert result["metrics"]["force_subprocess"] is True
    assert result["metrics"]["verbose"] is True
    diagnostic_log = Path(
        result["metrics"]["module_attempts"][0]["diagnostic_log"]
    )
    assert diagnostic_log.read_text() == "pynguin completed successfully\n"
    assert result["metrics"]["module_attempts"][0]["exit_code"] == 0
    assert (
        result["metrics"]["module_attempts"][0]["output_tail"]
        == "pynguin completed successfully\n"
    )
    assert result["metrics"]["postprocessing_version"] == 11
    assert result["metrics"]["network_guard_injected_count"] == 1
    finalization_calls = [call for call in calls if call[0][:2] == ["git", "add"]]
    assert finalization_calls[0][1] >= 1


def test_scheduler_resolves_relative_repo_and_output_paths(tmp_path, monkeypatch):
    repo = tmp_path / "relative-repo"
    (repo / "tests").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    pynguin_paths = {}

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            project = Path(command[command.index("--project-path") + 1])
            output = Path(command[command.index("--output-path") + 1])
            pynguin_paths.update(project=project, output=output, cwd=repo_dir)
            output.mkdir(parents=True, exist_ok=True)
            (output / "test_generated.py").write_text(
                "import pkg.core as module_0\n\n"
                "def test_x():\n    assert 1\n"
            )
        if command[:2] == ["git", "diff"]:
            stdout = "diff --git a/tests/test.py b/tests/test.py\n"
        elif command[:2] == ["python", "-c"] and "platform" in command[2]:
            stdout = "0.45.0\n3.10.12\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        Path("relative-repo"),
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 1,
            "covered_branches": 0, "num_branches": 0,
        }}},
        total_budget=20,
        diagnostic_dir=Path("diagnostics"),
    )

    assert pynguin_paths["project"] == repo.resolve()
    assert pynguin_paths["output"].is_absolute()
    assert pynguin_paths["output"].is_relative_to(repo.resolve())
    assert pynguin_paths["cwd"] == repo.resolve()
    assert result["metrics"]["module_attempts"][0]["generated_files"] == 1
    assert Path(
        result["metrics"]["module_attempts"][0]["diagnostic_log"]
    ).is_absolute()


def test_scheduler_revalidates_after_pruning_failed_generated_test(
    tmp_path, monkeypatch
):
    (tmp_path / "tests").mkdir()
    validation_calls = 0

    def fake_run(command, repo_dir, timeout, env):
        nonlocal validation_calls
        if command[:3] == ["python", "-m", "pynguin"]:
            output = Path(command[command.index("--output-path") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "test_generated.py").write_text(
                "import pkg.core as module_0\n\n"
                "def test_good():\n    assert True\n\n"
                "def test_bad():\n    raise RuntimeWarning('warning-as-error')\n"
            )
        if command[:3] == ["python", "-m", "pytest"]:
            validation_calls += 1
            generated = tmp_path / "tests" / "test_pynguin_pkg_core.py"
            if validation_calls == 1:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=(
                        "FAILED tests/test_pynguin_pkg_core.py::test_bad "
                        "- RuntimeWarning\n"
                    ),
                )
            assert "test_bad" not in generated.read_text()
            return subprocess.CompletedProcess(command, 0, stdout="1 passed\n")
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
        total_budget=20,
    )

    assert validation_calls == 2
    assert result["metrics"]["removed_failing_test_count"] == 1
    assert result["metrics"]["validation_runs"] == 2
    assert result["metrics"]["validation_exit_code"] == 0


def test_scheduler_isolates_modules_and_rejects_mismatched_export(
    tmp_path, monkeypatch
):
    (tmp_path / "tests").mkdir()
    output_paths = []

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            module = command[command.index("--module-name") + 1]
            output = Path(command[command.index("--output-path") + 1])
            output_paths.append(output)
            output.mkdir(parents=True, exist_ok=True)
            imported_module = module if module == "pkg.a" else "pkg.a"
            (output / "test_generated.py").write_text(
                f"import {imported_module} as module_0\n\n"
                "def test_x():\n    assert True\n"
            )
        stdout = (
            "diff --git a/tests/test_pynguin_pkg_a.py "
            "b/tests/test_pynguin_pkg_a.py\n"
            if command[:2] == ["git", "diff"] else ""
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {
            "pkg/a.py": {
                "covered_lines": 0, "num_statements": 1,
                "covered_branches": 0, "num_branches": 0,
            },
            "pkg/b.py": {
                "covered_lines": 0, "num_statements": 1,
                "covered_branches": 0, "num_branches": 0,
            },
        }},
        total_budget=20,
    )

    assert len(output_paths) == 2
    assert output_paths[0] != output_paths[1]
    assert output_paths[0].parent == output_paths[1].parent
    assert result["metrics"]["successful_modules"] == ["pkg.a"]
    assert result["metrics"]["rejected_mismatched_module_count"] == 1
    assert result["metrics"]["module_attempts"][1]["status"] == "no_tests_generated"


def test_run_kills_child_process_group_on_timeout(tmp_path):
    leaked = tmp_path / "orphan-worker-output"
    child = (
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(0.5)\n"
        f"Path({str(leaked)!r}).write_text('leaked')\n"
    )
    parent = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "time.sleep(5)\n"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _run([sys.executable, "-c", parent], tmp_path, 0.1, os.environ.copy())
    time.sleep(0.7)

    assert not leaked.exists()


def test_scheduler_scopes_noncallable_signature_compatibility(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    generation_environments = []

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            generation_environments.append(env.copy())
            output = Path(command[command.index("--output-path") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "test_generated.py").write_text(
                "import pkg.core as module_0\n\n"
                "def test_x():\n    assert 1\n"
            )
        stdout = (
            "diff --git a/tests/test.py b/tests/test.py\n"
            if command[:2] == ["git", "diff"]
            else ""
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 1,
            "covered_branches": 0, "num_branches": 0,
        }}},
        total_budget=20,
        ignore_noncallable_signatures=True,
    )
    assert generation_environments
    assert ".pynguin-compatibility" in generation_environments[0]["PYTHONPATH"]
    assert result["metrics"]["ignore_noncallable_signatures"] is True
    assert not (tmp_path / ".pynguin-compatibility").exists()


def test_scheduler_enables_network_guard_only_for_generation(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    generation_environments = []
    sitecustomize_sources = []
    setup_environments = []

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            generation_environments.append(env.copy())
            guard_dir = Path(env["PYTHONPATH"].split(os.pathsep)[0])
            sitecustomize_sources.append((guard_dir / "sitecustomize.py").read_text())
        elif command[:4] == ["python", "-m", "pip", "install"] or (
            command[:2] == ["python", "-c"]
            and "importlib.metadata" in command[2]
        ):
            setup_environments.append(env.copy())
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    result = run_pynguin_generation(
        tmp_path,
        {"files": {"pkg/core.py": {
            "covered_lines": 0, "num_statements": 1,
            "covered_branches": 0, "num_branches": 0,
        }}},
        total_budget=20,
    )

    assert generation_environments
    assert "_pynguin_guard_create_connection" in sitecustomize_sources[0]
    assert setup_environments
    assert all(
        ".pynguin-compatibility" not in environment.get("PYTHONPATH", "")
        for environment in setup_environments
    )
    assert result["metrics"]["generation_network_guard"] is True
    assert not (tmp_path / ".pynguin-compatibility").exists()


def test_generation_network_guard_blocks_external_and_allows_loopback(tmp_path):
    (tmp_path / "sitecustomize.py").write_text(_GENERATION_NETWORK_GUARD_SOURCE)
    script = (
        "import errno, socket\n"
        "assert socket.getaddrinfo('localhost', 0)\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 443)\n"
        "except OSError as exc:\n"
        "    assert exc.errno == errno.ENETUNREACH\n"
        "else:\n"
        "    raise AssertionError('external DNS was not blocked')\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "try:\n"
        "    sock.connect(('203.0.113.1', 443))\n"
        "except OSError as exc:\n"
        "    assert exc.errno == errno.ENETUNREACH\n"
        "else:\n"
        "    raise AssertionError('external TCP was not blocked')\n"
        "assert sock.connect_ex(('203.0.113.1', 443)) == errno.ENETUNREACH\n"
        "print('guard-ok')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    assert completed.stdout.strip() == "guard-ok"


def test_noncallable_signature_compatibility_only_changes_pynguin_analysis(tmp_path):
    (tmp_path / "sitecustomize.py").write_text(_NONCALLABLE_SIGNATURE_COMPAT_SOURCE)
    script = (
        "import inspect\n"
        "namespace = {'__name__': 'pynguin.analyses.typesystem', 'inspect': inspect}\n"
        "exec('def probe(): return inspect.signature(None)', namespace)\n"
        "print(namespace['probe']())\n"
        "try:\n"
        "    inspect.signature(None)\n"
        "except TypeError:\n"
        "    print('normal-type-error')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    assert completed.stdout.splitlines() == ["(*args, **kwargs)", "normal-type-error"]


def test_scheduler_collects_tests_after_module_timeout(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()

    def fake_run(command, repo_dir, timeout, env):
        if command[:3] == ["python", "-m", "pynguin"]:
            output = Path(command[command.index("--output-path") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "test_generated.py").write_text(
                "import pkg.core as module_0\n\n"
                "def test_x():\n    assert 1\n"
            )
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


def test_scheduler_pins_pynguin_before_repository_setup(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, repo_dir, timeout, env):
        calls.append((command, env.copy()))
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr("swebench.eval_pipeline.pynguin_generation._run", fake_run)
    run_pynguin_generation(
        tmp_path,
        {"files": {}},
        setup_command="python -m pip install -e . pytest",
        total_budget=10,
        base_environment={"PATH": "/isolated/bin", "MARKER": "isolated"},
    )

    assert calls[0][0][:4] == ["python", "-m", "pip", "install"]
    assert calls[1][0] == [
        "/bin/bash", "-c", "python -m pip install -e . pytest",
    ]
    assert all(environment["MARKER"] == "isolated" for _, environment in calls)


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
