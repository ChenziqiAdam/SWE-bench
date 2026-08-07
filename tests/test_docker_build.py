import itertools
from types import SimpleNamespace
from unittest.mock import Mock

import docker
import requests

from swebench.harness import docker_build
from swebench.harness.docker_build import _create_eval_container


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

    _create_eval_container(client, spec, "run", Mock())

    kwargs = client.containers.create.call_args.kwargs
    assert "device_requests" not in kwargs
    assert kwargs["devices"] == ["nvidia.com/gpu=2"]


def test_create_eval_container_detects_podman_via_docker_host(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/1000/podman/podman.sock")
    monkeypatch.setenv("SWEBENCH_GPU_COUNT", "4")
    monkeypatch.setattr(docker_build, "_gpu_assignment_counter", iter([1]))
    client = _client(version={"Engine": "docker"})
    spec = _spec(docker_specs={"run_args": {"gpu": True}})

    _create_eval_container(client, spec, "run", Mock())

    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["devices"] == ["nvidia.com/gpu=1"]


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
        lambda _client, _specs, force, workers: env_calls.append((force, workers))
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
    assert payloads_seen == [(spec, client, None, True)]
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
