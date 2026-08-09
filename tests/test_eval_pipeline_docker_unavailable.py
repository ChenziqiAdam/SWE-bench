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


def test_post_build_validation_reports_import_failure():
    class Containers:
        def run(self, image, command, remove):
            assert image == "instance:latest"
            assert command[:2] == ["/bin/bash", "-lc"]
            assert remove is True
            raise docker.errors.ContainerError(
                container=None,
                exit_status=1,
                command=command,
                image=image,
                stderr=b"ModuleNotFoundError: No module named 'dependency'",
            )

    client = type("Client", (), {"containers": Containers()})()
    ok, error = validate_base._smoke_validate_image(
        client, "instance:latest", "python -c 'import package'"
    )

    assert ok is False
    assert "post-build validation failed" in error
    assert "ModuleNotFoundError" in error


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


def test_clean_validation_batches_and_removes_instance_images(monkeypatch, tmp_path):
    instances = [
        {"instance_id": f"repo__pkg-{i}", "repo": "repo/pkg", "version": "v1"}
        for i in range(5)
    ]
    specs = {
        inst["instance_id"]: type(
            "Spec",
            (),
            {
                "instance_id": inst["instance_id"],
                "env_image_key": "env:v1",
                "instance_image_key": f"image:{i}",
            },
        )()
        for i, inst in enumerate(instances)
    }
    removed = []
    batches = []

    class Images:
        def remove(self, name, force=False):
            removed.append((name, force))

    class Client:
        images = Images()

        def ping(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(validate_base, "_spec_hash", lambda _: "hash")
    monkeypatch.setattr(
        validate_base, "MAP_REPO_VERSION_TO_SPECS", {"repo/pkg": {"v1": {}}}
    )
    monkeypatch.setattr(
        validate_base, "make_test_spec", lambda inst: specs[inst["instance_id"]]
    )
    monkeypatch.setattr(validate_base.docker, "from_env", lambda: Client())
    monkeypatch.setattr(
        validate_base,
        "build_env_images",
        lambda **_kwargs: ([], []),
    )

    def build_instances(**kwargs):
        batch = kwargs["dataset"]
        batches.append([inst["instance_id"] for inst in batch])
        return ([(specs[inst["instance_id"]],) for inst in batch], [])

    monkeypatch.setattr(validate_base, "build_instance_images", build_instances)

    result = validate_base.validate_buildable(
        instances,
        cache_path=tmp_path / "validation.json",
        max_workers=2,
        clean_images=True,
    )

    assert list(map(len, batches)) == [2, 2, 1]
    assert len(removed) == 5
    assert all(value["buildable"] for value in result.values())


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
