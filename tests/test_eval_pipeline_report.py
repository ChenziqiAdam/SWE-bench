import json

from swebench.eval_pipeline.report import collect_results, render_comparison_table


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
