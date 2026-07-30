"""Container-backed command runner used by C++ coverage-generation agents."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

import docker
import docker.errors
import requests


def _command(config: dict, action: str, extra: list[str]) -> str:
    if action == "build":
        command = config["setup"]
    elif action == "test" and extra:
        command = "ctest --test-dir build --output-on-failure " + " ".join(
            shlex.quote(value) for value in extra
        )
    elif action == "test":
        command = config["test"]
    elif action == "coverage":
        command = " && ".join(
            (config["reset"], config["coverage"], config["report"])
        )
    else:
        raise ValueError(
            "usage: coverage-runner {build|test [-- CTest args]|coverage}"
        )
    return f"set -o pipefail; {command}"


def run(config_path: Path, action: str, extra: list[str]) -> int:
    config = json.loads(config_path.read_text())
    repo_dir = config_path.parent.parent.resolve()
    client = docker.from_env()
    container = None
    try:
        image_name = config["image"]
        client.images.get(image_name)
        options = {
            "detach": True,
            "network_disabled": True,
            "user": f"{os.getuid()}:{os.getgid()}",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "working_dir": "/workspace",
            "volumes": {
                str(repo_dir): {"bind": "/workspace", "mode": "rw"},
            },
        }
        try:
            engine_identity = json.dumps(client.version()).lower()
        except (AttributeError, docker.errors.DockerException):
            engine_identity = ""
        if "podman" in engine_identity or "podman" in os.environ.get(
            "DOCKER_HOST", ""
        ).lower():
            options["user"] = "0:0"
            options["userns_mode"] = "host"
        command = _command(config, action, extra)
        container = client.containers.run(
            image_name, ["/bin/bash", "-c", command], **options
        )
        timeout = int(config.get("timeout", 14400))
        try:
            status = container.wait(timeout=timeout)
        except (requests.exceptions.ReadTimeout, TimeoutError):
            container.kill()
            print(f"coverage-runner timed out after {timeout}s", file=sys.stderr)
            return 124
        output = container.logs(stdout=True, stderr=True)
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        sys.stdout.write(output or "")
        return int((status or {}).get("StatusCode", 1))
    except docker.errors.ImageNotFound:
        print(
            f"C++ evaluator image is not available locally: {config.get('image', '')}",
            file=sys.stderr,
        )
        return 125
    except (docker.errors.DockerException, OSError, ValueError, KeyError) as exc:
        print(f"coverage-runner failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 125
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("action")
    parser.add_argument("extra", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    extra = args.extra[1:] if args.extra[:1] == ["--"] else args.extra
    raise SystemExit(run(args.config, args.action, extra))


if __name__ == "__main__":
    main()
