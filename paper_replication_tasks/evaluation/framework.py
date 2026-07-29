#!/usr/bin/env python3
"""Common, deterministic evaluation and safety utilities."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable


MAX_JSON_BYTES = 2 * 1024 * 1024
HASH_CHUNK_BYTES = 8 * 1024 * 1024
CATEGORIES = {"scientific", "protocol", "artifacts"}


class EvaluationInputError(ValueError):
    """The evaluator invocation or submission interface is malformed."""


@dataclass
class Check:
    id: str
    category: str
    passed: bool
    critical: bool = True
    message: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    task_id: str
    submission_dir: Path
    gold_path: Path
    manifest_path: Path
    results: dict[str, Any]
    gold: dict[str, Any]
    manifest: dict[str, Any]
    artifacts: dict[str, dict[str, Any]]
    checks: list[Check] = field(default_factory=list)

    def check(
        self,
        check_id: str,
        category: str,
        passed: bool,
        message: str = "",
        *,
        critical: bool = True,
        diagnostics: dict[str, Any] | None = None,
    ) -> bool:
        if category not in CATEGORIES:
            raise RuntimeError(f"unknown check category: {category}")
        self.checks.append(
            Check(
                id=check_id,
                category=category,
                passed=bool(passed),
                critical=critical,
                message=message,
                diagnostics=diagnostics or {},
            )
        )
        return bool(passed)

    def artifact_path(self, artifact_id: str) -> Path | None:
        record = self.artifacts.get(artifact_id)
        return None if record is None else safe_submission_path(
            self.submission_dir, record["path"]
        )


Plugin = Callable[[Context], None]


def read_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EvaluationInputError(f"cannot stat JSON input {path}: {exc}") from exc
    if size > max_bytes:
        raise EvaluationInputError(f"JSON input exceeds {max_bytes} bytes: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationInputError(f"JSON root must be an object: {path}")
    return value


def safe_submission_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise EvaluationInputError("artifact path must be a non-empty string")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise EvaluationInputError(f"unsafe artifact path: {relative!r}")
    if "\\" in relative:
        raise EvaluationInputError(f"artifact path must use POSIX separators: {relative!r}")
    root_real = root.resolve()
    candidate = root.joinpath(*posix.parts)
    current = root
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise EvaluationInputError(f"artifact path contains a symlink: {relative!r}")
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root_real)
    except (OSError, ValueError) as exc:
        raise EvaluationInputError(f"artifact escapes submission root: {relative!r}") from exc
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_results(task_id: str, results: dict[str, Any], root: Path) -> dict[str, dict[str, Any]]:
    expected_keys = {
        "schema_version",
        "task_id",
        "entrypoint",
        "protocol",
        "checkpoints",
        "artifacts",
    }
    unexpected_keys = set(results) - expected_keys
    missing_keys = expected_keys - set(results)
    if unexpected_keys or missing_keys:
        raise EvaluationInputError(
            "results.json fields do not match the public schema: "
            f"missing={sorted(missing_keys)}, unexpected={sorted(unexpected_keys)}"
        )
    if results.get("schema_version") != 1:
        raise EvaluationInputError("results.json schema_version must be 1")
    if results.get("task_id") != task_id:
        raise EvaluationInputError("results.json task_id does not match gold")
    if not isinstance(results.get("entrypoint"), str) or not results["entrypoint"].strip():
        raise EvaluationInputError("results.json entrypoint must be a non-empty string")
    for key in ("protocol", "checkpoints"):
        if not isinstance(results.get(key), dict):
            raise EvaluationInputError(f"results.json {key} must be an object")
    rows = results.get("artifacts")
    if not isinstance(rows, list):
        raise EvaluationInputError("results.json artifacts must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationInputError("each artifact must be an object")
        if set(row) != {"id", "path", "media_type"}:
            raise EvaluationInputError(
                "artifact fields must be exactly id, path, and media_type"
            )
        artifact_id = row.get("id")
        if not isinstance(artifact_id, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", artifact_id):
            raise EvaluationInputError(f"invalid artifact id: {artifact_id!r}")
        if artifact_id in indexed:
            raise EvaluationInputError(f"duplicate artifact id: {artifact_id}")
        safe_submission_path(root, row.get("path"))
        media_type = row.get("media_type")
        if not isinstance(media_type, str) or "/" not in media_type:
            raise EvaluationInputError(f"invalid media_type for {artifact_id}")
        indexed[artifact_id] = row
    return indexed


def validate_execution(ctx: Context) -> bool:
    manifest = ctx.manifest
    failures: list[str] = []
    if manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
    if manifest.get("task_id") != ctx.task_id:
        failures.append("manifest task_id mismatch")
    if not isinstance(manifest.get("attempt_id"), str) or not manifest.get("attempt_id"):
        failures.append("missing attempt_id")
    if manifest.get("exit_code") != 0:
        failures.append("submission execution exit_code is not zero")
    for key in ("command", "cwd", "started_at", "ended_at"):
        if not isinstance(manifest.get(key), str) or not manifest.get(key):
            failures.append(f"missing manifest field {key}")
    usage = manifest.get("resource_usage")
    if not isinstance(usage, dict) or any(
        not isinstance(usage.get(key), (int, float)) or usage.get(key) < 0
        for key in ("cpu_seconds", "wall_seconds", "peak_memory_bytes")
    ):
        failures.append("invalid resource_usage")
    before = manifest.get("before_files")
    after = manifest.get("after_files")
    final = manifest.get("artifacts")
    if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(final, dict):
        failures.append("manifest file-hash maps are missing")
        before, after, final = {}, {}, {}
    required = set(ctx.gold.get("required_artifact_ids", ctx.artifacts))
    for artifact_id in sorted(required - set(ctx.artifacts)):
        failures.append(f"required artifact absent from results.json: {artifact_id}")
    for artifact_id, row in ctx.artifacts.items():
        expected_media = ctx.gold.get("required_artifacts", {}).get(artifact_id)
        if expected_media is not None and row.get("media_type") != expected_media:
            failures.append(f"media type mismatch: {artifact_id}")
        relative = row["path"]
        path = safe_submission_path(ctx.submission_dir, relative)
        if not path.is_file():
            failures.append(f"missing artifact file: {artifact_id}")
            continue
        actual = sha256_file(path)
        final_row = final.get(artifact_id)
        if not isinstance(final_row, dict):
            failures.append(f"artifact absent from manifest: {artifact_id}")
            continue
        if final_row.get("path") != relative or final_row.get("sha256") != actual:
            failures.append(f"manifest final hash mismatch: {artifact_id}")
        if after.get(relative) != actual:
            failures.append(f"manifest after hash mismatch: {artifact_id}")
        if before.get(relative) == actual:
            failures.append(f"artifact was not newly created or modified: {artifact_id}")
    passed = not failures
    ctx.check(
        "trusted_execution",
        "protocol",
        passed,
        "trusted execution manifest is valid" if passed else "; ".join(failures),
    )
    return passed


def valid_pdf(path: Path) -> tuple[bool, str]:
    try:
        size = path.stat().st_size
        if size < 64:
            return False, "PDF is too small"
        with path.open("rb") as handle:
            head = handle.read(8)
            handle.seek(max(0, size - 2048))
            tail = handle.read()
        if not head.startswith(b"%PDF-"):
            return False, "missing PDF header"
        if b"%%EOF" not in tail:
            return False, "missing PDF EOF marker"
        return True, ""
    except OSError as exc:
        return False, str(exc)


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def close_scalar(actual: Any, expected: float, atol: float, rtol: float = 0.0) -> bool:
    return finite_number(actual) and math.isclose(
        float(actual), float(expected), abs_tol=atol, rel_tol=rtol
    )


def cross_check_scalar(
    ctx: Context, key: str, recomputed: float, *, atol: float, rtol: float = 0.0
) -> None:
    claimed = ctx.results["checkpoints"].get(key)
    ctx.check(
        f"reported_{key}",
        "scientific",
        close_scalar(claimed, recomputed, atol, rtol),
        f"reported {key} must agree with the value recomputed from artifacts",
        diagnostics={"reported": claimed, "recomputed": recomputed},
    )


def check_required_artifacts(ctx: Context, required: Iterable[str]) -> None:
    required_set = set(required)
    actual_set = set(ctx.artifacts)
    missing = sorted(required_set - actual_set)
    extra = sorted(actual_set - required_set)
    ctx.check(
        "artifact_index",
        "artifacts",
        not missing and not extra,
        "artifact index is complete" if not missing and not extra else "artifact index mismatch",
        diagnostics={"missing": missing, "unexpected": extra},
    )
    for artifact_id in sorted(required_set & actual_set):
        path = ctx.artifact_path(artifact_id)
        ctx.check(
            f"artifact_present_{artifact_id}",
            "artifacts",
            bool(path and path.is_file()),
            f"required artifact {artifact_id} exists",
        )


def score_checks(
    checks: list[Check], valid_execution: bool, weights: dict[str, float]
) -> float:
    if not valid_execution:
        return 0.0
    if checks and all(check.passed for check in checks):
        return 1.0
    if (
        not isinstance(weights, dict)
        or set(weights) - CATEGORIES
        or any(
            not finite_number(weight) or float(weight) < 0.0
            for weight in weights.values()
        )
        or not math.isclose(sum(map(float, weights.values())), 1.0, abs_tol=1e-12)
    ):
        raise EvaluationInputError("gold scoring weights must be nonnegative and sum to 1")
    total = 0.0
    for category, weight in weights.items():
        selected = [check for check in checks if check.category == category]
        fraction = (
            sum(1 for check in selected if check.passed) / len(selected)
            if selected
            else 0.0
        )
        total += weight * fraction
    return round(min(1.0, max(0.0, total)), 12)


def evaluate(
    submission_dir: Path,
    gold_path: Path,
    manifest_path: Path,
    plugin: Plugin,
) -> dict[str, Any]:
    root = submission_dir.resolve()
    if not root.is_dir():
        raise EvaluationInputError(f"submission directory does not exist: {root}")
    gold = read_json(gold_path)
    task_id = gold.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise EvaluationInputError("gold task_id is missing")
    results = read_json(root / "results.json")
    artifacts = _validate_results(task_id, results, root)
    manifest = read_json(manifest_path)
    ctx = Context(
        task_id=task_id,
        submission_dir=root,
        gold_path=gold_path.resolve(),
        manifest_path=manifest_path.resolve(),
        results=results,
        gold=gold,
        manifest=manifest,
        artifacts=artifacts,
    )
    valid_execution = validate_execution(ctx)
    plugin(ctx)
    score = score_checks(ctx.checks, valid_execution, gold.get("scoring", {}))
    full_success = valid_execution and all(
        check.passed for check in ctx.checks if check.critical
    )
    return {
        "schema_version": 1,
        "task_id": task_id,
        "valid_execution": valid_execution,
        "score": score,
        "full_success": full_success,
        "checks": [asdict(check) for check in ctx.checks],
    }


def run_cli(plugin: Plugin, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.submission_dir, args.gold, args.run_manifest, plugin)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 0
    except EvaluationInputError as exc:
        print(f"evaluation input error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # evaluator defect or corrupt trusted gold
        print(f"evaluator error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
