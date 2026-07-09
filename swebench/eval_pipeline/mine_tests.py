"""Stage 2.6: mine FAIL_TO_PASS / PASS_TO_PASS by running pytest before+after the gold patch.

For each buildable instance we spin up its built instance image, then run the test
suite twice inside the same container:

  Pass A: base_commit + test_patch only        →  "initial" pass/fail per test
  Pass B: base_commit + test_patch + gold patch →  "final"   pass/fail per test

Classification:
  FAIL_TO_PASS  = tests that went FAIL/missing → PASS    (the bug-revealing ones)
  PASS_TO_PASS  = tests that went PASS         → PASS    (regression guards)

Output is cached at outputs/<dir>/test_mining.json keyed by instance_id, then
written back into instances.jsonl (overwriting the regex-mined values).
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import docker

from swebench.harness.constants import (
    DOCKER_PATCH,
    MAP_REPO_VERSION_TO_SPECS,
    START_TEST_OUTPUT,
    END_TEST_OUTPUT,
)
from swebench.harness.docker_build import build_container, setup_logger, close_logger
from swebench.harness.docker_utils import (
    cleanup_container,
    copy_to_container,
    exec_run_with_timeout,
)
from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
from swebench.harness.test_spec.python import get_test_directives
from swebench.harness.test_spec.test_spec import make_test_spec

logger = logging.getLogger(__name__)

HEREDOC = "EOF_MINE_F2P"


def _build_mine_script(instance: dict, apply_gold: bool) -> str:
    """Build a bash script that resets to base, applies test_patch (+ optionally
    the gold patch), then runs pytest on the touched tests with the harness's
    START/END markers around the output so the log parser can find it."""
    spec = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    env_name = "testbed"
    repo_dir = "/testbed"
    base_commit = instance["base_commit"]
    test_patch = instance["test_patch"]

    # spec["test_cmd"] may be a string (legacy: append the test-file directives)
    # or a list of fully-formed commands (C/C++ path: the command already names
    # the test, so run it verbatim — matching what eval's get_test_cmds does).
    raw_test_cmd = spec["test_cmd"]
    if isinstance(raw_test_cmd, list):
        test_cmd = " && ".join(raw_test_cmd)
    else:
        test_cmd = " ".join([raw_test_cmd, *get_test_directives(instance)])

    # C/C++ images (ubuntu base) have no conda; only activate it when present.
    lines = [
        "#!/bin/bash",
        "set -uxo pipefail",
        "if [ -f /opt/miniconda3/bin/activate ]; then "
        f"source /opt/miniconda3/bin/activate && conda activate {env_name}; fi",
        f"cd {repo_dir}",
        f"git config --global --add safe.directory {repo_dir}",
        # Hard reset, then re-apply test_patch (and optionally gold patch).
        f"git reset --hard {base_commit}",
        # Clean untracked but leave conda env etc. alone — repo_dir is the worktree.
        "git clean -fdx",
    ]
    if "eval_commands" in spec:
        lines += spec["eval_commands"]
    if "install" in spec:
        lines.append(spec["install"])

    # Apply test_patch via heredoc (always, since these are the tests we care about).
    lines.append(f"git apply -v - <<'{HEREDOC}'\n{test_patch}\n{HEREDOC}")

    if apply_gold:
        # Gold patch is staged into the container as DOCKER_PATCH before exec.
        # Use the same fallback chain as run_evaluation for robustness.
        lines += [
            f"git apply -v {DOCKER_PATCH} "
            f"|| git apply -v --3way {DOCKER_PATCH} "
            f"|| patch --batch --fuzz=5 -p1 -i {DOCKER_PATCH}",
        ]

    # Run post-patch build steps, mirroring eval's ordering in
    # harness/test_spec/utils.py: reset → test_patch → build → test. Some specs
    # only make the patch effective via this step; without it both mining passes
    # can test the unpatched install → fail→fail → 0 FAIL_TO_PASS mined.
    if "build" in spec:
        lines += spec["build"]
    if "build_after_test_patch" in spec:
        lines += spec["build_after_test_patch"]

    lines += [
        f": '{START_TEST_OUTPUT}'",
        test_cmd,
        f": '{END_TEST_OUTPUT}'",
    ]
    return "\n".join(lines) + "\n"


def _run_one_pass(container, script_text: str, log_dir: Path, tag: str, timeout: int) -> str:
    """Write the script into the container, execute it, return the stdout text."""
    script_path = log_dir / f"mine_{tag}.sh"
    script_path.write_text(script_text)
    copy_to_container(container, script_path, PurePosixPath(f"/mine_{tag}.sh"))
    out, timed_out, runtime = exec_run_with_timeout(
        container, f"/bin/bash /mine_{tag}.sh", timeout
    )
    (log_dir / f"mine_{tag}.log").write_text(out)
    if timed_out:
        out += f"\n\n[mine_tests] Pass '{tag}' timed out after {timeout}s.\n"
    return out


def _classify(initial: dict[str, str], final: dict[str, str]) -> tuple[list[str], list[str]]:
    """initial/final are {test_name: status_str}; PASSED literal comes from TestStatus."""
    PASSED = "PASSED"
    fail_to_pass = sorted(
        t for t, s in final.items()
        if s == PASSED and initial.get(t, "FAILED") != PASSED
    )
    pass_to_pass = sorted(
        t for t, s in final.items()
        if s == PASSED and initial.get(t) == PASSED
    )
    return fail_to_pass, pass_to_pass


def _mine_one(instance: dict, run_id: str, client: docker.DockerClient, timeout: int = 1800) -> dict:
    """Mine FAIL_TO_PASS / PASS_TO_PASS for one instance. Builds (or reuses) the
    instance image, then runs both passes inside one container."""
    instance_id = instance["instance_id"]
    log_dir = Path("logs/mine_tests") / run_id / instance_id
    log_dir.mkdir(parents=True, exist_ok=True)
    inst_logger = setup_logger(instance_id, log_dir / "mine.log")

    spec = make_test_spec(instance)
    # Parse against a spec with EMPTY FAIL_TO_PASS/PASS_TO_PASS. Some parsers
    # (e.g. OpenMM's `_reconcile_nodeids`) suffix-match parsed nodeids onto the
    # spec's expected keys and *add* the matched expected key to the result. If
    # the instance still carries stale regex-mined keys (a different path-prefix
    # spelling of the same test), that injects a duplicate key we never actually
    # observed — which later eval can't reproduce, so the test scores as a
    # FAIL_TO_PASS failure. Mining must report only what the parser truly saw.
    parse_spec = make_test_spec({**instance, "FAIL_TO_PASS": [], "PASS_TO_PASS": []})
    parser = MAP_REPO_TO_PARSER.get(instance["repo"])
    if parser is None:
        inst_logger.error(f"No log parser registered for repo {instance['repo']}")
        close_logger(inst_logger)
        return {"ok": False, "error": f"no log parser for {instance['repo']}"}

    container = None
    try:
        # Remove any stale container from a previous crashed/interrupted run with
        # the same name to avoid Docker 409 Conflict errors.
        stale_name = spec.get_instance_container_name(run_id)
        try:
            stale = client.containers.get(stale_name)
            inst_logger.warning(f"Removing stale container {stale_name} from previous run")
            stale.remove(force=True)
        except docker.errors.NotFound:
            pass

        container = build_container(spec, client, run_id, inst_logger, nocache=False, force_rebuild=False)
        container.start()

        # Stage gold patch as DOCKER_PATCH inside the container for Pass B.
        patch_file = log_dir / "gold.patch"
        patch_file.write_text(instance.get("patch", "") or "")
        copy_to_container(container, patch_file, PurePosixPath(DOCKER_PATCH))

        # Pass A — test_patch only
        out_a = _run_one_pass(container, _build_mine_script(instance, apply_gold=False),
                              log_dir, "initial", timeout)
        initial = parser(out_a, parse_spec)

        # Pass B — test_patch + gold patch
        out_b = _run_one_pass(container, _build_mine_script(instance, apply_gold=True),
                              log_dir, "final", timeout)
        final = parser(out_b, parse_spec)

        f2p, p2p = _classify(initial, final)
        inst_logger.info(
            f"Mined {len(f2p)} FAIL_TO_PASS, {len(p2p)} PASS_TO_PASS "
            f"(initial: {len(initial)} tests, final: {len(final)} tests)"
        )
        return {
            "ok": True,
            "FAIL_TO_PASS": f2p,
            "PASS_TO_PASS": p2p,
            "n_initial": len(initial),
            "n_final": len(final),
        }
    except Exception as e:
        inst_logger.exception(f"mine_tests failed for {instance_id}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        cleanup_container(client, container, inst_logger)
        close_logger(inst_logger)


def mine_fail_to_pass(
    instances: list[dict],
    cache_path: str | Path,
    run_id: str = "mine",
    max_workers: int = 2,
    force: bool = False,
    build_validation: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Mine FAIL_TO_PASS/PASS_TO_PASS for buildable instances. Cached on disk."""
    cache_path = Path(cache_path)
    cache: dict[str, dict] = {}
    if cache_path.exists() and not force:
        cache = json.loads(cache_path.read_text())
        logger.info(f"Loaded {len(cache)} cached mining results from {cache_path}")

    build_validation = build_validation or {}

    def eligible(inst):
        iid = inst["instance_id"]
        if iid in cache and not force:
            return False
        if build_validation:
            if not build_validation.get(iid, {}).get("buildable", True):
                return False
        if not inst.get("test_patch", "").strip():
            return False
        return True

    todo = [i for i in instances if eligible(i)]
    if not todo:
        logger.info("No instances need mining.")
        return cache

    logger.info(f"Mining FAIL_TO_PASS for {len(todo)} instance(s) with {max_workers} workers...")
    # Share one Docker client across all threads — avoids opening a new Unix socket
    # per worker, which is wasteful and can hit connection limits on large runs.
    shared_client = docker.from_env()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(_mine_one, inst, run_id, shared_client): inst for inst in todo}
            for fut in as_completed(futs):
                inst = futs[fut]
                iid = inst["instance_id"]
                try:
                    cache[iid] = fut.result()
                except Exception as e:
                    cache[iid] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                # Persist incrementally so a crash mid-run doesn't lose progress.
                cache_path.write_text(json.dumps(cache, indent=2))
    finally:
        shared_client.close()

    n_ok = sum(1 for v in cache.values() if v.get("ok"))
    n_f2p = sum(len(v.get("FAIL_TO_PASS", [])) for v in cache.values() if v.get("ok"))
    logger.info(f"Mining done: {n_ok}/{len(cache)} ok, {n_f2p} FAIL_TO_PASS tests total.")
    return cache


def apply_mined_to_instances(
    instances: list[dict],
    mining: dict[str, dict],
) -> list[dict]:
    """Overwrite FAIL_TO_PASS / PASS_TO_PASS on instance dicts using mined results.
    Instances without successful mining keep their existing (regex-mined) values."""
    for inst in instances:
        m = mining.get(inst["instance_id"])
        if m and m.get("ok"):
            inst["FAIL_TO_PASS"] = m["FAIL_TO_PASS"]
            inst["PASS_TO_PASS"] = m["PASS_TO_PASS"]
    return instances
