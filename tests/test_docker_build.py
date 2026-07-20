from types import SimpleNamespace
from unittest.mock import Mock

import docker
import requests

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
