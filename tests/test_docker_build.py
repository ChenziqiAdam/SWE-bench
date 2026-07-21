from types import SimpleNamespace
from unittest.mock import Mock

import docker
import requests

from swebench.harness import docker_build
from swebench.harness.docker_build import _create_eval_container


def _spec():
    return SimpleNamespace(
        instance_id="demo__repo-1",
        instance_image_key="sweb.eval.demo:latest",
        docker_specs={},
        platform="linux/x86_64",
        get_instance_container_name=lambda run_id: f"demo.{run_id}",
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
