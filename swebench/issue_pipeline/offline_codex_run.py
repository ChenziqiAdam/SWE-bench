"""Resumable full Issues_No_Tests inference using the audited pilot protocol."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

import openpyxl

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference_security import (
    inference_input_hash,
    inference_worktree_root,
)
from swebench.issue_pipeline.offline_codex_pilot import (
    MODEL,
    TIMEOUT,
    _jsonl_rows,
    _run_one,
    build_pilot_prompt,
)


DATASET_PROFILES = {
    "v1": {
        "workbook_rows": 37,
        "instances": 35,
        "repos": {"lammps/lammps": 31, "biopython/biopython": 4},
        "duplicate_mappings": {
            "lammps__lammps-4339": [4337, 4216],
            "lammps__lammps-4195": [4141, 4180],
        },
    },
    "v2": {
        "workbook_rows": 41,
        "instances": 40,
        "repos": {
            "lammps/lammps": 15,
            "qutip/qutip": 13,
            "deepchem/deepchem": 4,
            "astropy/astropy": 3,
            "qgis/QGIS": 2,
            "qiskit/qiskit": 2,
            "biopython/biopython": 1,
        },
        "duplicate_mappings": {"lammps__lammps-4481": [4487, 4499]},
    },
}
MAX_FETCH_ATTEMPTS = 3
ABNORMAL_FILE_COUNT = 3
MANIFEST_VERSION = 2


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


def _workbook_selection(excel_path: Path) -> dict[str, Any]:
    workbook = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    rows_found: list[dict[str, Any]] = []
    try:
        for sheet in workbook:
            rows = sheet.iter_rows(values_only=True)
            try:
                headers = next(rows)
            except StopIteration:
                continue
            for values in rows:
                row = dict(zip(headers, values))
                if not row.get("Repo") or not row.get("Closing PR #"):
                    continue
                instance_id = (
                    str(row["Repo"]).replace("/", "__", 1)
                    + f"-{int(row['Closing PR #'])}"
                )
                rows_found.append(
                    {
                        "instance_id": instance_id,
                        "repo": str(row["Repo"]),
                        "issue_number": int(row["Issue Number"]),
                        "closing_pr": int(row["Closing PR #"]),
                        "sheet": sheet.title,
                    }
                )
    finally:
        workbook.close()
    ordered = list(dict.fromkeys(row["instance_id"] for row in rows_found))
    duplicate_mappings = {
        instance_id: [
            row["issue_number"]
            for row in rows_found
            if row["instance_id"] == instance_id
        ]
        for instance_id in ordered
        if sum(row["instance_id"] == instance_id for row in rows_found) > 1
    }
    matching_profiles = [
        name
        for name, profile in DATASET_PROFILES.items()
        if len(rows_found) == profile["workbook_rows"]
        and len(ordered) == profile["instances"]
        and duplicate_mappings == profile["duplicate_mappings"]
    ]
    if len(matching_profiles) != 1:
        raise ValueError(
            "workbook does not match a supported Issues_No_Tests dataset: "
            f"rows={len(rows_found)}, unique_instances={len(ordered)}, "
            f"duplicate_mappings={duplicate_mappings}"
        )
    return {
        "row_count": len(rows_found),
        "unique_instance_count": len(ordered),
        "ordered_instance_ids": ordered,
        "duplicate_mappings": duplicate_mappings,
    }


def _workbook_instance_order(excel_path: Path) -> list[str]:
    return _workbook_selection(excel_path)["ordered_instance_ids"]


def select_full_instances(
    excel_path: Path,
    instance_paths: list[Path],
) -> list[dict]:
    """Select unique closing-PR instances in first workbook order."""
    if len(instance_paths) != 1:
        raise ValueError("exactly one --instances source file is required")
    source_rows = [row for path in instance_paths for row in _jsonl_rows(path)]
    source_ids = [row.get("instance_id") for row in source_rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("instance source files contain duplicate instance_id values")
    by_id = dict(zip(source_ids, source_rows))
    selection = _workbook_selection(excel_path)
    workbook_order = selection["ordered_instance_ids"]
    missing = [item for item in workbook_order if item not in by_id]
    extra = sorted(set(by_id) - set(workbook_order))
    if missing or extra:
        raise ValueError(f"spreadsheet/source mismatch: missing={missing}, extra={extra}")

    selected = [by_id[item] for item in workbook_order]
    profile = next(
        value
        for value in DATASET_PROFILES.values()
        if value["workbook_rows"] == selection["row_count"]
        and value["instances"] == selection["unique_instance_count"]
        and value["duplicate_mappings"] == selection["duplicate_mappings"]
    )
    expected_repos = profile["repos"]
    for instance in selected:
        instance_id = instance.get("instance_id")
        if instance.get("repo") not in expected_repos:
            raise ValueError(f"unexpected repository for {instance_id}")
        if not re.fullmatch(r"[0-9a-f]{40}", str(instance.get("base_commit", ""))):
            raise ValueError(f"invalid base_commit for {instance_id}")
        if not (instance.get("problem_statement") or "").strip():
            raise ValueError(f"missing issue content for {instance_id}")
    counts = {
        repo: sum(instance["repo"] == repo for instance in selected)
        for repo in expected_repos
    }
    if counts != expected_repos:
        raise ValueError(f"unexpected repository counts: {counts}")
    return selected


def _manifest_config(
    *,
    excel_path: Path,
    instance_paths: list[Path],
    instances: list[dict],
    model: str,
    timeout: int,
    workers: int,
    wave_size: int,
    review_all: bool,
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
        "excel": {"path": str(excel_path), "sha256": _file_hash(excel_path)},
        "sources": [
            {"path": str(path), "sha256": _file_hash(path)} for path in instance_paths
        ],
        "workbook_selection": _workbook_selection(excel_path),
        "prompt_hash": _canonical_hash(prompts),
        "instance_inputs": [
            {
                "instance_id": item["instance_id"],
                "input_hash": inference_input_hash(item),
            }
            for item in instances
        ],
        "instance_selection_hash": _canonical_hash(
            [inference_input_hash(item) for item in instances]
        ),
        "instance_count": len(instances),
        "review_all": review_all,
        "abnormal_file_threshold": ABNORMAL_FILE_COUNT,
        "fetch_max_attempts": MAX_FETCH_ATTEMPTS,
    }


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
            "tool_network": "disabled",
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
    imported: bool = False,
) -> None:
    instance_id = prediction["instance_id"]
    checkpoint = {
        "instance_id": instance_id,
        "finalized": True,
        "imported": imported,
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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    reachable = subprocess.run(
        ["git", "rev-list", "--count", "--all"], cwd=repo_dir, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    remotes = subprocess.run(
        ["git", "remote"], cwd=repo_dir, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if head != base_commit or reachable != "1" or remotes:
        raise RuntimeError(
            f"checkout isolation failed: head={head}, reachable={reachable}, "
            f"remotes={remotes!r}"
        )


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


def _build_review_queue(
    instances: list[dict], checkpoints: dict[str, dict], *, review_all: bool
) -> list[dict]:
    queue: list[dict] = []
    for instance in instances:
        instance_id = instance["instance_id"]
        checkpoint = checkpoints.get(instance_id)
        if checkpoint is None:
            continue
        reasons = _review_reasons(checkpoint["prediction"])
        if review_all:
            reasons = reasons or ["full_manual_audit"]
        if reasons:
            queue.append({"instance_id": instance_id, "reasons": reasons})
    return queue


def _write_review_files(
    output_dir: Path,
    instances: list[dict],
    checkpoints: dict[str, dict],
    *,
    review_all: bool,
) -> None:
    queue = _build_review_queue(instances, checkpoints, review_all=review_all)
    _atomic_json(
        output_dir / "review_queue.json",
        {
            "abnormal_file_threshold": ABNORMAL_FILE_COUNT,
            "review_all": review_all,
            "cases": queue,
        },
    )
    existing: dict[str, dict] = {}
    review_path = output_dir / "manual_review.json"
    if review_path.is_file():
        existing_rows = json.loads(review_path.read_text()).get("cases", [])
        existing = {item.get("instance_id"): item for item in existing_rows}
        if len(existing) != len(existing_rows):
            raise ValueError("manual_review.json contains duplicate instance IDs")
    cases = []
    for item in queue:
        prior = existing.get(item["instance_id"], {})
        cases.append(
            {
                "instance_id": item["instance_id"],
                "review_status": prior.get("review_status", "pending"),
                "reasons": item["reasons"],
                "trajectory_sha256": prior.get(
                    "trajectory_sha256",
                    checkpoints[item["instance_id"]]["prediction"]["trajectory_sha256"],
                ),
                "no_network_attempt_verified": prior.get(
                    "no_network_attempt_verified", False
                ),
                "no_prohibited_inputs_verified": prior.get(
                    "no_prohibited_inputs_verified", False
                ),
                "patch_scope_verified": prior.get("patch_scope_verified", False),
                "review_notes": prior.get("review_notes", ""),
            }
        )
    _atomic_json(
        review_path,
        {
            "review_all": review_all,
            "cases": cases,
        },
    )


def _finalize_manual_reviews(
    output_dir: Path,
    instances: list[dict],
    checkpoints: dict[str, dict],
    *,
    model: str,
    timeout: int,
) -> list[dict]:
    """Create final predictions from review decisions without changing checkpoints."""
    review_value = json.loads((output_dir / "manual_review.json").read_text())
    reviews = {
        item.get("instance_id"): item for item in review_value.get("cases", [])
    }
    ordered_ids = [item["instance_id"] for item in instances]
    if len(reviews) != len(review_value.get("cases", [])) or set(reviews) != set(ordered_ids):
        raise ValueError("manual review must contain exactly all selected instances")

    finalized: list[dict] = []
    audit_cases: list[dict] = []
    for instance_id in ordered_ids:
        checkpoint = checkpoints[instance_id]
        review = reviews[instance_id]
        status = review.get("review_status")
        if status not in {"approved", "rejected"}:
            raise ValueError(f"manual review pending for {instance_id}")
        for field in (
            "no_network_attempt_verified",
            "no_prohibited_inputs_verified",
            "patch_scope_verified",
        ):
            if review.get(field) is not True:
                raise ValueError(f"manual review {field} is not verified for {instance_id}")
        expected_hash = checkpoint["prediction"]["trajectory_sha256"]
        if review.get("trajectory_sha256") != expected_hash:
            raise ValueError(f"manual review trajectory hash mismatch for {instance_id}")

        prediction = json.loads(json.dumps(checkpoint["prediction"]))
        prediction["offline_audit"]["manual_review"] = status
        prediction["manual_review"] = {
            "status": status,
            "notes": review.get("review_notes", ""),
        }
        if status == "rejected":
            if prediction.get("error"):
                prediction["automatic_error"] = prediction["error"]
            prediction["raw_model_patch_sha256"] = _sha256_bytes(
                prediction.get("model_patch", "").encode()
            )
            prediction["model_patch"] = ""
            prediction["error"] = "manual_review_rejected"
        finalized.append(prediction)
        audit = json.loads(json.dumps(checkpoint["audit"]))
        audit["manual_review"] = status
        audit["manual_review_notes"] = review.get("review_notes", "")
        audit_cases.append(audit)

    _atomic_jsonl(output_dir / "agent_predictions.jsonl", finalized)
    _atomic_json(
        output_dir / "offline_audit.json",
        {
            "model": model,
            "timeout_seconds": timeout,
            "tool_network": "disabled",
            "cases": audit_cases,
            "finalized_count": len(finalized),
            "manually_reviewed_count": len(finalized),
            "manual_review_required": False,
        },
    )
    return finalized


def run_full(
    instances: list[dict],
    output_dir: Path,
    *,
    manifest: dict,
    resume: bool,
    review_all: bool,
    finalize_reviews: bool,
    model: str,
    timeout: int,
    workers: int,
    wave_size: int,
    github_token: str | None,
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
    private_root = inference_worktree_root("codex-offline-full")
    checkout_root = Path(tempfile.mkdtemp(prefix="run_", dir=private_root))
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
                _save_checkpoint(
                    output_dir,
                    prediction,
                    audit,
                    checkpoints,
                    ordered_ids,
                    model=model,
                    timeout=timeout,
                )
    finally:
        shutil.rmtree(checkout_root, ignore_errors=True)

    if len(checkpoints) != len(instances):
        raise RuntimeError(
            f"run incomplete: {len(checkpoints)}/{len(instances)} finalized"
        )
    for checkpoint in checkpoints.values():
        _verify_trajectory(output_dir, checkpoint)
    _write_review_files(
        output_dir, instances, checkpoints, review_all=review_all
    )
    if finalize_reviews:
        return _finalize_manual_reviews(
            output_dir,
            instances,
            checkpoints,
            model=model,
            timeout=timeout,
        )
    return [checkpoints[item]["prediction"] for item in ordered_ids]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", type=Path, default=Path("Issues_No_Tests_v1.xlsx"))
    parser.add_argument("--instances", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--wave-size", type=int, default=3)
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--review-all",
        action="store_true",
        help="Place every finalized instance in the manual audit queue.",
    )
    parser.add_argument(
        "--finalize-reviews",
        action="store_true",
        help="Require completed manual reviews and emit reviewed final predictions.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.model != MODEL:
        raise SystemExit(f"formal run requires --model {MODEL}")
    if args.timeout <= 0 or args.timeout > TIMEOUT:
        raise SystemExit(f"timeout must be in 1..{TIMEOUT}")
    if args.workers < 1 or args.workers > 3:
        raise SystemExit("workers must be in 1..3")
    if args.wave_size < 1 or args.wave_size > 3:
        raise SystemExit("wave-size must be in 1..3")
    if args.resume and args.dry_run:
        raise SystemExit("--resume and --dry-run cannot be combined")
    if args.finalize_reviews and not args.resume:
        raise SystemExit("--finalize-reviews requires --resume")
    if args.finalize_reviews and not args.review_all:
        raise SystemExit("--finalize-reviews requires --review-all")
    instances = select_full_instances(args.excel, args.instances)
    manifest = _manifest_config(
        excel_path=args.excel,
        instance_paths=args.instances,
        instances=instances,
        model=args.model,
        timeout=args.timeout,
        workers=args.workers,
        wave_size=args.wave_size,
        review_all=args.review_all,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    **manifest,
                    "pending_count": len(instances),
                },
                indent=2,
            )
        )
        return 0
    run_full(
        instances,
        args.output_dir,
        manifest=manifest,
        resume=args.resume,
        review_all=args.review_all,
        finalize_reviews=args.finalize_reviews,
        model=args.model,
        timeout=args.timeout,
        workers=args.workers,
        wave_size=args.wave_size,
        github_token=args.github_token,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
