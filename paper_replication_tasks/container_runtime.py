"""Rootless Podman runtime with no network except a loopback model relay."""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import docker
import docker.errors

from swebench.eval_pipeline.linux_network_guard import (
    _loopback_target,
    _serve_host_relay,
)


class ContainerRuntimeError(RuntimeError):
    """The formal Podman boundary could not be established."""


def podman_client() -> docker.DockerClient:
    if not os.environ.get("DOCKER_HOST"):
        raise ContainerRuntimeError(
            "DOCKER_HOST must point to the rootless Podman API socket"
        )
    try:
        client = docker.from_env()
        client.ping()
        version = client.version()
    except docker.errors.DockerException as exc:
        raise ContainerRuntimeError(
            "cannot connect to the Podman Docker-compatible API"
        ) from exc
    text = str(version).lower()
    if "podman" not in text:
        client.close()
        raise ContainerRuntimeError(
            "the configured container API is not identified as Podman"
        )
    return client


def local_image_identity(client: docker.DockerClient, image_name: str) -> dict[str, Any]:
    try:
        image = client.images.get(image_name)
    except docker.errors.ImageNotFound as exc:
        raise ContainerRuntimeError(
            f"container image is not present locally: {image_name}; "
            "formal runs never pull images"
        ) from exc
    except docker.errors.DockerException as exc:
        raise ContainerRuntimeError(f"cannot inspect image {image_name!r}") from exc
    digests = (image.attrs or {}).get("RepoDigests") or []
    return {
        "name": image_name,
        "id": image.id,
        "digest": digests[0] if digests else image.id,
    }


def _decode_logs(container: Any, *, stdout: bool, stderr: bool) -> str:
    try:
        data = container.logs(stdout=stdout, stderr=stderr)
    except docker.errors.DockerException:
        return ""
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return str(data or "")


def _wait_for_container(container: Any, timeout: float) -> tuple[int, bool]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container.reload()
        if container.status not in {"created", "running", "restarting"}:
            result = container.wait(timeout=10)
            return int(result.get("StatusCode", 1)), False
        time.sleep(0.2)
    try:
        container.kill()
    except docker.errors.DockerException:
        pass
    return 124, True


def run_podman_container(
    *,
    client: docker.DockerClient,
    image: str,
    command: list[str],
    workspace: Path,
    runtime_dir: Path,
    runtime_home: Path,
    environment: dict[str, str],
    timeout: float,
    container_python: str,
    gateway_endpoint: str | None,
    memory: str | None,
    cpus: float | None,
    pids_limit: int,
    tmpfs_size: str,
) -> dict[str, Any]:
    """Run one ephemeral, unprivileged, read-only-root Podman container."""
    workspace = workspace.resolve()
    runtime_dir = runtime_dir.resolve()
    runtime_home = runtime_home.resolve()
    runtime_home.mkdir(parents=True, exist_ok=True)
    relay_root: Path | None = None
    listener: socket.socket | None = None
    relay_thread: threading.Thread | None = None
    stop = threading.Event()
    container = None
    started = time.perf_counter()
    try:
        volumes = {
            str(workspace): {"bind": "/workspace", "mode": "rw,Z"},
            str(runtime_dir): {"bind": "/runner", "mode": "ro,Z"},
            str(runtime_home): {"bind": "/agent-home", "mode": "rw,Z"},
        }
        effective_command = list(command)
        if gateway_endpoint:
            target = _loopback_target(gateway_endpoint)
            relay_root = Path(tempfile.mkdtemp(prefix="paper-replication-relay-"))
            relay_path = relay_root / "relay"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(relay_path))
            listener.listen(32)
            relay_thread = threading.Thread(
                target=_serve_host_relay,
                args=(listener, target, stop),
                daemon=True,
            )
            relay_thread.start()
            volumes[str(relay_root)] = {"bind": "/gateway", "mode": "rw,Z"}
            effective_command = [
                container_python,
                "/runner/container_proxy.py",
                "/gateway/relay",
                str(target[1]),
                "--",
                *effective_command,
            ]

        kwargs: dict[str, Any] = {
            "image": image,
            "command": effective_command,
            "entrypoint": [],
            "detach": True,
            "network_disabled": True,
            "network_mode": "none",
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            # Use rootless Podman's default mapping. Through the Docker-compatible
            # API, docker-py rejects Podman's otherwise valid ``keep-id`` value
            # before sending the request. Container UID 0 remains mapped to the
            # unprivileged user running the rootless Podman service.
            "working_dir": "/workspace",
            "volumes": volumes,
            "environment": environment,
            "pids_limit": pids_limit,
            "tmpfs": {
                "/tmp": f"rw,noexec,nosuid,nodev,size={tmpfs_size}",
                "/run": "rw,noexec,nosuid,nodev,size=64m",
            },
            "stdin_open": False,
            "tty": False,
            "privileged": False,
        }
        if memory:
            kwargs["mem_limit"] = memory
        if cpus:
            kwargs["nano_cpus"] = int(cpus * 1_000_000_000)
        container = client.containers.run(**kwargs)
        exit_code, timed_out = _wait_for_container(container, timeout)
        return {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": _decode_logs(container, stdout=True, stderr=False),
            "stderr": _decode_logs(container, stdout=False, stderr=True),
            "wall_time_seconds": round(time.perf_counter() - started, 6),
            "container_id": container.id,
        }
    except docker.errors.DockerException as exc:
        raise ContainerRuntimeError(f"Podman container failed: {exc}") from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass
        stop.set()
        if listener is not None:
            listener.close()
        if relay_thread is not None:
            relay_thread.join(timeout=1)
        if relay_root is not None:
            shutil.rmtree(relay_root, ignore_errors=True)
