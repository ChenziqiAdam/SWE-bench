import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_replication_tasks import run_pipeline as pipeline
from paper_replication_tasks import container_runtime
from paper_replication_tasks.evaluation.framework import EvaluationInputError
from swebench.eval_pipeline.linux_network_guard import _bubblewrap_command
from swebench.eval_pipeline.network_isolation import (
    NetworkIsolationError,
    guard_command,
)


def test_task_defaults_and_invalid_lifecycle(monkeypatch):
    monkeypatch.setattr(
        pipeline.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 4000))],
    )
    args = pipeline.parse_args(
        [
            "--backend", "codex", "--model", "m",
            "--endpoint", "http://localhost:4000",
            "--container-image", "paper-agent:test",
        ]
    )
    assert "scibench_replication_0007" in args.task_ids
    with pytest.raises(SystemExit):
        pipeline.parse_args(
            [
                "--backend", "codex", "--model", "m",
                "--endpoint", "http://localhost:4000",
                "--container-image", "paper-agent:test",
                "--task-id", "scibench_replication_0010",
            ]
        )


def test_non_loopback_endpoint_is_rejected(monkeypatch):
    monkeypatch.setattr(
        pipeline.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("203.0.113.2", 443))],
    )
    with pytest.raises(ValueError, match="loopback"):
        pipeline.validate_loopback_endpoint("https://example.test")


def test_claude_auth_uses_environment_without_mounting_host_login(monkeypatch):
    monkeypatch.setattr(
        pipeline.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 4000))],
    )
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    base = [
        "--backend", "claude_code",
        "--model", "m",
        "--endpoint", "http://localhost:4000",
        "--container-image", "paper-agent:test",
    ]
    with pytest.raises(SystemExit):
        pipeline.parse_args(base)

    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-secret")
    args = pipeline.parse_args(base)
    assert args.api_key == "gateway-secret"
    assert args.auth_source == "ANTHROPIC_AUTH_TOKEN"


def test_workspace_copies_only_regular_public_files(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    (public / "task.md").write_text("task")
    (public / "nested").mkdir()
    (public / "nested" / "input.json").write_text("{}")
    workspace = tmp_path / "workspace"
    pipeline.create_agent_workspace(public, workspace)
    assert sorted(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file()
    ) == ["nested/input.json", "task.md"]

    linked = tmp_path / "linked"
    linked.symlink_to(public / "task.md")
    (public / "bad").symlink_to(linked)
    with pytest.raises(ValueError, match="symlink"):
        pipeline.public_bundle_manifest(public)


def test_public_fingerprint_changes_with_content(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    source = public / "task.md"
    source.write_text("one")
    first = pipeline.public_bundle_fingerprint(
        pipeline.public_bundle_manifest(public)
    )
    source.write_text("two")
    second = pipeline.public_bundle_fingerprint(
        pipeline.public_bundle_manifest(public)
    )
    assert first != second


def test_literal_credentials_are_scrubbed_from_persisted_tree(tmp_path):
    (tmp_path / "source.py").write_text("TOKEN = 'secret-key'")
    (tmp_path / "binary.bin").write_bytes(b"\x00secret-key\xff")
    pipeline.redact_tree_credentials(tmp_path, ["secret-key"])
    assert "secret-key" not in (tmp_path / "source.py").read_text()
    assert b"secret-key" not in (tmp_path / "binary.bin").read_bytes()


def test_entrypoint_parsing_has_no_shell():
    assert pipeline.parse_entrypoint('python "reproduce file.py" --seed 1') == [
        "python", "reproduce file.py", "--seed", "1"
    ]
    with pytest.raises(EvaluationInputError, match="quoting"):
        pipeline.parse_entrypoint("python 'unterminated")


def test_execution_copy_removes_only_declared_outputs(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "reproduce.py").write_text("pass")
    (raw / "keep.txt").write_text("keep")
    (raw / "artifact.npy").write_bytes(b"old")
    (raw / "results.json").write_text("{}")
    results = {
        "artifacts": [
            {"id": "array", "path": "artifact.npy", "media_type": "application/x-npy"}
        ]
    }
    executed = tmp_path / "executed"
    pipeline.prepare_execution_copy(raw, executed, results)
    assert (executed / "reproduce.py").is_file()
    assert (executed / "keep.txt").read_text() == "keep"
    assert not (executed / "artifact.npy").exists()
    assert not (executed / "results.json").exists()


def test_hidden_path_is_forwarded_to_linux_guard(tmp_path, monkeypatch):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    monkeypatch.delenv("SWE_BENCH_NETWORK_GUARD", raising=False)
    monkeypatch.setattr(pipeline.sys, "platform", "linux")
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation._find_bubblewrap",
        lambda: "/usr/bin/bwrap",
    )
    command = guard_command(
        ["agent"], policy="model-only", hidden_paths=[str(hidden)]
    )
    assert command[-4:] == ["--hide-path", str(hidden), "--", "agent"]

    wrapped = _bubblewrap_command(
        "/usr/bin/bwrap", tmp_path / "relay", None, ["agent"], [str(hidden)]
    )
    location = wrapped.index(str(hidden))
    assert wrapped[location - 1] == "--tmpfs"


def test_external_guard_receives_hidden_paths(tmp_path, monkeypatch):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    monkeypatch.setenv("SWE_BENCH_NETWORK_GUARD", "/trusted/guard")
    assert guard_command(
        ["agent"], policy="model-only", hidden_paths=[str(hidden)]
    ) == ["/trusted/guard", "--hide-path", str(hidden), "--", "agent"]


def test_podman_client_requires_socket_and_rejects_other_engines(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    with pytest.raises(container_runtime.ContainerRuntimeError, match="DOCKER_HOST"):
        container_runtime.podman_client()

    class FakeClient:
        def ping(self):
            return True

        def version(self):
            return {"Components": [{"Name": "Docker Engine"}]}

        def close(self):
            pass

    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1/podman.sock")
    monkeypatch.setattr(container_runtime.docker, "from_env", lambda: FakeClient())
    with pytest.raises(container_runtime.ContainerRuntimeError, match="not identified"):
        container_runtime.podman_client()


def test_podman_runtime_uses_no_network_and_hardened_container(
    tmp_path, monkeypatch
):
    observed = {}

    class FakeSocket:
        def bind(self, path):
            observed["relay_socket"] = path

        def listen(self, backlog):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        container_runtime.socket, "socket", lambda *args, **kwargs: FakeSocket()
    )
    monkeypatch.setattr(container_runtime, "_serve_host_relay", lambda *args: None)

    class FakeContainer:
        id = "container-id"
        status = "exited"

        def reload(self):
            self.status = "exited"

        def wait(self, timeout):
            return {"StatusCode": 0}

        def logs(self, *, stdout, stderr):
            return b"stream" if stdout else b""

        def remove(self, force):
            observed["removed"] = force

    class FakeContainers:
        def run(self, **kwargs):
            observed.update(kwargs)
            return FakeContainer()

    class FakeClient:
        containers = FakeContainers()

    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    home = tmp_path / "home"
    workspace.mkdir()
    runtime.mkdir()
    result = container_runtime.run_podman_container(
        client=FakeClient(),
        image="paper:test",
        command=["python3", "-V"],
        workspace=workspace,
        runtime_dir=runtime,
        runtime_home=home,
        environment={"HOME": "/agent-home"},
        timeout=5,
        container_python="python3",
        gateway_endpoint="http://127.0.0.1:4000",
        memory="8g",
        cpus=2,
        pids_limit=128,
        tmpfs_size="1g",
    )
    assert result["exit_code"] == 0
    assert observed["network_disabled"] is True
    assert observed["network_mode"] == "none"
    assert observed["read_only"] is True
    assert observed["entrypoint"] == []
    assert observed["privileged"] is False
    assert observed["cap_drop"] == ["ALL"]
    assert observed["security_opt"] == ["no-new-privileges:true"]
    assert "userns_mode" not in observed
    assert "user" not in observed
    assert observed["pids_limit"] == 128
    assert observed["mem_limit"] == "8g"
    assert observed["nano_cpus"] == 2_000_000_000
    assert {
        str(workspace.resolve()),
        str(runtime.resolve()),
        str(home.resolve()),
    }.issubset(observed["volumes"])
    assert len(observed["volumes"]) == 4
    assert any(
        mount["bind"] == "/gateway"
        for mount in observed["volumes"].values()
    )
    assert observed["command"][:5] == [
        "python3",
        "/runner/container_proxy.py",
        "/gateway/relay",
        "4000",
        "--",
    ]


def test_hidden_evaluator_runs_offline_with_read_only_submission(
    tmp_path, monkeypatch
):
    observed = {}

    class FakeClient:
        def close(self):
            observed["closed"] = True

    def fake_container(**kwargs):
        observed.update(kwargs)
        pipeline.write_json(
            kwargs["runtime_home"] / "evaluation.json",
            {
                "schema_version": 1,
                "task_id": "scibench_replication_0007",
                "valid_execution": True,
                "score": 1.0,
                "full_success": True,
                "checks": [],
            },
        )
        return {
            "exit_code": 0,
            "stderr": "",
            "timed_out": False,
            "container_id": "evaluator-container",
        }

    monkeypatch.setattr(pipeline, "podman_client", lambda: FakeClient())
    monkeypatch.setattr(pipeline, "run_podman_container", fake_container)
    submission = tmp_path / "submission"
    submission.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    output = tmp_path / "evaluation.json"
    result = pipeline.run_evaluator(
        "scibench_replication_0007",
        submission,
        manifest,
        output,
        30,
        container_image="paper:test",
        container_python="python3",
        container_memory="8g",
        container_cpus=2,
        container_pids=128,
        container_tmpfs_size="1g",
    )
    assert result["exit_code"] == 0
    assert result["report"]["score"] == 1.0
    assert observed["gateway_endpoint"] is None
    assert observed["workspace_mode"] == "ro,Z"
    assert observed["environment"]["PYTHONPATH"] == "/runner"
    assert (observed["runtime_dir"] / "evaluation/plugins.py").is_file()
    assert (observed["runtime_dir"] / "task_hidden/gold_output.json").is_file()


def test_reports_preserve_nonfinite_and_structured_diagnostics(tmp_path):
    records = [{
        "task_id": "task",
        "backend": "codex",
        "model": "m",
        "status": "completed",
        "failure_type": None,
        "score": 0.5,
        "full_success": False,
        "valid_execution": True,
        "agent": {"usage": {"total_tokens": 10, "cost_usd": 0.1}},
        "execution": {
            "manifest": {
                "resource_usage": {
                    "wall_seconds": 2,
                    "cpu_seconds": 1,
                    "peak_memory_bytes": 3,
                }
            }
        },
        "evaluator": {
            "report": {
                "checks": [{
                    "id": "difference",
                    "category": "scientific",
                    "passed": False,
                    "critical": True,
                    "message": "mismatch",
                    "diagnostics": {
                        "max_abs": float("inf"),
                        "actual": [1, 2],
                        "expected": {"value": 3},
                        "atol": 0.01,
                    },
                }]
            }
        },
    }]
    pipeline.write_reports(tmp_path, records)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["mean_score"] == 0.5
    with (tmp_path / "difference_metrics.csv").open() as handle:
        row = next(csv.DictReader(handle))
    assert row["max_abs"] == "Infinity"
    assert json.loads(row["actual"]) == [1, 2]
    assert json.loads(row["expected"]) == {"value": 3}


def test_process_task_mocked_end_to_end_keeps_scientific_mismatch_completed(
    tmp_path, monkeypatch
):
    benchmark = tmp_path / "paper_replication_tasks"
    public = benchmark / "task_1" / "public"
    public.mkdir(parents=True)
    for name, content in {
        "task.md": "task",
        "input.json": "{}",
        "submission_schema.json": "{}",
    }.items():
        (public / name).write_text(content)
    monkeypatch.setattr(pipeline, "ROOT", benchmark)

    def fake_agent(**kwargs):
        workspace = kwargs["workspace"]
        script = """\
import json
from pathlib import Path
Path("artifact.txt").write_text("1")
Path("results.json").write_text(json.dumps({
    "schema_version": 1,
    "task_id": "task_1",
    "entrypoint": "python reproduce.py",
    "protocol": {},
    "checkpoints": {},
    "artifacts": [{"id": "value", "path": "artifact.txt", "media_type": "text/plain"}],
}))
"""
        (workspace / "reproduce.py").write_text(script)
        (workspace / "artifact.txt").write_text("1")
        (workspace / "results.json").write_text(json.dumps({
            "schema_version": 1,
            "task_id": "task_1",
            "entrypoint": "python reproduce.py",
            "protocol": {},
            "checkpoints": {},
            "artifacts": [
                {"id": "value", "path": "artifact.txt", "media_type": "text/plain"}
            ],
        }))
        return {
            "backend": "codex",
            "model": "m",
            "exit_code": 0,
            "usage": {"total_tokens": 4},
        }

    def fake_execution(**kwargs):
        from paper_replication_tasks.run_submission import execute

        manifest = execute(
            kwargs["execution_dir"],
            kwargs["task_id"],
            kwargs["command"],
            kwargs["timeout"],
        )
        pipeline.write_json(kwargs["manifest_path"], manifest)
        return {"runner_exit_code": 0, "stderr": "", "manifest": manifest}

    def fake_evaluator(
        task_id, execution_dir, manifest_path, output_path, timeout, **kwargs
    ):
        report = {
            "task_id": task_id,
            "valid_execution": True,
            "score": 0.4,
            "full_success": False,
            "checks": [{
                "id": "value",
                "category": "scientific",
                "passed": False,
                "critical": True,
                "message": "numerical mismatch",
                "diagnostics": {"max_abs": 1.0, "limit": 0.1},
            }],
        }
        pipeline.write_json(output_path, report)
        return {"exit_code": 0, "stderr": "", "report": report}

    monkeypatch.setattr(pipeline, "run_agent", fake_agent)
    monkeypatch.setattr(pipeline, "run_trusted_execution", fake_execution)
    monkeypatch.setattr(pipeline, "run_evaluator", fake_evaluator)
    args = SimpleNamespace(
        backend="codex",
        model="m",
        endpoint="http://127.0.0.1:4000",
        api_key=None,
        claude_oauth_token=None,
        container_image="paper-agent:test",
        container_image_identity={"digest": "sha256:test"},
        container_python="python3",
        container_memory="16g",
        container_cpus=4.0,
        container_pids=512,
        container_tmpfs_size="4g",
        workspace_root=None,
        agent_timeout=10,
        agent_retries=0,
        execution_timeout=10,
        evaluator_timeout=10,
        resume=True,
        force_inference=False,
        force_evaluation=False,
    )
    record = pipeline.process_task(args, tmp_path / "run", "task_1")
    assert record["status"] == "completed"
    assert record["failure_type"] is None
    assert record["score"] == 0.4
    assert (tmp_path / "run/tasks/task_1/raw_submission/results.json").is_file()
    assert (tmp_path / "run/tasks/task_1/executed_submission/artifact.txt").is_file()
