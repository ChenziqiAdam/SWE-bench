import logging
from types import SimpleNamespace
from unittest import mock

import pytest

from swebench.harness import docker_build


def _log():
    lg = logging.getLogger("t")
    lg.log_file = "t.log"
    return lg


def _spec():
    return SimpleNamespace(
        instance_id="x__x-1",
        instance_image_key="sweb.eval.x86_64.x__x-1:latest",
        is_remote_image=False,
    )


def test_container_creation_retries_when_image_vanishes():
    calls = {"build": 0, "create": 0}

    def fake_create(client, spec, run_id, logger):
        calls["create"] += 1
        if calls["create"] == 1:
            raise RuntimeError('404 Not Found ("no such image: ...: image not known")')
        return SimpleNamespace(id="cid")

    with mock.patch.object(docker_build, "build_instance_image", side_effect=lambda *a: calls.__setitem__("build", calls["build"] + 1)), \
         mock.patch.object(docker_build, "_create_eval_container", side_effect=fake_create), \
         mock.patch.object(docker_build, "cleanup_container"):
        out = docker_build.build_container(_spec(), None, "r", _log(), nocache=False)
    assert out.id == "cid"
    assert calls == {"build": 2, "create": 2}


def test_non_image_errors_are_not_retried():
    with mock.patch.object(docker_build, "build_instance_image"), \
         mock.patch.object(docker_build, "_create_eval_container", side_effect=RuntimeError("boom")) as create, \
         mock.patch.object(docker_build, "cleanup_container"):
        with pytest.raises(docker_build.BuildImageError):
            docker_build.build_container(_spec(), None, "r", _log(), nocache=False)
    assert create.call_count == 1
