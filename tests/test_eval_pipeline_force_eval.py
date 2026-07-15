import json
import subprocess

from swebench.eval_pipeline import run_pipeline


def test_force_eval_clears_only_selected_instance_reports(tmp_path, monkeypatch):
    run_dir = tmp_path / "run_testgen" / "model"
    selected = run_dir / "rdkit__rdkit-2083"
    unrelated = run_dir / "openmm__openmm-1235"
    selected.mkdir(parents=True)
    unrelated.mkdir()
    (selected / "report.json").write_text("selected")
    (unrelated / "report.json").write_text("unrelated")
    docker_calls = []

    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: docker_calls.append(command)
    )

    removed = run_pipeline._clear_selected_evaluation_cache(
        tmp_path, "run_testgen", ["rdkit__rdkit-2083"]
    )

    assert removed == 1
    assert not selected.exists()
    assert (unrelated / "report.json").read_text() == "unrelated"
    assert docker_calls == [
        ["docker", "rm", "-f", "sweb.eval.rdkit__rdkit-2083.run_testgen"]
    ]


def test_partial_rerun_preserves_unselected_prompts(tmp_path):
    prompts_path = tmp_path / "agent_prompts.jsonl"
    prompts_path.write_text(
        json.dumps({"instance_id": "keep", "prompt": "old"}) + "\n"
    )

    count = run_pipeline._write_prompts_preserving_unselected(
        prompts_path, {"replace": "new"}, preserve_existing=True
    )
    rows = [json.loads(line) for line in prompts_path.read_text().splitlines()]

    assert count == 2
    assert rows == [
        {"instance_id": "keep", "prompt": "old"},
        {"instance_id": "replace", "prompt": "new"},
    ]
