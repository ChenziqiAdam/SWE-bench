import json
from types import SimpleNamespace
from unittest.mock import Mock

import docker

from swebench.eval_pipeline import validate_base


def _instance(instance_id, repo="demo/repo", version="1.0"):
    return {"instance_id": instance_id, "repo": repo, "version": version}


def _spec(instance_id):
    return SimpleNamespace(
        instance_id=instance_id,
        env_image_key=f"sweb.env.{instance_id}:latest",
        instance_image_key=f"sweb.eval.{instance_id}:latest",
        setup_env_script="",
        install_repo_script="",
        eval_script="",
    )


def _setup_common(monkeypatch, instances, *, instance_image_exists):
    specs = {inst["instance_id"]: _spec(inst["instance_id"]) for inst in instances}
    monkeypatch.setattr(validate_base, "make_test_spec", lambda inst: specs[inst["instance_id"]])
    monkeypatch.setattr(
        validate_base,
        "MAP_REPO_VERSION_TO_SPECS",
        {"demo/repo": {"1.0": {}}},
    )
    monkeypatch.setattr(validate_base, "build_env_images", lambda **kwargs: ([], []))

    # Simulate build_instance_images reporting a failure for every instance,
    # mirroring a thread-pool race where the underlying build actually
    # succeeded (image exists) but the pool bucketed it as failed anyway.
    def fake_build_instance_images(**kwargs):
        return [], list(specs.values())

    monkeypatch.setattr(validate_base, "build_instance_images", fake_build_instance_images)

    def fake_images_get(image_key):
        if instance_image_exists:
            return object()
        raise docker.errors.ImageNotFound("not found")

    client = SimpleNamespace(
        ping=lambda: None,
        close=lambda: None,
        images=SimpleNamespace(get=fake_images_get, remove=Mock()),
    )
    monkeypatch.setattr(validate_base.docker, "from_env", lambda: client)
    return client


def test_false_negative_build_is_recovered_when_image_exists(monkeypatch, tmp_path):
    instances = [_instance("demo__repo-1")]
    _setup_common(monkeypatch, instances, instance_image_exists=True)

    cache_path = tmp_path / "build_validation.json"
    result = validate_base.validate_buildable(instances, cache_path, max_workers=1)

    assert result["demo__repo-1"]["buildable"] is True
    assert result["demo__repo-1"]["error"] == ""


def test_real_build_failure_stays_unbuildable_when_image_missing(monkeypatch, tmp_path):
    instances = [_instance("demo__repo-1")]
    _setup_common(monkeypatch, instances, instance_image_exists=False)

    cache_path = tmp_path / "build_validation.json"
    result = validate_base.validate_buildable(instances, cache_path, max_workers=1)

    assert result["demo__repo-1"]["buildable"] is False


def test_smoke_validate_retries_transient_no_such_container_race(monkeypatch):
    calls = []

    class FakeExc(Exception):
        stderr = b"404 Client Error ...: no such container"

    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise FakeExc("no such container")
        return None

    client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    ok, error = validate_base._smoke_validate_image(client, "demo:latest", "python -c 'import demo'")

    assert ok is True
    assert error == ""
    assert len(calls) == 3


def test_smoke_validate_raises_after_exhausting_transient_retries(monkeypatch):
    calls = []

    class FakeExc(Exception):
        stderr = b"404 Client Error ...: no such container"

    def fake_run(*args, **kwargs):
        calls.append(1)
        raise FakeExc("no such container")

    client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    ok, error = validate_base._smoke_validate_image(client, "demo:latest", "python -c 'import demo'")

    assert ok is False
    assert "no such container" in error.lower()
    assert len(calls) == 3


def test_smoke_validate_does_not_retry_real_failure(monkeypatch):
    calls = []

    class FakeExc(Exception):
        stderr = b"ModuleNotFoundError: No module named 'sklearn'"

    def fake_run(*args, **kwargs):
        calls.append(1)
        raise FakeExc("import error")

    client = SimpleNamespace(containers=SimpleNamespace(run=fake_run))
    ok, error = validate_base._smoke_validate_image(client, "demo:latest", "python -c 'import demo'")

    assert ok is False
    assert "sklearn" in error
    assert len(calls) == 1


def test_read_build_diagnostics_returns_structured_timeout(monkeypatch, tmp_path):
    spec = _spec("demo__repo-1")
    build_dir = tmp_path / spec.instance_image_key.replace(":", "__")
    build_dir.mkdir(parents=True)
    expected = {
        "status": "no-output_timeout",
        "elapsed_seconds": 2700.1,
        "no_output_timeout_seconds": 2700,
    }
    (build_dir / "build_diagnostics.json").write_text(json.dumps(expected))
    monkeypatch.setattr(validate_base, "INSTANCE_IMAGE_BUILD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(
        "swebench.harness.docker_build.INSTANCE_IMAGE_BUILD_DIR", tmp_path
    )

    assert validate_base._read_build_diagnostics(spec) == expected
