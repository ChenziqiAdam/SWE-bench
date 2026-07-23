import json

import docker

from swebench.eval_pipeline import mine_tests, run_pipeline, validate_base


def test_docker_preflight_pings_daemon_and_reports_failure(monkeypatch):
    class DeadClient:
        def ping(self):
            raise docker.errors.DockerException("daemon did not start")

        def close(self):
            pass

    monkeypatch.setattr(docker, "from_env", lambda: DeadClient())

    reason = run_pipeline._docker_unavailable_reason()

    assert "Docker daemon unavailable" in reason
    assert "daemon did not start" in reason


def test_validate_buildable_caches_docker_unavailable(monkeypatch, tmp_path):
    inst = {"instance_id": "repo__pkg-1", "repo": "repo/pkg", "version": "v1"}

    monkeypatch.setattr(validate_base, "_spec_hash", lambda _: "hash1")
    monkeypatch.setattr(validate_base, "MAP_REPO_VERSION_TO_SPECS", {"repo/pkg": {"v1": {}}})
    monkeypatch.setattr(
        validate_base.docker,
        "from_env",
        lambda: (_ for _ in ()).throw(docker.errors.DockerException("connection refused")),
    )

    cache_path = tmp_path / "build_validation.json"
    result = validate_base.validate_buildable([inst], cache_path=cache_path)

    assert result["repo__pkg-1"]["buildable"] is False
    assert "Docker daemon unavailable" in result["repo__pkg-1"]["error"]
    assert json.loads(cache_path.read_text()) == result


def test_forced_validation_preserves_unselected_cached_results(monkeypatch, tmp_path):
    selected = {
        "instance_id": "repo__pkg-1",
        "repo": "repo/pkg",
        "version": "v1",
    }
    retained = {
        "buildable": False,
        "error": "historical build failure",
        "spec_hash": "other-hash",
    }
    cache_path = tmp_path / "build_validation.json"
    cache_path.write_text(
        json.dumps(
            {
                selected["instance_id"]: {
                    "buildable": True,
                    "error": "",
                    "spec_hash": "old-hash",
                },
                "repo__pkg-2": retained,
            }
        )
    )

    monkeypatch.setattr(validate_base, "_spec_hash", lambda _: "new-hash")
    monkeypatch.setattr(
        validate_base,
        "MAP_REPO_VERSION_TO_SPECS",
        {"repo/pkg": {"v1": {}}},
    )
    monkeypatch.setattr(
        validate_base.docker,
        "from_env",
        lambda: (_ for _ in ()).throw(
            docker.errors.DockerException("connection refused")
        ),
    )

    result = validate_base.validate_buildable(
        [selected],
        cache_path=cache_path,
        force=True,
    )

    assert result["repo__pkg-2"] == retained
    assert result[selected["instance_id"]]["buildable"] is False
    assert json.loads(cache_path.read_text()) == result


def test_mine_fail_to_pass_caches_docker_unavailable(monkeypatch, tmp_path):
    inst = {
        "instance_id": "repo__pkg-1",
        "repo": "repo/pkg",
        "version": "v1",
        "test_patch": "diff --git a/test.py b/test.py\n",
    }
    monkeypatch.setattr(
        mine_tests.docker,
        "from_env",
        lambda: (_ for _ in ()).throw(docker.errors.DockerException("connection refused")),
    )

    cache_path = tmp_path / "test_mining.json"
    result = mine_tests.mine_fail_to_pass([inst], cache_path=cache_path)

    assert result["repo__pkg-1"]["ok"] is False
    assert "Docker daemon unavailable" in result["repo__pkg-1"]["error"]
    assert json.loads(cache_path.read_text()) == result
