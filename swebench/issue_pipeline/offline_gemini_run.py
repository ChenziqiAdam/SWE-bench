"""Resumable Gemini inference using the audited Antigravity CLI protocol."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

import openpyxl

from swebench.eval_pipeline.agent_inference import _clone_repo_at_commit
from swebench.eval_pipeline.inference_security import (
    inference_input_hash,
    inference_worktree_root,
)
from swebench.issue_pipeline.offline_codex_run import (
    ABNORMAL_FILE_COUNT,
    MAX_FETCH_ATTEMPTS,
    _atomic_json,
    _atomic_jsonl,
    _canonical_hash,
    _checkpoint_path,
    _file_hash,
    _load_checkpoints,
    _sha256_bytes,
    _verify_trajectory,
    _write_review_files,
    validate_checkout,
)
from swebench.issue_pipeline.offline_gemini_pilot import (
    AGENT_BACKEND,
    CLI_VERSION,
    MODEL,
    NETWORK_ISOLATION_LABEL,
    TIMEOUT,
    _jsonl_rows,
    _run_one,
    build_pilot_prompt,
    safety_settings,
    safety_settings_hash,
    validate_antigravity_cli,
)


FINAL_PROFILE = {
    "workbook_rows": 88,
    "instances": 84,
    "repos": {
        "lammps/lammps": 31,
        "openmm/openmm": 45,
        "rdkit/rdkit": 1,
        "biopython/biopython": 1,
        "qgis/QGIS": 1,
        "astropy/astropy": 1,
        "qutip/qutip": 2,
        "deepchem/deepchem": 2,
    },
    "duplicate_mappings": {
        "lammps__lammps-4339": [4216, 4337, 4338],
        "lammps__lammps-4443": [4373, 4398],
        "lammps__lammps-4481": [4487, 4491],
    },
}
MANIFEST_VERSION = 1


class QuotaLimitStop(RuntimeError):
    """Stop before checkpointing a quota-limited instance so resume retries it."""

    def __init__(self, instance_id: str):
        super().__init__(
            f"Antigravity quota/rate limit hit at {instance_id}; rerun with --resume "
            "after quota is available"
        )
        self.instance_id = instance_id


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
                rows_found.append(
                    {
                        "instance_id": str(row["Repo"]).replace("/", "__", 1)
                        + f"-{int(row['Closing PR #'])}",
                        "repo": str(row["Repo"]),
                        "issue_number": int(row["Issue Number"]),
                        "closing_pr": int(row["Closing PR #"]),
                        "sheet": sheet.title,
                    }
                )
    finally:
        workbook.close()

    ordered = list(dict.fromkeys(row["instance_id"] for row in rows_found))
    duplicates = {
        instance_id: [
            row["issue_number"]
            for row in rows_found
            if row["instance_id"] == instance_id
        ]
        for instance_id in ordered
        if sum(row["instance_id"] == instance_id for row in rows_found) > 1
    }
    row_repos = Counter(row["repo"] for row in rows_found)
    unique_repos = Counter(
        next(row["repo"] for row in rows_found if row["instance_id"] == item)
        for item in ordered
    )
    if (
        len(rows_found) != FINAL_PROFILE["workbook_rows"]
        or len(ordered) != FINAL_PROFILE["instances"]
        or duplicates != FINAL_PROFILE["duplicate_mappings"]
        or dict(unique_repos) != FINAL_PROFILE["repos"]
    ):
        raise ValueError(
            "workbook does not match Issues_No_Tests_final.xlsx: "
            f"rows={len(rows_found)}, unique_instances={len(ordered)}, "
            f"unique_repo_counts={dict(unique_repos)}, duplicate_mappings={duplicates}"
        )
    return {
        "row_count": len(rows_found),
        "unique_instance_count": len(ordered),
        "ordered_instance_ids": ordered,
        "duplicate_mappings": duplicates,
        "unique_repository_counts": dict(unique_repos),
        "workbook_row_repository_counts": dict(row_repos),
    }


def select_full_instances(excel_path: Path, instance_paths: list[Path]) -> list[dict]:
    """Select the exact 84 unique closing-PR instances in workbook order."""
    if len(instance_paths) != 1:
        raise ValueError("exactly one --instances source file is required")
    source_rows = _jsonl_rows(instance_paths[0])
    source_ids = [row.get("instance_id") for row in source_rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("instance source contains duplicate instance_id values")
    selection = _workbook_selection(excel_path)
    ordered_ids = selection["ordered_instance_ids"]
    by_id = dict(zip(source_ids, source_rows))
    missing = [item for item in ordered_ids if item not in by_id]
    extra = sorted(set(by_id) - set(ordered_ids))
    if missing or extra:
        raise ValueError(f"spreadsheet/source mismatch: missing={missing}, extra={extra}")
    selected = [by_id[item] for item in ordered_ids]
    for instance in selected:
        instance_id = instance.get("instance_id")
        if not re.fullmatch(r"[0-9a-f]{40}", str(instance.get("base_commit", ""))):
            raise ValueError(f"invalid base_commit for {instance_id}")
        if not (instance.get("problem_statement") or "").strip():
            raise ValueError(f"missing issue content for {instance_id}")
    if Counter(item["repo"] for item in selected) != FINAL_PROFILE["repos"]:
        raise ValueError("instance source has unexpected repository counts")
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
    settings = safety_settings()
    return {
        "manifest_version": MANIFEST_VERSION,
        "agent_backend": AGENT_BACKEND,
        "cli": {"name": "agy", "version": CLI_VERSION},
        "model": model,
        "timeout_seconds": timeout,
        "workers": workers,
        "wave_size": wave_size,
        "network_isolation": NETWORK_ISOLATION_LABEL,
        "antigravity_safety_configuration": settings,
        "antigravity_safety_configuration_sha256": safety_settings_hash(settings),
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
            "network_isolation": NETWORK_ISOLATION_LABEL,
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
        output_dir, ordered_ids, checkpoints, model=model, timeout=timeout
    )


def _fetch_with_retries(
    instance: dict,
    github_token: str | None,
    checkout_root: Path,
    clone: Callable[..., Path] = _clone_repo_at_commit,
) -> Path:
    errors = []
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            checkout = clone(
                instance["repo"], instance["base_commit"], github_token, checkout_root
            )
            validate_checkout(checkout, instance["base_commit"])
            return checkout
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
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
    """Complete every network fetch before starting any Antigravity process."""
    worktrees: dict[str, Path] = {}
    fetch_errors: list[BaseException] = []
    results: list[tuple[dict, dict]] = []
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
            try:
                results.append(future.result())
            finally:
                shutil.rmtree(worktrees[item["instance_id"]], ignore_errors=True)
    # Checkpoint every completed non-quota member before the run halts. Only
    # quota-limited instances remain pending for the next exact-manifest resume.
    results.sort(key=lambda item: item[0].get("error") == "quota_limit")
    yield from results


def _finalize_manual_reviews(
    output_dir: Path,
    instances: list[dict],
    checkpoints: dict[str, dict],
    *,
    model: str,
    timeout: int,
) -> list[dict]:
    value = json.loads((output_dir / "manual_review.json").read_text())
    rows = value.get("cases", [])
    reviews = {item.get("instance_id"): item for item in rows}
    ordered_ids = [item["instance_id"] for item in instances]
    if len(reviews) != len(rows) or set(reviews) != set(ordered_ids):
        raise ValueError("manual review must contain exactly all selected instances")
    finalized = []
    audits = []
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
        audits.append(audit)
    _atomic_jsonl(output_dir / "agent_predictions.jsonl", finalized)
    _atomic_json(
        output_dir / "offline_audit.json",
        {
            "model": model,
            "timeout_seconds": timeout,
            "network_isolation": NETWORK_ISOLATION_LABEL,
            "cases": audits,
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
    expected_prompts = [
        {"instance_id": item["instance_id"], "prompt": build_pilot_prompt(item)}
        for item in instances
    ]
    if resume:
        if not output_dir.is_dir():
            raise ValueError(f"resume output does not exist: {output_dir}")
        if json.loads((output_dir / "run_manifest.json").read_text()) != manifest:
            raise ValueError("resume manifest does not match the requested run")
        if _jsonl_rows(output_dir / "instances.jsonl") != instances:
            raise ValueError("resume instances.jsonl does not match the requested run")
        if _jsonl_rows(output_dir / "agent_prompts.jsonl") != expected_prompts:
            raise ValueError("resume agent_prompts.jsonl does not match the requested run")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "trajectories").mkdir()
        (output_dir / "checkpoints").mkdir()
        _atomic_json(output_dir / "run_manifest.json", manifest)
        _atomic_jsonl(output_dir / "instances.jsonl", instances)
        _atomic_jsonl(output_dir / "agent_prompts.jsonl", expected_prompts)

    checkpoints = _load_checkpoints(output_dir, ordered_ids)
    for checkpoint in checkpoints.values():
        _verify_trajectory(output_dir, checkpoint)
    _rebuild_outputs(
        output_dir, ordered_ids, checkpoints, model=model, timeout=timeout
    )
    pending = [item for item in instances if item["instance_id"] not in checkpoints]
    private_root = inference_worktree_root("antigravity-gemini-offline-full")
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
                if prediction.get("error") == "quota_limit":
                    raise QuotaLimitStop(prediction["instance_id"])
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
        raise RuntimeError(f"run incomplete: {len(checkpoints)}/{len(instances)} finalized")
    for checkpoint in checkpoints.values():
        _verify_trajectory(output_dir, checkpoint)
    _write_review_files(output_dir, instances, checkpoints, review_all=review_all)
    if finalize_reviews:
        return _finalize_manual_reviews(
            output_dir, instances, checkpoints, model=model, timeout=timeout
        )
    return [checkpoints[item]["prediction"] for item in ordered_ids]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", type=Path, default=Path("Issues_No_Tests_final.xlsx"))
    parser.add_argument("--instances", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--wave-size", type=int, default=3)
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--review-all", action="store_true")
    parser.add_argument("--finalize-reviews", action="store_true")
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
        print(json.dumps({**manifest, "pending_count": len(instances)}, indent=2))
        return 0
    validate_antigravity_cli()
    try:
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
    except QuotaLimitStop as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
