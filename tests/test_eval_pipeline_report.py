import json
import csv

from swebench.eval_pipeline.report import (
    collect_results,
    collect_test_generation_results,
    render_comparison_table,
    render_coverage_comparison_table,
    render_test_generation_table,
    render_coverage_generation_table,
)


def test_report_notes_excluded_harness_resolved_instances(tmp_path, capsys):
    run_id = "run_agent"
    report_dir = tmp_path / run_id / "model" / "demo__repo-1"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "demo__repo-1": {
                    "resolved": True,
                    "tests_status": {"FAIL_TO_PASS": {"success": [], "failure": []}},
                }
            }
        )
    )

    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps({"instance_id": "demo__repo-1", "model_patch": "diff --git a/x b/x\n"})
        + "\n"
    )

    results = collect_results({"agent": run_id}, log_dir=str(tmp_path))
    render_comparison_table(
        results,
        instances=[
            {
                "instance_id": "demo__repo-1",
                "repo": "demo/repo",
                "pull_number": 1,
                "FAIL_TO_PASS": [],
            }
        ],
        output_csv=str(tmp_path / "results.csv"),
        predictions_path=str(predictions),
    )

    output = capsys.readouterr().out
    assert "0/0 scorable" in output
    assert "harness-resolved instance(s) were excluded" in output


def test_fix_report_exports_pipeline_docker_failure(tmp_path, capsys):
    output_csv = tmp_path / "results.csv"
    render_comparison_table(
        results={},
        instances=[{
            "instance_id": "demo__repo-1",
            "repo": "demo/repo",
            "FAIL_TO_PASS": ["test_bug"],
        }],
        output_csv=str(output_csv),
        pipeline_failure="Docker daemon unavailable: connection refused",
    )

    with output_csv.open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["status"] == "errored"
    assert row["failure_reason"] == "docker_infrastructure_failure"
    assert "connection refused" in row["error"]
    assert "PIPELINE FAILURE" in capsys.readouterr().out


def test_collect_fix_result_reads_structured_evaluation_error(tmp_path):
    error_dir = tmp_path / "run_agent" / "model" / "demo__repo-1"
    error_dir.mkdir(parents=True)
    (error_dir / "error.json").write_text(json.dumps({
        "demo__repo-1": {
            "status": "errored",
            "failure_reason": "container_build_or_start",
            "error": "APIError: container start failed",
        }
    }))

    results = collect_results({"agent": "run_agent"}, log_dir=str(tmp_path))

    assert results["demo__repo-1"]["failure_reason"] == "container_build_or_start"
    assert "container start failed" in results["demo__repo-1"]["error"]


def test_collect_test_generation_results_filters_model_dir(tmp_path):
    run_id = "run_testgen"
    current = tmp_path / run_id / "deepseek-v4-flash" / "demo__repo-1"
    stale = tmp_path / run_id / "unknown" / "demo__repo-1"
    current.mkdir(parents=True)
    stale.mkdir(parents=True)
    (current / "report.json").write_text(
        json.dumps({"demo__repo-1": {"status": "resolved"}})
    )
    (stale / "report.json").write_text(
        json.dumps({"demo__repo-1": {"status": "no-pred"}})
    )

    results = collect_test_generation_results(
        run_id,
        log_dir=str(tmp_path),
        instance_ids={"demo__repo-1"},
        model_name="deepseek-v4-flash",
    )

    assert results["demo__repo-1"]["status"] == "resolved"


def test_collect_test_generation_results_counts_only_selected_instances(tmp_path, caplog):
    caplog.set_level("INFO")
    run_id = "run_testgen"
    for instance_id in ("demo__repo-1", "stale__repo-2"):
        report_dir = tmp_path / run_id / "model" / instance_id
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(
            json.dumps({instance_id: {"status": "resolved"}})
        )

    results = collect_test_generation_results(
        run_id,
        log_dir=str(tmp_path),
        instance_ids={"demo__repo-1"},
        model_name="model",
    )

    assert set(results) == {"demo__repo-1"}
    assert "found 1 report files" in caplog.text


def test_test_generation_report_exports_resource_metrics(tmp_path, capsys):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "instance_id": "demo__repo-1",
                "model_patch": "diff --git a/x b/x\n",
                "error": "timeout",
                "metrics": {
                    "wall_time_seconds": 12.5,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "cost_usd": 0.3,
                    "usage_incomplete": True,
                },
            }
        )
        + "\n"
    )
    output_csv = tmp_path / "results.csv"
    render_test_generation_table(
        results={
            "demo__repo-1": {
                "status": "resolved",
                "evaluation_wall_time_seconds": 7.25,
            }
        },
        instances=[{"instance_id": "demo__repo-1", "repo": "demo/repo"}],
        output_csv=str(output_csv),
        predictions_path=str(predictions),
    )

    with open(output_csv, newline="") as f:
        row = next(csv.DictReader(f))
    assert row["input_tokens"] == "100"
    assert row["cost_usd"] == "0.3"
    assert row["inference_wall_time_seconds"] == "12.5"
    assert row["inference_error"] == "timeout"
    assert row["inference_usage_incomplete"] == "yes"
    assert row["evaluation_wall_time_seconds"] == "7.25"
    assert "tracked totals" in capsys.readouterr().out


def test_test_generation_report_excludes_base_image_infrastructure_failure(
    tmp_path, capsys
):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "instance_id": "demo__repo-1",
                "model_patch": "diff --git a/x b/x\n",
            }
        )
        + "\n"
    )
    output_csv = tmp_path / "results.csv"
    render_test_generation_table(
        results={
            "demo__repo-1": {
                "status": "errored",
                "failure_reason": "evaluation_exception",
                "evaluation_stage": "build_instance_image",
            }
        },
        instances=[{"instance_id": "demo__repo-1", "repo": "demo/repo"}],
        output_csv=str(output_csv),
        build_validation={
            "demo__repo-1": {
                "buildable": False,
                "error": "apt exited with code 100",
            }
        },
        predictions_path=str(predictions),
    )

    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["status"] == "excluded"
    assert row["buildable"] == "no"
    assert row["failure_reason"] == "base_image_not_buildable"
    assert row["build_validation_error"] == "apt exited with code 100"
    assert "0/0 scorable; 1 total" in capsys.readouterr().out


def test_test_generation_report_does_not_exclude_invalid_spec(tmp_path):
    output_csv = tmp_path / "results.csv"
    render_test_generation_table(
        results={
            "demo__repo-1": {
                "status": "errored",
                "failure_reason": "invalid_test_spec",
                "evaluation_stage": "resolve_test_spec",
                "error": "KeyError: '0'",
            }
        },
        instances=[{"instance_id": "demo__repo-1", "repo": "demo/repo"}],
        output_csv=str(output_csv),
        build_validation={
            "demo__repo-1": {"buildable": False, "error": "no spec for version '0'"}
        },
    )

    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["status"] == "errored"
    assert row["failure_reason"] == "invalid_test_spec"
    assert row["evaluation_error"] == "KeyError: '0'"


def test_test_generation_report_keeps_successful_validation_retry(tmp_path):
    output_csv = tmp_path / "results.csv"
    render_test_generation_table(
        results={"demo__repo-1": {"status": "resolved"}},
        instances=[{"instance_id": "demo__repo-1", "repo": "demo/repo"}],
        output_csv=str(output_csv),
        build_validation={
            "demo__repo-1": {"buildable": False, "error": "transient apt failure"}
        },
    )

    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["status"] == "resolved"
    assert row["buildable"] == "no"


def test_coverage_generation_report_exports_scientific_metrics(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "instance_id": "demo__repo-1",
        "model_patch": "diff --git a/tests/test_x.py b/tests/test_x.py\n",
        "metrics": {
            "input_tokens": 10,
            "turns": 3,
            "attempt_count": 2,
            "interrupted_attempts": 1,
            "usage_incomplete": True,
        },
    }) + "\n")
    output_csv = tmp_path / "coverage.csv"
    render_coverage_generation_table(
        results={"demo__repo-1": {
            "status": "resolved",
            "base_commit": "abc123",
            "coverage_targets": ["src/pkg/core.py"],
            "tests_only_patch": True,
            "no_existing_test_lines_removed": True,
            "base_tests_passed": True,
            "after_tests_passed": True,
            "baseline_flaky": False,
            "generated_tests_flaky": False,
            "added_test_count": 2,
            "added_assertion_count": 4,
            "coverage_before": {"line_coverage": 50.0, "branch_coverage": 25.0},
            "coverage_after": {"line_coverage": 70.0, "branch_coverage": 50.0},
            "coverage_line_delta": 20.0,
            "coverage_branch_delta": 25.0,
            "mutation_before": {
                "score": 30.0,
                "score_killed_or_timeout": 35.0,
                "score_definition": "100 * killed / total",
            },
            "mutation_after": {"score": 60.0, "score_killed_or_timeout": 65.0},
            "mutation_before_partial": {
                "processed": 100, "expected": 200, "killed": 10,
            },
            "mutation_after_partial": {
                "processed": 150, "expected": 200, "killed": 40,
            },
            "mutation_score_delta": 30.0,
            "mutation_before_timed_out": True,
            "mutation_after_timed_out": False,
        }},
        instances=[{"instance_id": "demo__repo-1", "repo": "demo/repo"}],
        output_csv=str(output_csv),
        predictions_path=str(predictions),
    )
    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["line_coverage_delta"] == "20.0"
    assert row["base_commit"] == "abc123"
    assert row["mutation_score_delta"] == "30.0"
    assert row["added_assertion_count"] == "4"
    assert row["no_existing_test_lines_removed"] == "yes"
    assert row["mutation_timeout_adjusted_score_after"] == "65.0"
    assert row["mutation_score_definition"] == "100 * killed / total"
    assert row["mutation_before_timed_out"] == "yes"
    assert row["mutation_after_timed_out"] == "no"
    assert row["mutation_partial_before_processed"] == "100"
    assert row["mutation_partial_after_expected"] == "200"
    assert row["mutation_partial_after_killed"] == "40"
    assert row["turns"] == "3"
    assert row["inference_attempt_count"] == "2"
    assert row["inference_interrupted_attempts"] == "1"
    assert row["inference_usage_incomplete"] == "yes"


def test_coverage_comparison_reports_partial_mutation_prefix(tmp_path):
    output_csv = tmp_path / "comparison.csv"
    render_coverage_comparison_table(
        [{
            "method": "pynguin",
            "status": "partial",
            "failure_reason": "mutation_evaluation_timeout",
            "mutation_after_partial": {
                "processed": 263, "expected": 309, "killed": 37,
            },
        }],
        str(output_csv),
    )
    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["status"] == "partial"
    assert row["mutation_score"] == ""
    assert row["mutation_partial_processed"] == "263"
    assert row["mutation_partial_expected"] == "309"
    assert row["mutation_partial_killed"] == "37"


def test_coverage_no_prediction_reports_repository_scope_and_inference_error(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "instance_id": "standalone__demo-1",
        "model_patch": "",
        "error": "claude exited with code 1: missing prompt",
        "metrics": {"wall_time_seconds": 2.0},
    }) + "\n")
    output_csv = tmp_path / "coverage.csv"
    render_coverage_generation_table(
        results={"standalone__demo-1": {"status": "no-pred"}},
        instances=[{
            "instance_id": "standalone__demo-1",
            "repo": "demo/repo",
            "standalone": True,
        }],
        output_csv=str(output_csv),
        predictions_path=str(predictions),
    )
    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["coverage_scope"] == "repository"
    assert row["failure_reason"] == "claude exited with code 1: missing prompt"
