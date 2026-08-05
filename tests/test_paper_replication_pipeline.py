import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_replication_tasks import run_pipeline as pipeline
from paper_replication_tasks import container_runtime
from swebench.eval_pipeline.linux_network_guard import _bubblewrap_command
from swebench.eval_pipeline.network_isolation import guard_command


def test_task_defaults_and_invalid_lifecycle(monkeypatch):
    monkeypatch.setattr(
        pipeline.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 4000))],
    )
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-secret")
    args = pipeline.parse_args(
        [
            "--model", "m",
            "--endpoint", "http://localhost:4000",
            "--container-image", "paper-agent:test",
        ]
    )
    assert "scibench_replication_0007" in args.task_ids
    assert args.backend == "claude_code"
    with pytest.raises(SystemExit):
        pipeline.parse_args(
            [
                "--model", "m",
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


def test_trusted_execution_wraps_run_submission_read_only(tmp_path, monkeypatch):
    observed = {}

    def fake_container(**kwargs):
        observed.update(kwargs)
        report = {
            "schema_version": 4,
            "task_id": "scibench_replication_0007",
            "entrypoint": ["python3", "solution.py"],
            "cases": {"public": [], "hidden": []},
        }
        pipeline.write_json(
            kwargs["runtime_home"] / "execution_report.json", report
        )
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "container_id": "execution-container",
        }

    class FakeClient:
        def close(self):
            observed["closed"] = True

    monkeypatch.setattr(pipeline, "podman_client", lambda: FakeClient())
    monkeypatch.setattr(pipeline, "run_podman_container", fake_container)

    task_id = "scibench_replication_0007"
    (pipeline.ROOT / task_id / "public").exists()  # sanity: real task bundle exists
    submission_dir = tmp_path / "submission"
    submission_dir.mkdir()
    manifest_path = tmp_path / "execution_report.json"

    result = pipeline.run_trusted_execution(
        task_id=task_id,
        submission_dir=submission_dir,
        manifest_path=manifest_path,
        timeout=30,
        container_image="paper:test",
        container_python="python3",
        container_memory="8g",
        container_cpus=2,
        container_pids=128,
        container_tmpfs_size="1g",
    )
    assert result["runner_exit_code"] == 0
    assert result["report"]["task_id"] == task_id
    assert observed["gateway_endpoint"] is None
    assert observed["workspace_mode"] == "ro,Z"
    assert observed["command"][-6:] == [
        "--task-dir", f"/runner/{task_id}",
        "--output", "/agent-home/execution_report.json",
        "--timeout-seconds", "30",
    ]
    assert (observed["runtime_dir"] / "run_submission.py").is_file()
    assert (observed["runtime_dir"] / task_id / "public").is_dir()


def test_evaluator_runs_offline_with_read_only_bundle(tmp_path, monkeypatch):
    observed = {}

    def fake_container(**kwargs):
        observed.update(kwargs)
        pipeline.write_json(
            kwargs["runtime_home"] / "evaluation.json",
            {
                "schema_version": 4,
                "task_id": "scibench_replication_0007",
                "valid_execution": True,
                "public_score": 1.0,
                "hidden_score": 1.0,
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

    class FakeClient:
        def close(self):
            observed["closed"] = True

    monkeypatch.setattr(pipeline, "podman_client", lambda: FakeClient())
    monkeypatch.setattr(pipeline, "run_podman_container", fake_container)

    task_id = "scibench_replication_0007"
    manifest_path = tmp_path / "execution_report.json"
    manifest_path.write_text("{}")
    output = tmp_path / "evaluation.json"
    result = pipeline.run_evaluator(
        task_id,
        manifest_path,
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
    assert (observed["runtime_dir"] / "evaluation" / "framework.py").is_file()
    assert (observed["runtime_dir"] / task_id / "manifest.json").exists() is False
    assert (observed["runtime_dir"] / "manifest.json").is_file()
    assert (observed["runtime_dir"] / task_id / "hidden" / "tolerances.json").is_file()


def test_reports_preserve_nonfinite_and_structured_diagnostics(tmp_path):
    records = [{
        "task_id": "task",
        "model": "m",
        "status": "completed",
        "failure_type": None,
        "score": 0.5,
        "full_success": False,
        "valid_execution": True,
        "agent": {"usage": {"total_tokens": 10, "cost_usd": 0.1}},
        "evaluator": {
            "report": {
                "public_score": 1.0,
                "hidden_score": 0.2,
                "checks": [{
                    "id": "hidden:case_01",
                    "split": "hidden",
                    "passed": False,
                    "critical": True,
                    "diagnostics": {
                        "max_abs": float("inf"),
                        "rmse": 0.5,
                        "structural_errors": ["$.value: value differs"],
                    },
                }],
            }
        },
    }]
    pipeline.write_reports(tmp_path, records)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["mean_score"] == 0.5
    with (tmp_path / "difference_metrics.csv").open() as handle:
        row = next(csv.DictReader(handle))
    assert row["max_abs"] == "Infinity"
    assert json.loads(row["structural_errors"]) == ["$.value: value differs"]
    with (tmp_path / "results.csv").open() as handle:
        result_row = next(csv.DictReader(handle))
    assert result_row["public_score"] == "1.0"
    assert result_row["hidden_score"] == "0.2"


def test_process_task_mocked_end_to_end_keeps_scientific_mismatch_completed(
    tmp_path, monkeypatch
):
    benchmark = tmp_path / "paper_replication_tasks"
    public = benchmark / "task_1" / "public"
    public.mkdir(parents=True)
    for name, content in {
        "task.md": "task",
        "paper.pdf": "%PDF-1.4",
        "interface.schema.json": "{}",
    }.items():
        (public / name).write_text(content)
    monkeypatch.setattr(pipeline, "ROOT", benchmark)

    def fake_agent(**kwargs):
        workspace = kwargs["workspace"]
        (workspace / "solution.py").write_text("pass")
        (workspace / "submission.json").write_text(json.dumps({
            "schema_version": 4,
            "task_id": "task_1",
            "entrypoint": ["python3", "solution.py"],
        }))
        return {
            "backend": "claude_code",
            "model": "m",
            "exit_code": 0,
            "usage": {"total_tokens": 4},
        }

    def fake_execution(**kwargs):
        report = {
            "schema_version": 4,
            "task_id": "task_1",
            "entrypoint": ["python3", "solution.py"],
            "cases": {"public": [], "hidden": []},
        }
        pipeline.write_json(kwargs["manifest_path"], report)
        return {"runner_exit_code": 0, "stderr": "", "timed_out": False, "report": report}

    def fake_evaluator(task_id, manifest_path, output_path, timeout, **kwargs):
        report = {
            "task_id": task_id,
            "valid_execution": True,
            "public_score": 1.0,
            "hidden_score": 0.0,
            "score": 0.4,
            "full_success": False,
            "checks": [{
                "id": "hidden:case_01",
                "split": "hidden",
                "passed": False,
                "critical": True,
                "diagnostics": {"max_abs": 1.0, "rmse": 0.5, "structural_errors": []},
            }],
        }
        pipeline.write_json(output_path, report)
        return {"exit_code": 0, "stderr": "", "report": report}

    monkeypatch.setattr(pipeline, "run_agent", fake_agent)
    monkeypatch.setattr(pipeline, "run_trusted_execution", fake_execution)
    monkeypatch.setattr(pipeline, "run_evaluator", fake_evaluator)
    args = SimpleNamespace(
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
    assert (tmp_path / "run/tasks/task_1/raw_submission/submission.json").is_file()
