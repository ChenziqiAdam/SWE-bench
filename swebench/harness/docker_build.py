from __future__ import annotations

import docker
import docker.errors
import docker.types
import itertools
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback

import requests

from pathlib import Path

from swebench.harness.constants import (
    BASE_IMAGE_BUILD_DIR,
    DOCKER_USER,
    ENV_IMAGE_BUILD_DIR,
    INSTANCE_IMAGE_BUILD_DIR,
    UTF8,
)
from swebench.harness.docker_utils import cleanup_container, remove_image
from swebench.harness.test_spec.test_spec import (
    get_test_specs_from_dataset,
    make_test_spec,
    TestSpec,
)
from swebench.harness.utils import ansi_escape, run_threadpool


class BuildImageError(Exception):
    def __init__(self, image_name, message, logger):
        super().__init__(message)
        self.super_str = super().__str__()
        self.image_name = image_name
        self.log_path = logger.log_file
        self.logger = logger

    def __str__(self):
        return (
            f"Error building image {self.image_name}: {self.super_str}\n"
            f"Check ({self.log_path}) for more information."
        )


def _client_is_podman(client) -> bool:
    """Detect a Podman-backed docker-py client (rootless Podman's Docker-compatible API)."""
    try:
        engine_identity = json.dumps(client.version()).lower()
    except (AttributeError, docker.errors.DockerException):
        engine_identity = ""
    docker_host = os.environ.get("DOCKER_HOST", "").lower()
    return "podman" in engine_identity or "podman" in docker_host


_gpu_assignment_counter = itertools.count()
_gpu_assignment_lock = threading.Lock()


def _next_gpu_index(gpu_count: int) -> int:
    """Round-robin the next GPU index, so concurrent eval containers spread
    across the host's GPUs instead of all landing on every card at once."""
    with _gpu_assignment_lock:
        return next(_gpu_assignment_counter) % gpu_count


def _create_podman_gpu_container(
    client,
    test_spec: TestSpec,
    name: str,
    run_args: dict,
    gpu_index: int,
):
    """Create a CDI-backed GPU container through Podman's native CLI.

    docker-py serializes its ``devices`` argument as Docker
    ``HostConfig.Devices`` entries.  Podman's Docker-compatible endpoint then
    treats a CDI name such as ``nvidia.com/gpu=0`` as a host filesystem path
    instead of resolving it as CDI.  Podman's native ``--device`` parser does
    resolve CDI device names, so use it for this one Podman-specific case.
    """
    command = ["podman"]
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host:
        # Keep the CLI on the same Podman service selected by docker.from_env().
        command.extend(["--url", docker_host])
    command.extend(
        [
            "create",
            "--name",
            name,
            "--user",
            DOCKER_USER,
            "--platform",
            test_spec.platform,
            "--device",
            f"nvidia.com/gpu={gpu_index}",
            "--security-opt",
            "label=disable",
        ]
    )
    for capability in run_args.get("cap_add", []):
        command.extend(["--cap-add", capability])
    command.extend([test_spec.instance_image_key, "tail", "-f", "/dev/null"])

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "Podman-backed GPU evaluation requires the podman CLI, but it was "
            "not found on PATH"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"Podman failed to create GPU container {name} "
            f"(exit {completed.returncode}): {detail}"
        )
    return client.containers.get(name)


def _create_eval_container(client, test_spec: TestSpec, run_id: str, logger):
    """Create an eval container, recovering when a loaded daemon answers late."""
    run_args = test_spec.docker_specs.get("run_args", {})
    name = test_spec.get_instance_container_name(run_id)
    kwargs = {
        "image": test_spec.instance_image_key,
        "name": name,
        "user": DOCKER_USER,
        "detach": True,
        "command": "tail -f /dev/null",
        "platform": test_spec.platform,
        "cap_add": run_args.get("cap_add", []),
    }
    requests_gpu = run_args.get("gpu", False)
    is_podman = _client_is_podman(client)
    if requests_gpu:
        if "SWEBENCH_GPU_COUNT" not in os.environ:
            logger.warning(
                "SWEBENCH_GPU_COUNT is not set for a GPU-requesting spec (%s); "
                "GPU assignment will default to a single GPU (index 0) instead "
                "of spreading concurrent eval containers across the host's "
                "GPUs. Export SWEBENCH_GPU_COUNT to the number of GPUs "
                "available on this host for multi-GPU hosts.",
                test_spec.instance_id,
            )
        gpu_count = int(os.environ.get("SWEBENCH_GPU_COUNT", "1"))
        gpu_index = _next_gpu_index(gpu_count)
        if not is_podman:
            kwargs["device_requests"] = [
                docker.types.DeviceRequest(
                    device_ids=[str(gpu_index)], capabilities=[["gpu"]]
                )
            ]
        logger.info(
            "Assigning GPU %s to %s (engine=%s, SWEBENCH_GPU_COUNT=%s)",
            gpu_index,
            test_spec.instance_id,
            "podman" if is_podman else "docker",
            gpu_count,
        )
    if requests_gpu and is_podman:
        return _create_podman_gpu_container(
            client, test_spec, name, run_args, gpu_index
        )
    for attempt in range(1, 4):
        try:
            return client.containers.create(**kwargs)
        except requests.exceptions.Timeout:
            logger.warning(
                "Docker create timed out for %s (attempt %s/3); checking whether "
                "the daemon completed it asynchronously.",
                test_spec.instance_id,
                attempt,
            )
            time.sleep(2 * attempt)
            try:
                return client.containers.get(name)
            except (docker.errors.NotFound, requests.exceptions.Timeout):
                if attempt == 3:
                    raise
        except docker.errors.APIError as error:
            if error.status_code != 409:
                if requests_gpu:
                    logger.error(
                        "GPU container create failed for %s (gpu=%s, "
                        "devices=%s, device_requests=%s): %s. Verify the host "
                        "has a GPU at that index and the NVIDIA Container "
                        "Toolkit / CDI is configured for this container engine.",
                        test_spec.instance_id,
                        gpu_index,
                        kwargs.get("devices"),
                        kwargs.get("device_requests"),
                        error,
                    )
                raise
            # A create request that timed out can still complete server-side and
            # make the retry report a name conflict.
            return client.containers.get(name)
    raise RuntimeError(f"Could not create container {name}")


def setup_logger(instance_id: str, log_file: Path, mode="w", add_stdout: bool = False):
    """
    This logger is used for logging the build process of images and containers.
    It writes logs to the log file.

    If `add_stdout` is True, logs will also be sent to stdout, which can be used for
    streaming ephemeral output from Modal containers.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"{instance_id}.{log_file.name}")
    handler = logging.FileHandler(log_file, mode=mode, encoding=UTF8)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    setattr(logger, "log_file", log_file)
    if add_stdout:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            f"%(asctime)s - {instance_id} - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def close_logger(logger):
    # To avoid too many open files
    for handler in logger.handlers:
        handler.close()
        logger.removeHandler(handler)


def build_image(
    image_name: str,
    setup_scripts: dict,
    dockerfile: str,
    platform: str,
    client: docker.DockerClient,
    build_dir: Path,
    nocache: bool = False,
):
    """
    Builds a docker image with the given name, setup scripts, dockerfile, and platform.

    Args:
        image_name (str): Name of the image to build
        setup_scripts (dict): Dictionary of setup script names to setup script contents
        dockerfile (str): Contents of the Dockerfile
        platform (str): Platform to build the image for
        client (docker.DockerClient): Docker client to use for building the image
        build_dir (Path): Directory for the build context (will also contain logs, scripts, and artifacts)
        nocache (bool): Whether to use the cache when building
    """
    # Create a logger for the build process
    logger = setup_logger(image_name, build_dir / "build_image.log")
    logger.info(
        f"Building image {image_name}\n"
        f"Using dockerfile:\n{dockerfile}\n"
        f"Adding ({len(setup_scripts)}) setup scripts to image build repo"
    )

    for setup_script_name, setup_script in setup_scripts.items():
        logger.info(f"[SETUP SCRIPT] {setup_script_name}:\n{setup_script}")
    response = None
    try:
        # Write the setup scripts to the build directory
        for setup_script_name, setup_script in setup_scripts.items():
            setup_script_path = build_dir / setup_script_name
            with open(setup_script_path, "w") as f:
                f.write(setup_script)
            if setup_script_name not in dockerfile:
                logger.warning(
                    f"Setup script {setup_script_name} may not be used in Dockerfile"
                )

        # Write the dockerfile to the build directory
        dockerfile_path = build_dir / "Dockerfile"
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile)

        # Build the image
        logger.info(
            f"Building docker image {image_name} in {build_dir} with platform {platform}"
        )
        max_attempts = 3
        for attempt in range(max_attempts):
            response = client.api.build(
                path=str(build_dir),
                tag=image_name,
                rm=True,
                forcerm=True,
                decode=True,
                platform=platform,
                nocache=nocache,
            )

            # Log the build process continuously. Podman can briefly retain a
            # stale cache reference after an image is removed, reporting
            # "top layer info: layer not known" before any build step runs.
            # Under concurrent builds, the daemon's forcerm=True cleanup of the
            # intermediate build container can also race with another build's
            # container teardown, surfacing as "identifier is not a container"
            # or "deleting build container ..." even though the image itself
            # was built and tagged successfully. Retrying is safe for both
            # cases and avoids turning transient daemon races into
            # instance-level evaluation errors.
            buildlog = ""
            retry_transient = False
            for chunk in response:
                if "stream" in chunk:
                    # Remove ANSI escape sequences from the log
                    chunk_stream = ansi_escape(chunk["stream"])
                    logger.info(chunk_stream.strip())
                    buildlog += chunk_stream
                elif "errorDetail" in chunk:
                    message = chunk["errorDetail"]["message"]
                    lower_message = message.lower()
                    is_transient = (
                        "layer not known" in lower_message
                        or "identifier is not a container" in lower_message
                        or "deleting build container" in lower_message
                    )
                    if attempt < max_attempts - 1 and is_transient:
                        logger.warning(
                            "Transient Docker daemon error while building %s "
                            "(attempt %d/%d): %s; retrying",
                            image_name,
                            attempt + 1,
                            max_attempts,
                            message,
                        )
                        retry_transient = True
                        break
                    # Decode error message, raise BuildError
                    logger.error(f"Error: {ansi_escape(message)}")
                    raise docker.errors.BuildError(message, buildlog)
            if not retry_transient:
                break
            close = getattr(response, "close", None)
            if close:
                close()
            response = None
        logger.info("Image built successfully!")
    except docker.errors.BuildError as e:
        logger.error(f"docker.errors.BuildError during {image_name}: {e}")
        raise BuildImageError(image_name, str(e), logger) from e
    except Exception as e:
        logger.error(f"Error building image {image_name}: {e}")
        raise BuildImageError(image_name, str(e), logger) from e
    finally:
        close = getattr(response, "close", None)
        if close:
            try:
                close()
            except ValueError:
                pass
        close_logger(logger)  # functions that create loggers should close them


def build_base_images(
    client: docker.DockerClient,
    dataset: list,
    force_rebuild: bool = False,
    namespace: str = None,
    instance_image_tag: str = None,
    env_image_tag: str = None,
):
    """
    Builds the base images required for the dataset if they do not already exist.

    Args:
        client (docker.DockerClient): Docker client to use for building the images
        dataset (list): List of test specs or dataset to build images for
        force_rebuild (bool): Whether to force rebuild the images even if they already exist
    """
    # Get the base images to build from the dataset
    test_specs = get_test_specs_from_dataset(
        dataset,
        namespace=namespace,
        instance_image_tag=instance_image_tag,
        env_image_tag=env_image_tag,
    )
    base_images = {
        x.base_image_key: (x.base_dockerfile, x.platform) for x in test_specs
    }

    # Build the base images
    for image_name, (dockerfile, platform) in base_images.items():
        try:
            # Check if the base image already exists
            client.images.get(image_name)
            if force_rebuild:
                # Remove the base image if it exists and force rebuild is enabled
                remove_image(client, image_name, "quiet")
            else:
                print(f"Base image {image_name} already exists, skipping build.")
                continue
        except docker.errors.ImageNotFound:
            pass
        # Build the base image (if it does not exist or force rebuild is enabled)
        print(f"Building base image ({image_name})")
        build_image(
            image_name=image_name,
            setup_scripts={},
            dockerfile=dockerfile,
            platform=platform,
            client=client,
            build_dir=BASE_IMAGE_BUILD_DIR / image_name.replace(":", "__"),
        )
    print("Base images built successfully.")


def get_env_configs_to_build(
    client: docker.DockerClient,
    dataset: list,
    namespace: str = None,
    instance_image_tag: str = None,
    env_image_tag: str = None,
):
    """
    Returns a dictionary of image names to build scripts and dockerfiles for environment images.
    Returns only the environment images that need to be built.

    Args:
        client (docker.DockerClient): Docker client to use for building the images
        dataset (list): List of test specs or dataset to build images for
    """
    image_scripts = dict()
    base_images = dict()
    test_specs = get_test_specs_from_dataset(
        dataset,
        namespace=namespace,
        instance_image_tag=instance_image_tag,
        env_image_tag=env_image_tag,
    )

    for test_spec in test_specs:
        # Check if the base image exists
        try:
            if test_spec.base_image_key not in base_images:
                base_images[test_spec.base_image_key] = client.images.get(
                    test_spec.base_image_key
                )
        except docker.errors.ImageNotFound:
            raise Exception(
                f"Base image {test_spec.base_image_key} not found for {test_spec.env_image_key}\n."
                "Please build the base images first."
            )

        # Check if the environment image exists
        image_exists = False
        try:
            client.images.get(test_spec.env_image_key)
            image_exists = True
        except docker.errors.ImageNotFound:
            pass
        if not image_exists:
            # Add the environment image to the list of images to build
            image_scripts[test_spec.env_image_key] = {
                "setup_script": test_spec.setup_env_script,
                "dockerfile": test_spec.env_dockerfile,
                "platform": test_spec.platform,
            }
    return image_scripts


def build_env_images(
    client: docker.DockerClient,
    dataset: list,
    force_rebuild: bool = False,
    max_workers: int = 4,
    namespace: str = None,
    instance_image_tag: str = None,
    env_image_tag: str = None,
):
    """
    Builds the environment images required for the dataset if they do not already exist.

    Args:
        client (docker.DockerClient): Docker client to use for building the images
        dataset (list): List of test specs or dataset to build images for
        force_rebuild (bool): Whether to force rebuild the images even if they already exist
        max_workers (int): Maximum number of workers to use for building images
    """
    # Get the environment images to build from the dataset
    if force_rebuild:
        env_image_keys = {
            x.env_image_key
            for x in get_test_specs_from_dataset(
                dataset,
                namespace=namespace,
                instance_image_tag=instance_image_tag,
                env_image_tag=env_image_tag,
            )
        }
        for key in env_image_keys:
            remove_image(client, key, "quiet")
    build_base_images(
        client, dataset, force_rebuild, namespace, instance_image_tag, env_image_tag
    )
    configs_to_build = get_env_configs_to_build(
        client, dataset, namespace, instance_image_tag, env_image_tag
    )
    if len(configs_to_build) == 0:
        print("No environment images need to be built.")
        return [], []
    print(f"Total environment images to build: {len(configs_to_build)}")

    args_list = list()
    for image_name, config in configs_to_build.items():
        args_list.append(
            (
                image_name,
                {"setup_env.sh": config["setup_script"]},
                config["dockerfile"],
                config["platform"],
                client,
                ENV_IMAGE_BUILD_DIR / image_name.replace(":", "__"),
            )
        )

    successful, failed = run_threadpool(build_image, args_list, max_workers)
    # Show how many images failed to build
    if len(failed) == 0:
        print("All environment images built successfully.")
    else:
        print(f"{len(failed)} environment images failed to build.")

    # Return the list of (un)successfuly built images
    return successful, failed


def build_instance_images(
    client: docker.DockerClient,
    dataset: list,
    force_rebuild: bool = False,
    max_workers: int = 4,
    namespace: str = None,
    tag: str = None,
    env_image_tag: str = None,
    force_rebuild_env: bool | None = None,
    nocache: bool = False,
):
    """
    Builds the instance images required for the dataset if they do not already exist.

    Args:
        dataset (list): List of test specs or dataset to build images for
        client (docker.DockerClient): Docker client to use for building the images
        force_rebuild (bool): Whether to force rebuild the images even if they already exist
        max_workers (int): Maximum number of workers to use for building images
        force_rebuild_env (bool | None): Override whether base/environment
            images are also force rebuilt. By default this follows
            ``force_rebuild`` for backward compatibility.
        nocache (bool): Disable Docker's intermediate build cache for instance
            images.
    """
    # Build environment images (and base images as needed) first
    test_specs = list(
        map(
            lambda x: make_test_spec(
                x,
                namespace=namespace,
                instance_image_tag=tag,
                env_image_tag=env_image_tag,
            ),
            dataset,
        )
    )
    if force_rebuild:
        for spec in test_specs:
            remove_image(client, spec.instance_image_key, "quiet")
    rebuild_env = force_rebuild if force_rebuild_env is None else force_rebuild_env
    _, env_failed = build_env_images(client, test_specs, rebuild_env, max_workers)

    failed_env_keys = {
        failure[0] if isinstance(failure, tuple) else failure
        for failure in env_failed
    }
    if failed_env_keys:
        # Don't build images for instances that depend on failed-to-build env images
        dont_run_specs = [
            spec for spec in test_specs if spec.env_image_key in failed_env_keys
        ]
        test_specs = [
            spec for spec in test_specs if spec.env_image_key not in failed_env_keys
        ]
        print(
            f"Skipping {len(dont_run_specs)} instances - due to failed env image builds"
        )
    print(f"Building instance images for {len(test_specs)} instances")
    successful, failed = list(), list()

    # `logger` is set to None b/c logger is created in build-instage_image
    payloads = [(spec, client, None, nocache) for spec in test_specs]
    # Build the instance images
    successful, failed = run_threadpool(build_instance_image, payloads, max_workers)
    # Show how many images failed to build
    if len(failed) == 0:
        print("All instance images built successfully.")
    else:
        print(f"{len(failed)} instance images failed to build.")

    # Return the list of (un)successfuly built images
    return successful, failed


def build_instance_image(
    test_spec: TestSpec,
    client: docker.DockerClient,
    logger: logging.Logger | None,
    nocache: bool,
):
    """
    Builds the instance image for the given test spec if it does not already exist.

    Args:
        test_spec (TestSpec): Test spec to build the instance image for
        client (docker.DockerClient): Docker client to use for building the image
        logger (logging.Logger): Logger to use for logging the build process
        nocache (bool): Whether to use the cache when building
    """
    # Set up logging for the build process
    build_dir = INSTANCE_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(
        ":", "__"
    )
    new_logger = False
    if logger is None:
        new_logger = True
        logger = setup_logger(test_spec.instance_id, build_dir / "prepare_image.log")

    # Get the image names and dockerfile for the instance image
    image_name = test_spec.instance_image_key
    env_image_name = test_spec.env_image_key
    dockerfile = test_spec.instance_dockerfile

    # Check that the env. image the instance image is based on exists. It is
    # a shared, deterministically-built layer (keyed by a hash of its setup
    # script/dockerfile), so if something external removed it mid-run
    # (e.g. a concurrent prune on a shared host), rebuild it here rather than
    # failing every remaining instance that depends on it.
    try:
        client.images.get(env_image_name)
    except docker.errors.ImageNotFound:
        logger.info(
            f"Environment image {env_image_name} not found for {test_spec.instance_id}; "
            "rebuilding it before continuing."
        )
        try:
            client.images.get(test_spec.base_image_key)
        except docker.errors.ImageNotFound:
            build_image(
                image_name=test_spec.base_image_key,
                setup_scripts={},
                dockerfile=test_spec.base_dockerfile,
                platform=test_spec.platform,
                client=client,
                build_dir=BASE_IMAGE_BUILD_DIR / test_spec.base_image_key.replace(":", "__"),
            )
        try:
            build_image(
                image_name=env_image_name,
                setup_scripts={"setup_env.sh": test_spec.setup_env_script},
                dockerfile=test_spec.env_dockerfile,
                platform=test_spec.platform,
                client=client,
                build_dir=ENV_IMAGE_BUILD_DIR / env_image_name.replace(":", "__"),
            )
        except Exception as e:
            raise BuildImageError(
                test_spec.instance_id,
                f"Environment image {env_image_name} was missing and could not be "
                f"rebuilt for {test_spec.instance_id}: {e}",
                logger,
            ) from e
    logger.info(
        f"Environment image {env_image_name} found for {test_spec.instance_id}\n"
        f"Building instance image {image_name} for {test_spec.instance_id}"
    )

    # Check if the instance image already exists
    image_exists = False
    try:
        client.images.get(image_name)
        image_exists = True
    except docker.errors.ImageNotFound:
        pass

    # Build the instance image
    if not image_exists:
        build_image(
            image_name=image_name,
            setup_scripts={
                "setup_repo.sh": test_spec.install_repo_script,
            },
            dockerfile=dockerfile,
            platform=test_spec.platform,
            client=client,
            build_dir=build_dir,
            nocache=nocache,
        )
    else:
        logger.info(f"Image {image_name} already exists, skipping build.")

    if new_logger:
        close_logger(logger)


def build_container(
    test_spec: TestSpec,
    client: docker.DockerClient,
    run_id: str,
    logger: logging.Logger,
    nocache: bool,
    force_rebuild: bool = False,
):
    """
    Builds the instance image for the given test spec and creates a container from the image.

    Args:
        test_spec (TestSpec): Test spec to build the instance image and container for
        client (docker.DockerClient): Docker client for building image + creating the container
        run_id (str): Run ID identifying process, used for the container name
        logger (logging.Logger): Logger to use for logging the build process
        nocache (bool): Whether to use the cache when building
        force_rebuild (bool): Whether to force rebuild the image even if it already exists
    """
    # Build corresponding instance image
    if force_rebuild:
        remove_image(client, test_spec.instance_image_key, "quiet")
    if not test_spec.is_remote_image:
        build_instance_image(test_spec, client, logger, nocache)
    else:
        try:
            client.images.get(test_spec.instance_image_key)
        except docker.errors.ImageNotFound:
            try:
                client.images.pull(test_spec.instance_image_key)
            except docker.errors.NotFound as e:
                raise BuildImageError(test_spec.instance_id, str(e), logger) from e
            except Exception as e:
                raise Exception(
                    f"Error occurred while pulling image {test_spec.base_image_key}: {str(e)}"
                )

    container = None
    try:
        # Create the container
        logger.info(f"Creating container for {test_spec.instance_id}...")

        container = _create_eval_container(client, test_spec, run_id, logger)
        logger.info(f"Container for {test_spec.instance_id} created: {container.id}")
        return container
    except Exception as e:
        # If an error occurs, clean up the container and raise an exception
        logger.error(f"Error creating container for {test_spec.instance_id}: {e}")
        logger.info(traceback.format_exc())
        cleanup_container(client, container, logger)
        raise BuildImageError(test_spec.instance_id, str(e), logger) from e
