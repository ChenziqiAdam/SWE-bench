"""Stage 2.5: validate that each instance's base_commit builds in Docker.

Caches results to outputs/<dir>/build_validation.json so reruns skip rebuilds.

Speed improvements vs v1:
- Two-phase build: env images first (parallelised across versions), then instance
  images only for instances whose env succeeded.  This mirrors what
  build_instance_images() does internally, but we surface it here so we can
  short-circuit all instances that share a failing env image without ever
  attempting their instance builds.
- Version-level short-circuit: after env images are built, instances whose
  env_image_key failed are immediately marked non-buildable and excluded from
  the (slower) per-instance build phase.
- Incremental cache write: results are flushed after each phase so a crash
  mid-run doesn't lose the env-phase results.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path

import docker

from swebench.harness.docker_build import build_env_images, build_instance_images
from swebench.harness.test_spec.test_spec import MAP_REPO_VERSION_TO_SPECS, make_test_spec

logger = logging.getLogger(__name__)


def _spec_hash(inst: dict) -> str:
    """Hash the build-relevant portions of an instance's resolved test_spec.

    A cached build_validation entry is only valid if it was produced from the
    same spec. When a spec (pre_install/install/build/test_cmd/env setup) is
    edited, the hash changes and the cached entry is treated as a miss so the
    instance is re-validated — preventing a stale non-buildable flag from
    silently excluding a now-passing instance from the report.
    """
    try:
        spec = make_test_spec(inst)
    except Exception:
        # If the spec can't be built (e.g. missing version), fall back to a
        # stable sentinel so such instances still cache by instance_id alone.
        return "no-spec"
    payload = json.dumps(
        {
            "env_script": spec.setup_env_script,
            "install_script": spec.install_repo_script,
            "eval_script": spec.eval_script,
            "validation_cmd": _validation_command(inst),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _validation_command(inst: dict) -> str | None:
    """Return an optional post-build import/smoke command for an instance."""
    repo_specs = MAP_REPO_VERSION_TO_SPECS.get(inst.get("repo", ""), {})
    spec = repo_specs.get(str(inst.get("version", "")), {})
    command = spec.get("validation_cmd")
    return command.strip() if isinstance(command, str) and command.strip() else None


def _smoke_validate_image(client, image_name: str, command: str) -> tuple[bool, str]:
    """Run a lightweight readiness check inside a newly built instance image."""
    shell_command = (
        "source /opt/miniconda3/bin/activate && conda activate testbed && "
        f"cd /testbed && {command}"
    )
    try:
        client.containers.run(
            image_name,
            command=["/bin/bash", "-lc", shell_command],
            remove=True,
        )
        return True, ""
    except Exception as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        detail = str(stderr).strip() or str(exc)
        return False, f"post-build validation failed: {detail[-2000:]}"


def validate_buildable(
    instances: list[dict],
    cache_path: str | Path,
    max_workers: int = 4,
    force: bool = False,
    clean_images: bool = False,
) -> dict[str, dict]:
    """For each instance, build env+instance image at base_commit. Return id→{buildable, error}.

    Reads/writes the cache JSON so reruns only validate new instance_ids.
    """
    cache_path = Path(cache_path)
    cache: dict[str, dict] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
        logger.info(f"Loaded {len(cache)} cached build-validation results from {cache_path}")
    if force:
        # Revalidate only the requested cohort while retaining results for
        # unselected instances in a shared output directory.
        for inst in instances:
            cache.pop(inst["instance_id"], None)

    # Auto-invalidate cached entries whose spec changed since they were written.
    spec_hashes = {i["instance_id"]: _spec_hash(i) for i in instances}
    if not force:
        stale = [
            i["instance_id"]
            for i in instances
            if i["instance_id"] in cache
            and cache[i["instance_id"]].get("spec_hash") != spec_hashes[i["instance_id"]]
        ]
        if stale:
            logger.info(
                f"{len(stale)} cached entr(ies) invalidated (spec changed): "
                f"{', '.join(stale[:5])}{'...' if len(stale) > 5 else ''}"
            )
            for iid in stale:
                cache.pop(iid, None)

    todo = [i for i in instances if i["instance_id"] not in cache]

    # Filter out instances whose repo/version has no spec — they can't be built.
    buildable_todo = []
    for inst in todo:
        repo = inst.get("repo", "")
        version = inst.get("version", "")
        if repo not in MAP_REPO_VERSION_TO_SPECS or version not in MAP_REPO_VERSION_TO_SPECS.get(repo, {}):
            logger.warning(
                f"Skipping {inst['instance_id']}: no spec for {repo}@version={version!r}"
            )
            cache[inst["instance_id"]] = {"buildable": False, "error": f"no spec for version {version!r}", "spec_hash": spec_hashes[inst["instance_id"]]}
        else:
            buildable_todo.append(inst)

    if not buildable_todo:
        logger.info("All instances already validated; skipping build pass.")
        _write_cache(cache, cache_path)
        return cache

    logger.info(f"Building images at base_commit for {len(buildable_todo)} instance(s)...")
    client = None
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as e:
        if client is not None:
            client.close()
        error = f"Docker daemon unavailable: {e}"
        logger.error(error)
        for inst in buildable_todo:
            cache[inst["instance_id"]] = {
                "buildable": False,
                "error": error,
                "spec_hash": spec_hashes[inst["instance_id"]],
            }
        _write_cache(cache, cache_path)
        return cache
    try:

        # ── Phase 1: build env images (one per repo/version group) ────────────────
        # Make test specs so we can group by env_image_key.
        spec_map: dict[str, object] = {}  # instance_id → TestSpec
        for inst in buildable_todo:
            spec_map[inst["instance_id"]] = make_test_spec(inst)

        # Group instances by env_image_key to identify version buckets.
        env_key_to_ids: dict[str, list[str]] = defaultdict(list)
        for iid, spec in spec_map.items():
            env_key_to_ids[spec.env_image_key].append(iid)

        logger.info(
            f"Phase 1: building {len(env_key_to_ids)} distinct env image(s) "
            f"for {len(buildable_todo)} instance(s) using {max_workers} workers..."
        )
        _, env_failed = build_env_images(
            client=client,
            dataset=buildable_todo,
            force_rebuild=force,
            max_workers=max_workers,
            instance_image_tag="latest",
            env_image_tag="latest",
        )
        # build_env_images returns payload tuples; element 0 is the env image_name (key).
        failed_env_keys = {f[0] if isinstance(f, tuple) else f for f in env_failed}

        # Mark instances in failed-env groups immediately and remove from phase 2.
        instance_todo_p2: list[dict] = []
        for inst in buildable_todo:
            iid = inst["instance_id"]
            env_key = spec_map[iid].env_image_key
            if env_key in failed_env_keys:
                cache[iid] = {"buildable": False, "error": f"env image failed: {env_key}", "spec_hash": spec_hashes[iid]}
            else:
                instance_todo_p2.append(inst)

        # Flush after phase 1 — crash-safe.
        _write_cache(cache, cache_path)

        skipped = len(buildable_todo) - len(instance_todo_p2)
        if skipped:
            logger.info(
                f"Phase 1 done: {skipped} instance(s) skipped (env image failed); "
                f"{len(instance_todo_p2)} proceeding to instance-image build."
            )

        # ── Phase 2: build per-instance images ────────────────────────────────────
        if instance_todo_p2:
            logger.info(
                f"Phase 2: building {len(instance_todo_p2)} instance image(s) "
                f"using {max_workers} workers..."
            )
            # Phase 1 already rebuilt the shared base/environment images when
            # requested. Force only the per-instance images here; rebuilding
            # the shared ancestry a second time can invalidate Docker's cached
            # parents while parallel instance builds start.
            # With report-first cleanup enabled, validate in bounded batches
            # and immediately remove successful instance images. Evaluation
            # will rebuild one batch at a time and remove them after reports
            # are persisted. This prevents validation from retaining the full
            # cohort's large repository layers before evaluation starts.
            batch_size = max(1, max_workers) if clean_images else len(instance_todo_p2)
            successful = []
            smoke_failures: dict[str, str] = {}
            for start in range(0, len(instance_todo_p2), batch_size):
                batch = instance_todo_p2[start : start + batch_size]
                batch_successful, _ = build_instance_images(
                    client=client,
                    dataset=batch,
                    force_rebuild=force,
                    max_workers=max_workers,
                    tag="latest",
                    env_image_tag="latest",
                    force_rebuild_env=False,
                    nocache=force,
                )
                batch_by_id = {inst["instance_id"]: inst for inst in batch}
                for built in batch_successful:
                    built_spec = built[0]
                    inst = batch_by_id[built_spec.instance_id]
                    validation_cmd = _validation_command(inst)
                    if validation_cmd:
                        ok, error = _smoke_validate_image(
                            client, built_spec.instance_image_key, validation_cmd
                        )
                        if not ok:
                            smoke_failures[built_spec.instance_id] = error
                            logger.error(
                                "Post-build validation failed for %s: %s",
                                built_spec.instance_id,
                                error,
                            )
                            continue
                    successful.append(built)
                if clean_images:
                    for spec, *_rest in batch_successful:
                        try:
                            client.images.remove(spec.instance_image_key, force=True)
                            logger.info(
                                "Validation passed for %s; removed instance image %s",
                                spec.instance_id,
                                spec.instance_image_key,
                            )
                        except docker.errors.NotFound:
                            pass
                        except Exception as exc:
                            logger.warning(
                                "Validation passed for %s, but instance image cleanup failed: %s",
                                spec.instance_id,
                                exc,
                            )
            ok_ids = {s[0].instance_id for s in successful}

            for inst in instance_todo_p2:
                iid = inst["instance_id"]
                if iid in ok_ids:
                    cache[iid] = {"buildable": True, "error": "", "spec_hash": spec_hashes[iid]}
                    continue
                if iid in smoke_failures:
                    # Image built but failed the post-build smoke test: a real failure.
                    cache[iid] = {"buildable": False, "error": smoke_failures[iid], "spec_hash": spec_hashes[iid]}
                    continue
                # The thread pool recorded a build failure for this instance, but
                # build_image() logs "Image built successfully!" as soon as the
                # Docker build stream completes without error — any exception
                # afterwards (e.g. a transient client.images.get() race right
                # after tagging) gets misclassified as a build failure even
                # though the image exists. Verify against Docker directly
                # before trusting the thread-pool's failure classification.
                image_key = spec_map[iid].instance_image_key
                try:
                    client.images.get(image_key)
                    image_exists = True
                except docker.errors.ImageNotFound:
                    image_exists = False
                except Exception:
                    image_exists = False
                if image_exists:
                    logger.warning(
                        "Instance image for %s exists despite a reported build "
                        "failure (likely a transient post-build race); treating "
                        "as buildable.",
                        iid,
                    )
                    cache[iid] = {"buildable": True, "error": "", "spec_hash": spec_hashes[iid]}
                else:
                    reason = _read_build_log(spec_map[iid])
                    cache[iid] = {"buildable": False, "error": reason or "instance image build failed", "spec_hash": spec_hashes[iid]}

        _write_cache(cache, cache_path)
        n_ok = sum(1 for v in cache.values() if v["buildable"])
        logger.info(f"Build validation: {n_ok}/{len(cache)} buildable. Cache → {cache_path}")
        return cache
    finally:
        if client is not None:
            client.close()


def _write_cache(cache: dict, path: Path) -> None:
    path.write_text(json.dumps(cache, indent=2))


def _read_build_log(spec) -> str:
    from swebench.harness.docker_build import INSTANCE_IMAGE_BUILD_DIR
    log = INSTANCE_IMAGE_BUILD_DIR / f"{spec.instance_image_key.replace(':', '__')}" / "build_image.log"
    if log.exists():
        tail = log.read_text(errors="replace").splitlines()[-3:]
        return " | ".join(line.strip() for line in tail if line.strip())[:300]
    return ""
