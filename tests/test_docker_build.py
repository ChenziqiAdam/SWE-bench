import itertools
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import docker
import requests

from swebench.harness import docker_build
from swebench.harness.docker_build import _create_eval_container


def test_build_image_retries_podman_stale_layer_once(monkeypatch, tmp_path):
    responses = [
        iter([{"errorDetail": {"message": "top layer info: layer not known"}}]),
        iter([{"stream": "success\n"}]),
    ]
    api = SimpleNamespace(build=Mock(side_effect=responses))
    client = SimpleNamespace(api=api)
    logger = Mock()
    monkeypatch.setattr(docker_build, "setup_logger", lambda *_args: logger)
    monkeypatch.setattr(docker_build, "close_logger", lambda *_args: None)

    docker_build.build_image(
        image_name="sweb.eval.demo:latest",
        setup_scripts={"setup.sh": "true"},
        dockerfile="FROM scratch\nCOPY setup.sh /setup.sh",
        platform="linux/x86_64",
        client=client,
        build_dir=Path(tmp_path),
    )

    assert api.build.call_count == 2
    logger.warning.assert_called_once()


def test_build_image_retries_transient_container_cleanup_race(monkeypatch, tmp_path):
    responses = [
        iter([{"errorDetail": {"message": "identifier is not a container"}}]),
        iter(
            [
                {
                    "errorDetail": {
                        "message": 'deleting build container "abc123": identifier is not a container'
                    }
                }
            ]
        ),
        iter([{"stream": "success\n"}]),
    ]
    api = SimpleNamespace(build=Mock(side_effect=responses))
    client = SimpleNamespace(api=api)
    logger = Mock()
    monkeypatch.setattr(docker_build, "setup_logger", lambda *_args: logger)
    monkeypatch.setattr(docker_build, "close_logger", lambda *_args: None)

    docker_build.build_image(
        image_name="sweb.eval.demo:latest",
        setup_scripts={"setup.sh": "true"},
        dockerfile="FROM scratch\nCOPY setup.sh /setup.sh",
        platform="linux/x86_64",
        client=client,
        build_dir=Path(tmp_path),
    )

    assert api.build.call_count == 3
    assert logger.warning.call_count == 2


def test_build_image_raises_after_exhausting_transient_retries(monkeypatch, tmp_path):
    responses = [
        iter([{"errorDetail": {"message": "identifier is not a container"}}]),
        iter([{"errorDetail": {"message": "identifier is not a container"}}]),
        iter([{"errorDetail": {"message": "identifier is not a container"}}]),
    ]
    api = SimpleNamespace(build=Mock(side_effect=responses))
    client = SimpleNamespace(api=api)
    logger = Mock()
    monkeypatch.setattr(docker_build, "setup_logger", lambda *_args: logger)
    monkeypatch.setattr(docker_build, "close_logger", lambda *_args: None)

    try:
        docker_build.build_image(
            image_name="sweb.eval.demo:latest",
            setup_scripts={"setup.sh": "true"},
            dockerfile="FROM scratch\nCOPY setup.sh /setup.sh",
            platform="linux/x86_64",
            client=client,
            build_dir=Path(tmp_path),
        )
        assert False, "expected BuildImageError"
    except docker_build.BuildImageError:
        pass

    assert api.build.call_count == 3


class _BlockingBuildResponse:
    def __init__(self):
        self.closed = threading.Event()

    def __iter__(self):
        self.closed.wait(5)
        return
        yield

    def close(self):
        self.closed.set()


def test_build_stream_emits_heartbeat_without_resetting_idle_timeout(monkeypatch):
    response = _BlockingBuildResponse()
    logger = Mock()
    monkeypatch.setattr(docker_build, "BUILD_HEARTBEAT_INTERVAL", 0.01)
    stream = docker_build._iter_with_build_timeouts(
        response,
        timeout=1,
        no_output_timeout=0.05,
        started_at=time.monotonic(),
        logger=logger,
    )

    try:
        next(stream)
        assert False, "expected BuildTimeoutError"
    except docker_build.BuildTimeoutError as error:
        assert error.reason == "no-output"

    assert any(
        call.args and "Build heartbeat" in call.args[0]
        for call in logger.info.call_args_list
    )


def test_build_image_no_output_timeout_closes_stream_and_records_diagnostics(tmp_path):
    response = _BlockingBuildResponse()
    client = SimpleNamespace(
        api=SimpleNamespace(build=Mock(return_value=response)),
        version=Mock(return_value={"Engine": "docker"}),
    )

    try:
        docker_build.build_image(
            image_name="sweb.eval.timeout:latest",
            setup_scripts={},
            dockerfile="FROM scratch",
            platform="linux/x86_64",
            client=client,
            build_dir=tmp_path,
            timeout=1,
            no_output_timeout=0.05,
        )
        assert False, "expected BuildImageError"
    except docker_build.BuildImageError as error:
        assert isinstance(error.__cause__, docker_build.BuildTimeoutError)
        assert error.__cause__.reason == "no-output"

    assert response.closed.is_set()
    diagnostics = json.loads((tmp_path / "build_diagnostics.json").read_text())
    assert diagnostics["status"] == "no-output_timeout"
    assert diagnostics["no_output_timeout_seconds"] == 0.05


def test_build_image_wallclock_timeout_wins_while_output_continues(tmp_path):
    class ChattyResponse:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            while not self.closed:
                time.sleep(0.005)
                yield {"stream": "still building\n"}

        def close(self):
            self.closed = True

    response = ChattyResponse()
    client = SimpleNamespace(
        api=SimpleNamespace(build=Mock(return_value=response)),
        version=Mock(return_value={"Engine": "docker"}),
    )

    try:
        docker_build.build_image(
            image_name="sweb.eval.wallclock:latest",
            setup_scripts={},
            dockerfile="FROM scratch",
            platform="linux/x86_64",
            client=client,
            build_dir=tmp_path,
            timeout=0.05,
            no_output_timeout=1,
        )
        assert False, "expected BuildImageError"
    except docker_build.BuildImageError as error:
        assert isinstance(error.__cause__, docker_build.BuildTimeoutError)
        assert error.__cause__.reason == "wall-clock"

    diagnostics = json.loads((tmp_path / "build_diagnostics.json").read_text())
    assert diagnostics["status"] == "wall-clock_timeout"


def test_podman_build_command_uses_selected_socket_and_no_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1000/podman/podman.sock")

    command = docker_build._podman_build_command(
        "sweb.eval.demo:latest", tmp_path, "linux/x86_64", True
    )

    assert command[:3] == [
        "podman",
        "--url",
        "unix:///run/user/1000/podman/podman.sock",
    ]
    assert command[-2:] == ["--no-cache", str(tmp_path)]
    assert command[command.index("--platform") + 1] == "linux/x86_64"


def test_podman_build_command_applies_memory_and_cpu_quota(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    command = docker_build._podman_build_command(
        "sweb.eval.demo:latest", tmp_path, "linux/x86_64", False, "24g", 6.5
    )

    assert command[command.index("--memory") + 1] == "24g"
    assert command[command.index("--cpu-period") + 1] == "100000"
    assert command[command.index("--cpu-quota") + 1] == "650000"


def test_native_podman_timeout_terminates_only_its_process_group(
    monkeypatch, tmp_path
):
    class BlockingStdout:
        def __init__(self):
            self.closed = threading.Event()

        def __iter__(self):
            self.closed.wait(5)
            return
            yield

        def close(self):
            self.closed.set()

    process = SimpleNamespace(
        pid=4321,
        stdout=BlockingStdout(),
        poll=Mock(return_value=None),
    )
    terminated = []
    monkeypatch.setattr(docker_build.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(
        docker_build,
        "_terminate_process_group",
        lambda candidate: terminated.append(candidate),
    )

    started_at = time.monotonic()
    try:
        docker_build._run_native_podman_build(
            image_name="sweb.eval.demo:latest",
            build_dir=tmp_path,
            platform="linux/x86_64",
            nocache=False,
            logger=Mock(),
            timeout=1,
            no_output_timeout=0.05,
            started_at=started_at,
        )
        assert False, "expected BuildTimeoutError"
    except docker_build.BuildTimeoutError as error:
        assert error.reason == "no-output"

    assert terminated == [process]
    assert process.stdout.closed.is_set()


def test_build_image_uses_native_podman_runner(monkeypatch, tmp_path):
    client = SimpleNamespace(
        api=SimpleNamespace(build=Mock()),
        version=Mock(return_value={"Platform": {"Name": "Podman Engine"}}),
    )
    native_build = Mock(return_value="success\n")
    monkeypatch.setattr(docker_build, "_run_native_podman_build", native_build)

    docker_build.build_image(
        image_name="sweb.eval.demo:latest",
        setup_scripts={},
        dockerfile="FROM scratch",
        platform="linux/x86_64",
        client=client,
        build_dir=tmp_path,
        timeout=123,
        no_output_timeout=45,
    )

    native_build.assert_called_once()
    client.api.build.assert_not_called()
    diagnostics = json.loads((tmp_path / "build_diagnostics.json").read_text())
    assert diagnostics["status"] == "success"


def test_qgis_instance_build_uses_single_build_lock(monkeypatch, tmp_path):
    class RecordingLock:
        def __init__(self):
            self.events = []

        def acquire(self):
            self.events.append("acquire")

        def release(self):
            self.events.append("release")

    lock = RecordingLock()
    spec = SimpleNamespace(
        repo="qgis/QGIS",
        instance_id="qgis__QGIS-1",
        instance_image_key="sweb.eval.qgis:latest",
        env_image_key="sweb.env.qgis:latest",
        instance_dockerfile="FROM env",
        install_repo_script="true",
        platform="linux/x86_64",
    )

    def get_image(name):
        if name == spec.env_image_key:
            return object()
        raise docker.errors.ImageNotFound("missing")

    client = SimpleNamespace(images=SimpleNamespace(get=get_image))
    build = Mock()
    monkeypatch.setattr(docker_build, "INSTANCE_IMAGE_BUILD_DIR", tmp_path)
    monkeypatch.setattr(docker_build, "_qgis_build_lock", lock)
    monkeypatch.setattr(docker_build, "build_image", build)

    docker_build.build_instance_image(spec, client, Mock(), False, 123, 45)

    assert lock.events == ["acquire", "release"]
    assert build.call_args.kwargs["timeout"] == 123
    assert build.call_args.kwargs["no_output_timeout"] == 45


def _spec(docker_specs=None):
    return SimpleNamespace(
        instance_id="demo__repo-1",
        instance_image_key="sweb.eval.demo:latest",
        docker_specs=docker_specs or {},
        platform="linux/x86_64",
        get_instance_container_name=lambda run_id: f"demo.{run_id}",
    )


def _client(containers=None, version=None):
    return SimpleNamespace(
        containers=containers or SimpleNamespace(create=Mock(return_value=object())),
        version=Mock(return_value=version or {"Engine": "docker"}),
    )


def test_create_eval_container_recovers_completed_timed_out_create(monkeypatch):
    created = object()
    containers = SimpleNamespace(
        create=Mock(side_effect=requests.exceptions.ReadTimeout("busy")),
        get=Mock(return_value=created),
    )
    monkeypatch.setattr("swebench.harness.docker_build.time.sleep", lambda _delay: None)

    result = _create_eval_container(
        SimpleNamespace(containers=containers), _spec(), "run", Mock()
    )

    assert result is created
    containers.create.assert_called_once()
    containers.get.assert_called_once_with("demo.run")


def test_create_eval_container_retries_when_timeout_did_not_create(monkeypatch):
    created = object()
    containers = SimpleNamespace(
        create=Mock(side_effect=[requests.exceptions.ReadTimeout("busy"), created]),
        get=Mock(side_effect=docker.errors.NotFound("missing")),
    )
    monkeypatch.setattr("swebench.harness.docker_build.time.sleep", lambda _delay: None)

    result = _create_eval_container(
        SimpleNamespace(containers=containers), _spec(), "run", Mock()
    )

    assert result is created
    assert containers.create.call_count == 2


def test_create_eval_container_without_gpu_request_omits_gpu_kwargs():
    client = _client()

    _create_eval_container(client, _spec(), "run", Mock())

    kwargs = client.containers.create.call_args.kwargs
    assert "device_requests" not in kwargs
    assert "devices" not in kwargs
    assert kwargs["network_disabled"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert "SETUID" in kwargs["cap_add"]
    assert "SETGID" in kwargs["cap_add"]
    assert "NET_RAW" not in kwargs["cap_add"]
    assert kwargs["mem_limit"] == "32g"
    assert kwargs["nano_cpus"] == 8_000_000_000
    assert kwargs["pids_limit"] == 2048


def test_eval_container_boundary_has_explicit_compatibility_overrides(monkeypatch):
    monkeypatch.setenv("SWEBENCH_EVAL_NETWORK_DISABLED", "0")
    monkeypatch.setenv("SWEBENCH_EVAL_HARDENING", "0")
    monkeypatch.setenv("SWEBENCH_EVAL_MEMORY", "0")
    monkeypatch.setenv("SWEBENCH_EVAL_CPUS", "0")
    monkeypatch.setenv("SWEBENCH_EVAL_PIDS_LIMIT", "-1")

    options = docker_build._eval_container_options()

    assert options == {"network_disabled": False}


def test_create_eval_container_requests_gpu_on_docker(monkeypatch):
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "4")
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", iter([0]))
    client = _client(version={"Engine": "docker"})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})

    _create_eval_container(client, spec, "run", Mock())

    kwargs = client.containers.create.call_args.kwargs
    assert "devices" not in kwargs
    [device_request] = kwargs["device_requests"]
    assert device_request["DeviceIDs"] == ["0"]
    assert device_request["Capabilities"] == [["gpu"]]


def test_create_eval_container_requests_gpu_on_podman(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "4")
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", iter([2]))
    client = _client(version={"Platform": {"Name": "Podman Engine"}})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})
    created = object()
    client.containers.get = Mock(return_value=created)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="id\n", stderr=""))
    monkeypatch.setattr(docker_build.subprocess, "run", run)

    result = _create_eval_container(client, spec, "run", Mock())

    assert result is created
    client.containers.create.assert_not_called()
    client.containers.get.assert_called_once_with("demo.run")
    command = run.call_args.args[0]
    assert command[:2] == ["podman", "create"]
    assert command[command.index("--device") + 1] == "nvidia.com/gpu=2"
    assert command[command.index("--security-opt") + 1] == "label=disable"
    assert command[command.index("--network") + 1] == "none"
    assert "ALL" in command
    assert "no-new-privileges:true" in command
    assert command[command.index("--memory") + 1] == "32g"
    assert command[command.index("--cpus") + 1] == "8.0"
    assert command[command.index("--pids-limit") + 1] == "2048"


def test_create_eval_container_detects_podman_via_docker_host(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1000/podman/podman.sock")
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "4")
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", iter([1]))
    client = _client(version={"Engine": "docker"})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})
    created = object()
    client.containers.get = Mock(return_value=created)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="id\n", stderr=""))
    monkeypatch.setattr(docker_build.subprocess, "run", run)

    result = _create_eval_container(client, spec, "run", Mock())

    assert result is created
    command = run.call_args.args[0]
    assert command[:3] == [
        "podman",
        "--url",
        "unix:///run/user/1000/podman/podman.sock",
    ]
    assert command[command.index("--device") + 1] == "nvidia.com/gpu=1"


def test_create_eval_container_reports_podman_cli_failure(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "1")
    client = _client(version={"Platform": {"Name": "Podman Engine"}})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})
    monkeypatch.setattr(
        docker_build.subprocess,
        "run",
        Mock(
            return_value=SimpleNamespace(
                returncode=125,
                stdout="",
                stderr="Error: unresolvable CDI device nvidia.com/gpu=0\n",
            )
        ),
    )

    try:
        _create_eval_container(client, spec, "run", Mock())
        assert False, "expected Podman create failure"
    except RuntimeError as error:
        assert "unresolvable CDI device" in str(error)

    client.containers.create.assert_not_called()


def test_create_eval_container_logs_gpu_details_on_api_error(monkeypatch):
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "4")
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", iter([3]))
    error = docker.errors.APIError("no such device")
    error.response = SimpleNamespace(status_code=500)
    containers = SimpleNamespace(create=Mock(side_effect=error))
    client = _client(containers=containers, version={"Engine": "docker"})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})
    logger = Mock()

    try:
        _create_eval_container(client, spec, "run", logger)
        assert False, "expected docker.errors.APIError to propagate"
    except docker.errors.APIError:
        pass

    logger.error.assert_called_once()
    log_args = logger.error.call_args.args
    assert "GPU container create failed" in log_args[0]
    assert spec.instance_id in log_args
    assert 3 in log_args


def test_create_eval_container_gpu_assignment_round_robins_across_cards(monkeypatch):
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "4")
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", itertools.count())
    client = _client(version={"Engine": "docker"})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})

    assigned = []
    for _ in range(6):
        _create_eval_container(client, spec, "run", Mock())
        [device_request] = client.containers.create.call_args.kwargs["device_requests"]
        assigned.append(device_request["DeviceIDs"][0])

    assert assigned == ["0", "1", "2", "3", "0", "1"]


def test_force_instance_rebuild_can_preserve_prebuilt_environment(monkeypatch):
    spec = SimpleNamespace(
        instance_image_key="sweb.eval.demo:latest",
        env_image_key="sweb.env.demo:latest",
    )
    removed = []
    env_calls = []
    payloads_seen = []
    monkeypatch.setattr(docker_build, "make_test_spec", lambda *args, **kwargs: spec)
    monkeypatch.setattr(
        docker_build,
        "remove_image",
        lambda _client, image, _logger: removed.append(image),
    )
    monkeypatch.setattr(
        docker_build,
        "build_env_images",
        lambda _client, _specs, force, workers, **_kwargs: env_calls.append((force, workers))
        or ([], []),
    )

    def fake_threadpool(_func, payloads, _workers):
        payloads_seen.extend(payloads)
        return payloads, []

    monkeypatch.setattr(docker_build, "run_threadpool", fake_threadpool)

    client = object()
    successful, failed = docker_build.build_instance_images(
        client=client,
        dataset=[{"instance_id": "demo__repo-1"}],
        force_rebuild=True,
        force_rebuild_env=False,
        nocache=True,
        max_workers=2,
    )

    assert removed == ["sweb.eval.demo:latest"]
    assert env_calls == [(False, 2)]
    assert payloads_seen == [(spec, client, None, True, None, None, None, None)]
    assert successful == payloads_seen
    assert failed == []


def test_failed_environment_payload_excludes_dependent_instances(monkeypatch):
    spec = SimpleNamespace(
        instance_image_key="sweb.eval.demo:latest",
        env_image_key="sweb.env.demo:latest",
    )
    monkeypatch.setattr(docker_build, "make_test_spec", lambda *args, **kwargs: spec)
    monkeypatch.setattr(
        docker_build,
        "build_env_images",
        lambda *_args, **_kwargs: (
            [],
            [("sweb.env.demo:latest", {}, "Dockerfile", "linux/x86_64")],
        ),
    )
    payloads_seen = []

    def fake_threadpool(_func, payloads, _workers):
        payloads_seen.extend(payloads)
        return payloads, []

    monkeypatch.setattr(docker_build, "run_threadpool", fake_threadpool)

    successful, failed = docker_build.build_instance_images(
        client=object(),
        dataset=[{"instance_id": "demo__repo-1"}],
    )

    assert payloads_seen == []
    assert successful == []
    assert failed == []


def test_next_gpu_index_round_robins_across_gpu_count(monkeypatch):
    from swebench.harness.docker_build import _next_gpu_index

    # Reset the counter to a known state
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", itertools.count())

    # Call _next_gpu_index 30 times with gpu_count=3
    indices = [_next_gpu_index(3) for _ in range(30)]

    # Verify that all three GPU indices (0, 1, 2) are used
    assert len(set(indices)) == 3, f"Expected all 3 GPU indices to be used, got {set(indices)}"

    # Verify round-robin pattern: for every gpu_count calls, we should see each index once
    for i in range(0, 30, 3):
        batch = indices[i : i + 3]
        assert len(set(batch)) == 3, f"Batch {batch} does not contain all 3 indices"
