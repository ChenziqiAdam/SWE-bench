import json

import docker

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

    class FakeContainer:
        def remove(self, force=False):
            docker_calls.append(("remove", force))

    class FakeContainers:
        def get(self, name):
            docker_calls.append(("get", name))
            return FakeContainer()

    class FakeClient:
        containers = FakeContainers()

        def close(self):
            docker_calls.append(("close",))

    monkeypatch.setattr(docker, "from_env", lambda: FakeClient())

    removed = run_pipeline._clear_selected_evaluation_cache(
        tmp_path, "run_testgen", ["rdkit__rdkit-2083"]
    )

    assert removed == 1
    assert not selected.exists()
    assert (unrelated / "report.json").read_text() == "unrelated"
    assert docker_calls == [
        ("get", "sweb.eval.rdkit__rdkit-2083.run_testgen"),
        ("remove", True),
        ("close",),
    ]


def test_force_eval_container_cleanup_is_best_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(
        docker,
        "from_env",
        lambda: (_ for _ in ()).throw(docker.errors.DockerException("offline")),
    )

    assert run_pipeline._clear_selected_evaluation_cache(
        tmp_path, "run_testgen", ["rdkit__rdkit-2083"]
    ) == 0


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
