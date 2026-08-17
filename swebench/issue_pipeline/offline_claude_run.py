"""Resumable full Issues_No_Tests inference using the audited Claude CLI pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference_security import (
    inference_input_hash,
    inference_worktree_root,
)
from swebench.issue_pipeline.offline_claude_pilot import (
    MODEL,
    NETWORK_ISOLATION_LABEL,
    TIMEOUT,
    _jsonl_rows,
    _clean_patch,
    _capture_patch,
    _repair_patch,
    _run_one,
    _strip_build_artifact_diff_blocks,
    _untracked_root_scratch_paths,
    audit_patch_paths,
    audit_trajectory,
    build_pilot_prompt,
    detect_rate_limit,
    select_pilot_instances,
)


DATASET_PROFILES = {
    "issues_no_tests": {"openmm/openmm": 76, "rdkit/rdkit": 7},
    "v1": {"lammps/lammps": 31, "biopython/biopython": 4},
    "final_cc_remainder": {
        "lammps/lammps": 7,
        "qutip/qutip": 2,
        "deepchem/deepchem": 2,
        "biopython/biopython": 1,
        "qgis/QGIS": 1,
        "astropy/astropy": 1,
    },
}
REVIEW_SEED = 20260803
MAX_FETCH_ATTEMPTS = 3
ABNORMAL_FILE_COUNT = 3
MANIFEST_VERSION = 1
RECOVERY_VERSION = 1
RECOVERABLE_ERRORS = {None, "disallowed_patch_scope"}


class RateLimitStop(RuntimeError):
    """Raised to halt a run when the subscription session limit is hit.

    A rate-limited ``claude -p`` call exits instantly (~1-3s) rather than
    failing gracefully, so without this guard every remaining pending
    instance in the run would burn through the same rejection in seconds,
    wasting hours and producing checkpoints that look "finalized" but carry
    no real signal. Stopping on the first detection keeps the run resumable:
    the rate-limited instance is never checkpointed, so it stays pending for
    the next --resume once the session window resets.
    """

    def __init__(self, instance_id: str):
        super().__init__(
            f"subscription session rate limit hit at {instance_id}; rerun with "
            "--resume once the session window resets"
        )
        self.instance_id = instance_id


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_hash(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(value: Any) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return _sha256_bytes(data)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _atomic_jsonl(path: Path, rows: Iterable[dict]) -> None:
    _atomic_write(
        path,
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )


def select_full_instances(instances_path: Path) -> tuple[list[dict], dict[str, int]]:
    """Load every instance in ``instances_path``, in file order.

    Returns the selected instances plus the matched ``DATASET_PROFILES`` repo
    map, so callers/manifest can record which known dataset this run is.
    """
    rows = _jsonl_rows(instances_path)
    ordered_ids = [row.get("instance_id") for row in rows]
    if len(ordered_ids) != len(set(ordered_ids)):
        duplicates = sorted({i for i in ordered_ids if ordered_ids.count(i) > 1})
        raise ValueError(f"duplicate instance_id values: {duplicates}")
    selected = select_pilot_instances(instances_path, ordered_ids)
    counts: dict[str, int] = {}
    for instance in selected:
        repo = instance["repo"]
        counts[repo] = counts.get(repo, 0) + 1
    matching = [
        name for name, repos in DATASET_PROFILES.items() if repos == counts
    ]
    if len(matching) != 1:
        raise ValueError(
            "instances do not match a known Issues_No_Tests dataset profile: "
            f"repo counts={counts}"
        )
    return selected, DATASET_PROFILES[matching[0]]


def _manifest_config(
    *,
    instances_path: Path,
    instances: list[dict],
    expected_repos: dict[str, int],
    model: str,
    timeout: int,
    workers: int,
    wave_size: int,
) -> dict:
    prompts = [
        {"instance_id": item["instance_id"], "prompt": build_pilot_prompt(item)}
        for item in instances
    ]
    return {
        "manifest_version": MANIFEST_VERSION,
        "model": model,
        "timeout_seconds": timeout,
        "workers": workers,
        "wave_size": wave_size,
        "expected_repos": expected_repos,
        "sources": [{"path": str(instances_path), "sha256": _file_hash(instances_path)}],
        "prompt_hash": _canonical_hash(prompts),
        "instance_selection_hash": _canonical_hash(
            [
                {
                    "instance_id": item["instance_id"],
                    "input_hash": inference_input_hash(item),
                }
                for item in instances
            ]
        ),
        "instance_count": len(instances),
        "review_seed": REVIEW_SEED,
        "abnormal_file_threshold": ABNORMAL_FILE_COUNT,
        "fetch_max_attempts": MAX_FETCH_ATTEMPTS,
    }


def _validate_recovery_manifest(existing: dict, requested: dict) -> None:
    """Validate immutable inputs while allowing later prompt improvements.

    Recovery replays the historical, hash-verified trajectory and never sends
    the current prompt to a model, so prompt hash drift is irrelevant here.
    """
    ignored = {"prompt_hash"}
    mismatched = [
        key
        for key, value in existing.items()
        if key not in ignored and requested.get(key) != value
    ]
    unknown = sorted(set(existing) - set(requested) - ignored)
    if mismatched or unknown:
        raise ValueError("resume manifest does not match the requested run")


def _validate_recovery_instances(frozen: list[dict], requested: list[dict]) -> None:
    """Allow historical local-media path rebasing, but no scientific input drift."""
    if len(frozen) != len(requested):
        raise ValueError("resume instances.jsonl does not match the requested run")
    ignored = {"issue_images", "image_assets"}
    for old, new in zip(frozen, requested):
        old_core = {key: value for key, value in old.items() if key not in ignored}
        new_core = {key: value for key, value in new.items() if key not in ignored}
        if old_core != new_core:
            raise ValueError("resume instances.jsonl does not match the requested run")


def _checkpoint_path(output_dir: Path, instance_id: str) -> Path:
    return output_dir / "checkpoints" / f"{instance_id}.json"


def _load_checkpoints(output_dir: Path, ordered_ids: list[str]) -> dict[str, dict]:
    checkpoints: dict[str, dict] = {}
    allowed = set(ordered_ids)
    for path in sorted((output_dir / "checkpoints").glob("*.json")):
        checkpoint = json.loads(path.read_text())
        instance_id = checkpoint.get("instance_id")
        if instance_id not in allowed or path.stem != instance_id:
            raise ValueError(f"invalid checkpoint {path}")
        if instance_id in checkpoints:
            raise ValueError(f"duplicate checkpoint for {instance_id}")
        if checkpoint.get("finalized") is not True:
            raise ValueError(f"non-final checkpoint for {instance_id}")
        checkpoints[instance_id] = checkpoint
    return checkpoints


def _verify_trajectory(output_dir: Path, checkpoint: dict) -> None:
    prediction = checkpoint["prediction"]
    relative = prediction["offline_audit"]["trajectory_path"]
    path = output_dir / relative
    actual = _file_hash(path)
    expected = prediction["trajectory_sha256"]
    if actual != expected:
        raise ValueError(f"trajectory hash mismatch for {checkpoint['instance_id']}")


def _successful_edit_calls(trajectory: str) -> list[dict]:
    """Return successful Write/Edit calls in trajectory order.

    A tool request is not evidence that an edit happened. Claude stream JSON
    records the authoritative result separately, so permission denials and
    failed tools are deliberately omitted here.
    """
    calls: list[dict] = []
    results: dict[str, bool] = {}
    for raw in trajectory.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use" and item.get("name") in {"Write", "Edit"}:
                calls.append(
                    {
                        "id": item.get("id"),
                        "name": item["name"],
                        "input": item.get("input"),
                    }
                )
            elif item.get("type") == "tool_result":
                tool_id = item.get("tool_use_id")
                if isinstance(tool_id, str):
                    results[tool_id] = item.get("is_error") is not True
    return [call for call in calls if results.get(call["id"]) is True]


def _safe_replay_path(
    raw_path: object, repo_dir: Path, audited_paths: set[str]
) -> tuple[Path, str]:
    """Map a historical tool path into the disposable checkout safely."""
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("edit has no file_path")
    candidate = Path(raw_path)
    matches = [
        path
        for path in audited_paths
        if raw_path == path or raw_path.replace("\\", "/").endswith(f"/{path}")
    ]
    if not candidate.is_absolute() and raw_path in audited_paths:
        matches = [raw_path]
    if len(matches) != 1:
        raise ValueError(f"edit path is not uniquely present in original audit: {raw_path}")
    relative = matches[0]
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"unsafe audited path: {relative}")
    target = (repo_dir / relative).resolve()
    root = repo_dir.resolve()
    if target == root or root not in target.parents:
        raise ValueError(f"edit escapes checkout: {raw_path}")
    return target, relative


def _replay_edit_calls(
    trajectory: str, repo_dir: Path, audited_paths: list[str]
) -> list[str]:
    """Replay successful file-edit tools without executing trajectory Bash."""
    replayed: list[str] = []
    audited = set(audited_paths)
    calls = _successful_edit_calls(trajectory)
    if not calls:
        raise ValueError("trajectory has no successful Write/Edit calls")
    for call in calls:
        tool_input = call.get("input")
        if not isinstance(tool_input, dict):
            raise ValueError("edit input is not an object")
        try:
            target, relative = _safe_replay_path(
                tool_input.get("file_path"), repo_dir, audited
            )
        except ValueError:
            # A successful transient Write may later be deleted. The frozen
            # final changed-path audit is authoritative: never recreate a
            # path that was absent from that audit.
            continue
        if call["name"] == "Write":
            content = tool_input.get("content")
            if not isinstance(content, str):
                raise ValueError(f"Write content is not text: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        else:
            old = tool_input.get("old_string")
            new = tool_input.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                raise ValueError(f"Edit strings are invalid: {relative}")
            content = target.read_text()
            count = content.count(old)
            replace_all = tool_input.get("replace_all") is True
            if count == 0 or (count != 1 and not replace_all):
                raise ValueError(
                    f"Edit old_string match count is {count} for {relative}"
                )
            target.write_text(content.replace(old, new, -1 if replace_all else 1))
        replayed.append(relative)
    replayed = list(dict.fromkeys(replayed))
    if not replayed:
        raise ValueError("no successful Write/Edit path is present in original audit")
    return replayed


_FENCED_DIFF_RE = re.compile(r"```diff\s*\n(?P<patch>diff --git .*?)```", re.S)


def _terminal_diff(trajectory: str) -> str:
    """Extract the last complete fenced unified diff from a terminal answer."""
    terminal_text = ""
    for raw in trajectory.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        for item in message.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                terminal_text += str(item.get("text") or "") + "\n"
    matches = list(_FENCED_DIFF_RE.finditer(terminal_text))
    return matches[-1].group("patch").rstrip() + "\n" if matches else ""


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git a/") or " b/" not in line:
            continue
        left, right = line[len("diff --git ") :].split(" b/", 1)
        if left != f"a/{right}" or not right or ".." in Path(right).parts:
            raise ValueError(f"unsafe or inconsistent diff header: {line}")
        paths.append(right)
    if not paths:
        raise ValueError("patch has no git diff headers")
    return paths


def _git_apply_check(repo_dir: Path, patch: str) -> None:
    fd, name = tempfile.mkstemp(prefix="recovery-index-")
    os.close(fd)
    index = Path(name)
    index.unlink()
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        subprocess.run(
            ["git", "read-tree", "HEAD"], cwd=repo_dir, env=env, check=True
        )
        result = subprocess.run(
            ["git", "apply", "--check", "--cached", "-"],
            cwd=repo_dir,
            env=env,
            input=patch,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise ValueError(f"git apply --check failed: {result.stderr.strip()}")
    finally:
        index.unlink(missing_ok=True)


def _working_tree_paths(repo_dir: Path) -> list[str]:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return sorted(set(changed + untracked))


def _recover_checkpoint(
    instance: dict, checkpoint: dict, trajectory: str, repo_dir: Path
) -> tuple[dict, dict]:
    """Build a recovered checkpoint in memory; never mutate the source row."""
    prediction = checkpoint["prediction"]
    audit = prediction.get("offline_audit", {})
    if prediction.get("model_patch"):
        raise ValueError("existing nonempty prediction")
    if prediction.get("error") not in RECOVERABLE_ERRORS:
        raise ValueError(f"inference error is not recoverable: {prediction.get('error')}")
    if audit.get("network_findings") or audit_trajectory(trajectory):
        raise ValueError("trajectory contains a network-policy violation")
    if detect_rate_limit(trajectory):
        raise ValueError("trajectory contains a rate-limit rejection")

    validate_checkout(repo_dir, instance["base_commit"])
    original_paths = list(audit.get("changed_paths") or [])
    replayed: list[str] = []
    fallback = False
    try:
        replayed = _replay_edit_calls(trajectory, repo_dir, original_paths)
        actual_paths = _working_tree_paths(repo_dir)
        unexpected = sorted(set(actual_paths) - set(original_paths))
        missing_replay = sorted(set(replayed) - set(actual_paths))
        if unexpected or missing_replay:
            raise ValueError(
                f"replay path audit mismatch: unexpected={unexpected}, "
                f"missing={missing_replay}"
            )
        scratch = _untracked_root_scratch_paths(repo_dir)
        captured = _capture_patch(repo_dir)
        _, disallowed = audit_patch_paths(repo_dir, scratch_paths=scratch)
        discarded_paths = sorted(scratch | set(disallowed))
        patch = _repair_patch(
            _clean_patch(
                _strip_build_artifact_diff_blocks(
                    captured, scratch_paths=set(discarded_paths)
                )
            )
        )
    except ValueError:
        if instance["instance_id"] != "openmm__openmm-3428":
            raise
        patch = _repair_patch(_clean_patch(_terminal_diff(trajectory)))
        replayed = _patch_paths(patch)
        fallback = True

    patch_paths = _patch_paths(patch)
    if not patch.strip():
        raise ValueError("recovered patch is empty")
    # Scope-check terminal fallback and protect against malformed capture output.
    for path in patch_paths:
        lowered = path.lower().split("/")
        filename = lowered[-1]
        testish = (
            "tests" in lowered[:-1]
            or "test" in lowered[:-1]
            or "unittest" in lowered[:-1]
            or "unittests" in lowered[:-1]
            or any(part in {"testdata", "test_data", "fixtures"} for part in lowered[:-1])
            or (("test" in filename or "tests" in filename) and len(lowered) > 1)
        )
        if not testish:
            raise ValueError(f"recovered diff path is outside test scope: {path}")
    _git_apply_check(repo_dir, patch)

    recovered = json.loads(json.dumps(checkpoint))
    recovered_prediction = recovered["prediction"]
    provenance = {
        "version": RECOVERY_VERSION,
        "method": "terminal_diff" if fallback else "successful_write_edit_replay",
        "no_inference": True,
        "trajectory_sha256": recovered_prediction["trajectory_sha256"],
        "original_error": prediction.get("error"),
        "original_audit_sha256": _canonical_hash(checkpoint.get("audit", {})),
        "replayed_paths": replayed,
        "patch_paths": patch_paths,
        "discarded_paths": discarded_paths if not fallback else [],
    }
    recovered_prediction["model_patch"] = patch
    recovered_prediction.pop("error", None)
    recovered_prediction["offline_audit"].update(
        status="passed",
        changed_paths=patch_paths,
        disallowed_paths=[],
        recovery=provenance,
    )
    recovered["audit"].update(
        status="passed",
        changed_paths=patch_paths,
        disallowed_paths=[],
        recovery=provenance,
    )
    recovered["recovered_old_inference"] = True
    return recovered, provenance


def _rebuild_outputs(
    output_dir: Path,
    ordered_ids: list[str],
    checkpoints: dict[str, dict],
    *,
    model: str,
    timeout: int,
) -> None:
    ordered = [checkpoints[item] for item in ordered_ids if item in checkpoints]
    _atomic_jsonl(
        output_dir / "agent_predictions.jsonl",
        (item["prediction"] for item in ordered),
    )
    _atomic_json(
        output_dir / "offline_audit.json",
        {
            "model": model,
            "timeout_seconds": timeout,
            "tool_network": NETWORK_ISOLATION_LABEL,
            "cases": [item["audit"] for item in ordered],
            "finalized_count": len(ordered),
            "manual_review_required": True,
        },
    )


def _save_checkpoint(
    output_dir: Path,
    prediction: dict,
    audit: dict,
    checkpoints: dict[str, dict],
    ordered_ids: list[str],
    *,
    model: str,
    timeout: int,
) -> None:
    instance_id = prediction["instance_id"]
    checkpoint = {
        "instance_id": instance_id,
        "finalized": True,
        "imported": False,
        "prediction": prediction,
        "audit": audit,
    }
    _atomic_json(_checkpoint_path(output_dir, instance_id), checkpoint)
    checkpoints[instance_id] = checkpoint
    _rebuild_outputs(
        output_dir,
        ordered_ids,
        checkpoints,
        model=model,
        timeout=timeout,
    )


def validate_checkout(repo_dir: Path, base_commit: str) -> None:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != base_commit:
        raise ValueError(f"checkout HEAD mismatch: expected {base_commit}")


def _fetch_with_retries(
    instance: dict,
    github_token: str | None,
    checkout_root: Path,
    clone: Callable[..., Path] = _clone_repo_at_commit,
) -> Path:
    errors: list[str] = []
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            checkout = clone(
                instance["repo"], instance["base_commit"], github_token, checkout_root
            )
            validate_checkout(checkout, instance["base_commit"])
            return checkout
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < MAX_FETCH_ATTEMPTS:
                time.sleep(min(attempt, 2))
    raise RuntimeError(
        f"fetch failed for {instance['instance_id']} after {MAX_FETCH_ATTEMPTS} "
        f"attempts: {'; '.join(errors)}"
    )


def _run_wave(
    wave: list[dict],
    checkout_root: Path,
    output_dir: Path,
    *,
    model: str,
    timeout: int,
    workers: int,
    github_token: str | None,
    run_one: Callable[..., tuple[dict, dict]] = _run_one,
) -> Iterable[tuple[dict, dict]]:
    """Fetch the entire wave first, then yield each finalized agent result."""
    worktrees: dict[str, Path] = {}
    fetch_errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=min(workers, len(wave))) as pool:
        futures = {
            pool.submit(_fetch_with_retries, item, github_token, checkout_root): item
            for item in wave
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                worktrees[item["instance_id"]] = future.result()
            except BaseException as exc:
                fetch_errors.append(exc)
    if fetch_errors:
        for checkout in worktrees.values():
            shutil.rmtree(checkout, ignore_errors=True)
        raise fetch_errors[0]

    with ThreadPoolExecutor(max_workers=min(workers, len(wave))) as pool:
        futures = {
            pool.submit(
                run_one,
                item,
                worktrees[item["instance_id"]],
                output_dir,
                model,
                timeout,
            ): item
            for item in wave
        }
        for future in as_completed(futures):
            item = futures[future]
            checkout = worktrees[item["instance_id"]]
            try:
                yield future.result()
            finally:
                shutil.rmtree(checkout, ignore_errors=True)


def _review_reasons(prediction: dict) -> list[str]:
    audit = prediction.get("offline_audit", {})
    reasons: list[str] = []
    error = prediction.get("error")
    if error:
        reasons.append(str(error))
    if not prediction.get("model_patch"):
        reasons.append("empty_patch")
    if audit.get("network_findings"):
        reasons.append("network_finding")
    if audit.get("disallowed_paths"):
        reasons.append("scope_violation")
    if audit.get("status") == "failed" and not error:
        reasons.append("audit_failed")
    if len(audit.get("changed_paths", [])) > ABNORMAL_FILE_COUNT:
        reasons.append("abnormal_multi_file_patch")
    return list(dict.fromkeys(reasons))


def _stratified_sample_counts(expected_repos: dict[str, int]) -> dict[str, int]:
    """Proportionally scale a fixed 8-sample review budget across repos.

    Reproduces the established (openmm: 7, rdkit: 1) split for the 83-instance
    dataset exactly, and generalizes to any repo mix while guaranteeing at
    least 1 sample per repo.
    """
    total = sum(expected_repos.values())
    return {
        repo: max(1, round(count / total * 8))
        for repo, count in expected_repos.items()
    }


def _build_review_queue(
    instances: list[dict],
    checkpoints: dict[str, dict],
    *,
    expected_repos: dict[str, int],
) -> list[dict]:
    by_id = {item["instance_id"]: item for item in instances}
    queue: dict[str, dict] = {}
    clean: dict[str, list[str]] = {repo: [] for repo in expected_repos}
    for instance_id, checkpoint in checkpoints.items():
        reasons = _review_reasons(checkpoint["prediction"])
        if reasons:
            queue[instance_id] = {"instance_id": instance_id, "reasons": reasons}
        else:
            clean[by_id[instance_id]["repo"]].append(instance_id)
    rng = random.Random(REVIEW_SEED)
    for repo, count in _stratified_sample_counts(expected_repos).items():
        candidates = sorted(clean[repo])
        for instance_id in rng.sample(candidates, min(count, len(candidates))):
            queue[instance_id] = {
                "instance_id": instance_id,
                "reasons": ["fixed_stratified_clean_sample"],
            }
    order = {item["instance_id"]: index for index, item in enumerate(instances)}
    return sorted(queue.values(), key=lambda item: order[item["instance_id"]])


def _write_review_files(
    output_dir: Path,
    instances: list[dict],
    checkpoints: dict[str, dict],
    *,
    expected_repos: dict[str, int],
) -> None:
    queue = _build_review_queue(instances, checkpoints, expected_repos=expected_repos)
    _atomic_json(
        output_dir / "review_queue.json",
        {
            "seed": REVIEW_SEED,
            "abnormal_file_threshold": ABNORMAL_FILE_COUNT,
            "cases": queue,
        },
    )
    _atomic_json(
        output_dir / "manual_review.json",
        {
            "pilot_reviews_imported": False,
            "review_seed": REVIEW_SEED,
            "cases": [
                {
                    "instance_id": item["instance_id"],
                    "review_status": "pending",
                    "reasons": item["reasons"],
                }
                for item in queue
            ],
        },
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _jsonl_text(rows: Iterable[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _merge_recovered_prediction(prior: dict, recovered: dict) -> dict:
    """Change only recovery-owned fields in an existing aggregate row."""
    merged = json.loads(json.dumps(prior))
    merged["model_patch"] = recovered["model_patch"]
    merged.pop("error", None)
    merged["offline_audit"] = recovered["offline_audit"]
    merged["trajectory_sha256"] = recovered["trajectory_sha256"]
    return merged


def _next_recovery_backup_dir(output_dir: Path) -> Path:
    root = output_dir / "backups"
    index = 1
    while (root / f"recover-old-inference-{index:03d}").exists():
        index += 1
    return root / f"recover-old-inference-{index:03d}"


def _atomic_recovery_update(output_dir: Path, payloads: dict[Path, str]) -> Path:
    """Back up and replace a recovery's complete file set, with rollback."""
    backup_dir = _next_recovery_backup_dir(output_dir)
    temporary: dict[Path, Path] = {}
    for path, data in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.recovery.", dir=path.parent)
        with os.fdopen(fd, "w") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary[path] = Path(name)

    backup_dir.mkdir(parents=True)
    existing: set[Path] = set()
    try:
        for path in payloads:
            if path.exists():
                existing.add(path)
                relative = path.relative_to(output_dir)
                backup = backup_dir / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
        replaced: list[Path] = []
        try:
            for path, staged in temporary.items():
                os.replace(staged, path)
                replaced.append(path)
        except BaseException:
            for path in replaced:
                backup = backup_dir / path.relative_to(output_dir)
                if path in existing:
                    shutil.copy2(backup, path)
                else:
                    path.unlink(missing_ok=True)
            raise
    finally:
        for staged in temporary.values():
            staged.unlink(missing_ok=True)
    return backup_dir


def _recovery_review_payloads(
    output_dir: Path,
    instances: list[dict],
    checkpoints: dict[str, dict],
    expected_repos: dict[str, int],
) -> dict[Path, str]:
    queue = _build_review_queue(instances, checkpoints, expected_repos=expected_repos)
    queue_value = {
        "seed": REVIEW_SEED,
        "abnormal_file_threshold": ABNORMAL_FILE_COUNT,
        "cases": queue,
    }
    manual_path = output_dir / "manual_review.json"
    prior_by_id: dict[str, dict] = {}
    if manual_path.exists():
        prior = json.loads(manual_path.read_text())
        prior_by_id = {
            item["instance_id"]: item
            for item in prior.get("cases", [])
            if isinstance(item, dict) and isinstance(item.get("instance_id"), str)
        }
    manual_cases = []
    for item in queue:
        case = dict(
            prior_by_id.get(
                item["instance_id"],
                {"instance_id": item["instance_id"], "review_status": "pending"},
            )
        )
        case["reasons"] = item["reasons"]
        manual_cases.append(case)
    manual_value = {
        "pilot_reviews_imported": False,
        "review_seed": REVIEW_SEED,
        "cases": manual_cases,
    }
    return {
        output_dir / "review_queue.json": _json_text(queue_value),
        manual_path: _json_text(manual_value),
    }


def recover_old_inference(
    instances: list[dict],
    output_dir: Path,
    *,
    model: str,
    timeout: int,
    github_token: str | None,
    expected_repos: dict[str, int],
    dry_run: bool,
    fetch: Callable[[dict, str | None, Path], Path] = _fetch_with_retries,
) -> dict:
    """Recover empty historical predictions solely from frozen trajectories."""
    ordered_ids = [item["instance_id"] for item in instances]
    by_id = {item["instance_id"]: item for item in instances}
    checkpoints = _load_checkpoints(output_dir, ordered_ids)
    if len(checkpoints) != len(instances):
        raise ValueError("old-inference recovery requires a complete checkpoint set")
    for checkpoint in checkpoints.values():
        _verify_trajectory(output_dir, checkpoint)

    private_root = inference_worktree_root("claude-old-inference-recovery")
    checkout_root = Path(tempfile.mkdtemp(prefix="recover_", dir=private_root))
    recovered: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    ineligible: dict[str, str] = {}
    try:
        for instance_id in ordered_ids:
            checkpoint = checkpoints[instance_id]
            prediction = checkpoint["prediction"]
            if prediction.get("model_patch"):
                continue
            error = prediction.get("error")
            if isinstance(error, str) and (
                error.startswith("claude_exit_")
                or error in {"process_error", "timeout"}
            ):
                ineligible[instance_id] = f"inference error is not recoverable: {error}"
                continue
            trajectory_path = output_dir / prediction["offline_audit"]["trajectory_path"]
            trajectory = trajectory_path.read_text()
            try:
                if _file_hash(trajectory_path) != prediction["trajectory_sha256"]:
                    raise ValueError("trajectory hash mismatch")
                if prediction.get("error") not in RECOVERABLE_ERRORS:
                    raise ValueError(
                        f"inference error is not recoverable: {prediction.get('error')}"
                    )
                if prediction.get("offline_audit", {}).get("network_findings"):
                    raise ValueError("trajectory contains a network-policy violation")
                checkout = fetch(by_id[instance_id], github_token, checkout_root)
                try:
                    new_checkpoint, _ = _recover_checkpoint(
                        by_id[instance_id], checkpoint, trajectory, checkout
                    )
                finally:
                    shutil.rmtree(checkout, ignore_errors=True)
                recovered[instance_id] = new_checkpoint
            except Exception as exc:
                skipped[instance_id] = str(exc)
    finally:
        shutil.rmtree(checkout_root, ignore_errors=True)

    report = {
        "recovery_version": RECOVERY_VERSION,
        "dry_run": dry_run,
        "empty_prediction_count": sum(
            not checkpoint["prediction"].get("model_patch")
            for checkpoint in checkpoints.values()
        ),
        "candidate_count": len(recovered) + len(skipped),
        "recoverable_count": len(recovered),
        "skipped_count": len(skipped),
        "ineligible_count": len(ineligible),
        "recovered": list(recovered),
        "skipped": skipped,
        "ineligible": ineligible,
    }
    if dry_run or not recovered:
        return report

    updated = dict(checkpoints)
    updated.update(recovered)
    prior_predictions = _jsonl_rows(output_dir / "agent_predictions.jsonl")
    prior_by_id = {item["instance_id"]: item for item in prior_predictions}
    predictions = []
    for instance_id in ordered_ids:
        prior = prior_by_id[instance_id]
        if instance_id in recovered:
            prior = _merge_recovered_prediction(
                prior, updated[instance_id]["prediction"]
            )
        predictions.append(prior)
    audit_value = {
        "model": model,
        "timeout_seconds": timeout,
        "tool_network": NETWORK_ISOLATION_LABEL,
        "cases": [updated[item]["audit"] for item in ordered_ids],
        "finalized_count": len(updated),
        "manual_review_required": True,
        "old_inference_recovery": report,
    }
    report["backup_dir"] = str(
        _next_recovery_backup_dir(output_dir).relative_to(output_dir)
    )
    payloads: dict[Path, str] = {
        output_dir / "agent_predictions.jsonl": _jsonl_text(predictions),
        output_dir / "offline_audit.json": _json_text(audit_value),
        output_dir / "recovery_report.json": _json_text(report),
    }
    for instance_id, checkpoint in recovered.items():
        payloads[_checkpoint_path(output_dir, instance_id)] = _json_text(checkpoint)

    selected_path = output_dir / "agent_predictions.selected.jsonl"
    if selected_path.exists():
        selected = _jsonl_rows(selected_path)
        for index, row in enumerate(selected):
            instance_id = row.get("instance_id")
            if instance_id in recovered and not row.get("model_patch"):
                selected[index] = _merge_recovered_prediction(
                    row, updated[instance_id]["prediction"]
                )
        payloads[selected_path] = _jsonl_text(selected)
    payloads.update(
        _recovery_review_payloads(
            output_dir, instances, updated, expected_repos=expected_repos
        )
    )
    _atomic_recovery_update(output_dir, payloads)
    return report


def run_full(
    instances: list[dict],
    output_dir: Path,
    *,
    manifest: dict,
    resume: bool,
    model: str,
    timeout: int,
    workers: int,
    wave_size: int,
    github_token: str | None,
    expected_repos: dict[str, int],
) -> list[dict]:
    ordered_ids = [item["instance_id"] for item in instances]
    if resume:
        if not output_dir.is_dir():
            raise ValueError(f"resume output does not exist: {output_dir}")
        existing = json.loads((output_dir / "run_manifest.json").read_text())
        if existing != manifest:
            raise ValueError("resume manifest does not match the requested run")
        if _jsonl_rows(output_dir / "instances.jsonl") != instances:
            raise ValueError("resume instances.jsonl does not match the requested run")
        expected_prompts = [
            {"instance_id": item["instance_id"], "prompt": build_pilot_prompt(item)}
            for item in instances
        ]
        if _jsonl_rows(output_dir / "agent_prompts.jsonl") != expected_prompts:
            raise ValueError("resume agent_prompts.jsonl does not match the requested run")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "trajectories").mkdir()
        (output_dir / "checkpoints").mkdir()
        _atomic_json(output_dir / "run_manifest.json", manifest)
        _atomic_jsonl(output_dir / "instances.jsonl", instances)
        _atomic_jsonl(
            output_dir / "agent_prompts.jsonl",
            (
                {"instance_id": item["instance_id"], "prompt": build_pilot_prompt(item)}
                for item in instances
            ),
        )

    checkpoints = _load_checkpoints(output_dir, ordered_ids)
    for checkpoint in checkpoints.values():
        _verify_trajectory(output_dir, checkpoint)
    _rebuild_outputs(
        output_dir, ordered_ids, checkpoints, model=model, timeout=timeout
    )

    pending = [item for item in instances if item["instance_id"] not in checkpoints]
    private_root = inference_worktree_root("claude-offline-full")
    checkout_root = Path(tempfile.mkdtemp(prefix="run_", dir=private_root))
    stopped_for_rate_limit = False
    try:
        for start in range(0, len(pending), wave_size):
            wave = pending[start : start + wave_size]
            for prediction, audit in _run_wave(
                wave,
                checkout_root,
                output_dir,
                model=model,
                timeout=timeout,
                workers=workers,
                github_token=github_token,
            ):
                if prediction.get("error") == "rate_limit":
                    stopped_for_rate_limit = True
                    break
                _save_checkpoint(
                    output_dir,
                    prediction,
                    audit,
                    checkpoints,
                    ordered_ids,
                    model=model,
                    timeout=timeout,
                )
            if stopped_for_rate_limit:
                break
    finally:
        shutil.rmtree(checkout_root, ignore_errors=True)

    if stopped_for_rate_limit:
        raise RateLimitStop(prediction["instance_id"])

    if len(checkpoints) != len(instances):
        raise RuntimeError(
            f"run incomplete: {len(checkpoints)}/{len(instances)} finalized"
        )
    for checkpoint in checkpoints.values():
        _verify_trajectory(output_dir, checkpoint)
    _write_review_files(output_dir, instances, checkpoints, expected_repos=expected_repos)
    return [checkpoints[item]["prediction"] for item in ordered_ids]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--wave-size", type=int, default=3)
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--recover-old-inference", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.timeout <= 0 or args.timeout > TIMEOUT:
        raise SystemExit(f"timeout must be in 1..{TIMEOUT}")
    if args.workers < 1 or args.workers > 3:
        raise SystemExit("workers must be in 1..3")
    if args.wave_size < 1 or args.wave_size > 3:
        raise SystemExit("wave-size must be in 1..3")
    if args.recover_old_inference and not args.resume:
        raise SystemExit("--recover-old-inference requires --resume")
    if args.resume and args.dry_run and not args.recover_old_inference:
        raise SystemExit("--resume and --dry-run cannot be combined")
    instances, expected_repos = select_full_instances(args.instances)
    manifest = _manifest_config(
        instances_path=args.instances,
        instances=instances,
        expected_repos=expected_repos,
        model=args.model,
        timeout=args.timeout,
        workers=args.workers,
        wave_size=args.wave_size,
    )
    if args.dry_run and not args.recover_old_inference:
        print(
            json.dumps(
                {**manifest, "pending_count": len(instances)},
                indent=2,
            )
        )
        return 0
    if args.recover_old_inference:
        if not args.output_dir.is_dir():
            raise SystemExit(f"resume output does not exist: {args.output_dir}")
        existing = json.loads((args.output_dir / "run_manifest.json").read_text())
        try:
            _validate_recovery_manifest(existing, manifest)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        frozen_instances = _jsonl_rows(args.output_dir / "instances.jsonl")
        try:
            _validate_recovery_instances(frozen_instances, instances)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        report = recover_old_inference(
            frozen_instances,
            args.output_dir,
            model=args.model,
            timeout=args.timeout,
            github_token=args.github_token,
            expected_repos=expected_repos,
            dry_run=args.dry_run,
        )
        print(json.dumps(report, indent=2))
        return 0
    try:
        run_full(
            instances,
            args.output_dir,
            manifest=manifest,
            resume=args.resume,
            model=args.model,
            timeout=args.timeout,
            workers=args.workers,
            wave_size=args.wave_size,
            github_token=args.github_token,
            expected_repos=expected_repos,
        )
    except RateLimitStop as exc:
        print(f"stopped: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
