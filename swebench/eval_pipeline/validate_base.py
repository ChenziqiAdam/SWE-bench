"""Stage 2.5: validate that each instance's base_commit builds in Docker.

Caches results to outputs/<dir>/build_validation.json so reruns skip rebuilds.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import docker

from swebench.harness.docker_build import build_instance_images
from swebench.harness.test_spec.test_spec import make_test_spec

logger = logging.getLogger(__name__)


def validate_buildable(
    instances: list[dict],
    cache_path: str | Path,
    max_workers: int = 4,
    force: bool = False,
) -> dict[str, dict]:
    """For each instance, build env+instance image at base_commit. Return id→{buildable, error}.

    Reads/writes the cache JSON so reruns only validate new instance_ids.
    """
    cache_path = Path(cache_path)
    cache: dict[str, dict] = {}
    if cache_path.exists() and not force:
        cache = json.loads(cache_path.read_text())
        logger.info(f"Loaded {len(cache)} cached build-validation results from {cache_path}")

    todo = [i for i in instances if i["instance_id"] not in cache] if not force else instances
    if not todo:
        logger.info("All instances already validated; skipping build pass.")
        return cache

    logger.info(f"Building images at base_commit for {len(todo)} instance(s)...")
    client = docker.from_env()
    successful, failed = build_instance_images(
        client=client,
        dataset=todo,
        force_rebuild=force,
        max_workers=max_workers,
        tag="latest",
        env_image_tag="latest",
    )
    ok_ids = {s.instance_id for s in successful}

    for inst in todo:
        iid = inst["instance_id"]
        if iid in ok_ids:
            cache[iid] = {"buildable": True, "error": ""}
        else:
            # Surface a short reason by reading the build log if present.
            spec = make_test_spec(inst)
            reason = ""
            log = Path("logs/build_images/instances") / f"{spec.instance_image_key.replace(':', '__')}" / "build_image.log"
            if log.exists():
                tail = log.read_text(errors="replace").splitlines()[-3:]
                reason = " | ".join(l.strip() for l in tail if l.strip())[:300]
            cache[iid] = {"buildable": False, "error": reason or "image build failed"}

    cache_path.write_text(json.dumps(cache, indent=2))
    n_ok = sum(1 for v in cache.values() if v["buildable"])
    logger.info(f"Build validation: {n_ok}/{len(cache)} buildable. Cache → {cache_path}")
    return cache
