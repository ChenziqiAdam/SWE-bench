import json
import csv

from swebench.eval_pipeline.report import (
    collect_results,
    collect_test_generation_results,
    render_comparison_table,
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


def test_test_generation_report_exports_resource_metrics(tmp_path, capsys):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "instance_id": "demo__repo-1",
                "model_patch": "diff --git a/x b/x\n",
                "metrics": {
                    "wall_time_seconds": 12.5,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "cost_usd": 0.3,
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
    assert row["evaluation_wall_time_seconds"] == "7.25"
    assert "tracked totals" in capsys.readouterr().out


def test_coverage_generation_report_exports_scientific_metrics(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "instance_id": "demo__repo-1",
        "model_patch": "diff --git a/tests/test_x.py b/tests/test_x.py\n",
        "metrics": {"input_tokens": 10, "turns": 3},
    }) + "\n")
    output_csv = tmp_path / "coverage.csv"
    render_coverage_generation_table(
        results={"demo__repo-1": {
            "status": "resolved",
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
            "mutation_score_delta": 30.0,
        }},
        instances=[{"instance_id": "demo__repo-1", "repo": "demo/repo"}],
        output_csv=str(output_csv),
        predictions_path=str(predictions),
    )
    with open(output_csv, newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["line_coverage_delta"] == "20.0"
    assert row["mutation_score_delta"] == "30.0"
    assert row["added_assertion_count"] == "4"
    assert row["no_existing_test_lines_removed"] == "yes"
    assert row["mutation_timeout_adjusted_score_after"] == "65.0"
    assert row["mutation_score_definition"] == "100 * killed / total"
    assert row["turns"] == "3"
