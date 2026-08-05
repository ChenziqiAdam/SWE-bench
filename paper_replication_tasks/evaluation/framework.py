"""v4 functional-case evaluator and safety checks."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

MAX_JSON_BYTES = 16 * 1024 * 1024


class EvaluationInputError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise EvaluationInputError(f"JSON too large: {path}")
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvaluationInputError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationInputError(f"JSON root must be an object: {path}")
    return value


def safe_relative(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise EvaluationInputError("path must be a non-empty POSIX relative path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(part in (".", "..") for part in parts.parts):
        raise EvaluationInputError(f"unsafe path: {relative}")
    candidate = root.joinpath(*parts.parts)
    cursor = root
    for part in parts.parts:
        cursor /= part
        if cursor.is_symlink():
            raise EvaluationInputError(f"symlink rejected: {relative}")
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise EvaluationInputError(f"path escapes root: {relative}") from exc
    return candidate


def _errors(actual: Any, expected: Any, path: str = "$") -> tuple[list[float], list[str]]:
    errors: list[float] = []
    structural: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return errors, [f"{path}: object keys/type differ"]
        for key in expected:
            child_errors, child_structural = _errors(actual[key], expected[key], f"{path}.{key}")
            errors.extend(child_errors)
            structural.extend(child_structural)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return errors, [f"{path}: array length/type differ"]
        if path.endswith(".eigenvalues") and all(
            isinstance(item, list) and len(item) == 2 for item in expected
        ):
            try:
                actual_complex = np.asarray([complex(float(item[0]), float(item[1])) for item in actual])
                expected_complex = np.asarray([complex(float(item[0]), float(item[1])) for item in expected])
            except (TypeError, ValueError, IndexError):
                return errors, [f"{path}: invalid complex-pair eigenvalues"]
            if not np.isfinite(actual_complex).all():
                return errors, [f"{path}: expected finite eigenvalues"]
            rows, columns = linear_sum_assignment(
                np.abs(actual_complex[:, None] - expected_complex[None, :])
            )
            for actual_index, expected_index in zip(rows, columns):
                errors.extend([
                    abs(actual_complex[actual_index].real - expected_complex[expected_index].real),
                    abs(actual_complex[actual_index].imag - expected_complex[expected_index].imag),
                ])
            return errors, structural
        for index, target in enumerate(expected):
            child_errors, child_structural = _errors(actual[index], target, f"{path}[{index}]")
            errors.extend(child_errors)
            structural.extend(child_structural)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(float(actual)):
            structural.append(f"{path}: expected finite number")
        else:
            errors.append(abs(float(actual) - float(expected)))
    elif actual != expected:
        structural.append(f"{path}: value differs")
    return errors, structural


def compare_output(actual: dict[str, Any], expected: dict[str, Any], tolerance: dict[str, float]) -> dict[str, Any]:
    errors, structural = _errors(actual, expected)
    maximum = max(errors, default=0.0)
    rmse = float(np.sqrt(np.mean(np.square(errors)))) if errors else 0.0
    passed = not structural and maximum <= tolerance["max_abs"] and rmse <= tolerance["rmse"]
    return {"passed": passed, "max_abs": maximum, "rmse": rmse, "structural_errors": structural[:10]}


def _file_map(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _validate_bundle_integrity(task_dir: Path) -> None:
    manifest = read_json(task_dir.parent / "manifest.json")
    rows = [row for row in manifest.get("tasks", []) if isinstance(row, dict) and row.get("task_id") == task_dir.name]
    if len(rows) != 1 or rows[0].get("lifecycle") != "validated":
        raise EvaluationInputError("task manifest is missing, duplicated, or not validated")
    row = rows[0]
    if row.get("public_files") != _file_map(task_dir / "public") or row.get("hidden_files") != _file_map(task_dir / "hidden"):
        raise EvaluationInputError("task bundle hash mismatch")


def evaluate(task_dir: Path, execution_report: Path) -> dict[str, Any]:
    task_dir = task_dir.resolve()
    _validate_bundle_integrity(task_dir)
    provenance = read_json(task_dir / "hidden/provenance.json")
    if (
        provenance.get("lifecycle") != "validated"
        or provenance.get("gold_source") != "pinned_official_checkout"
    ):
        raise EvaluationInputError(
            f"task is not eligible for scoring: {provenance.get('lifecycle', 'unknown')}"
        )
    report = read_json(execution_report)
    if report.get("schema_version") != 4 or report.get("task_id") != task_dir.name:
        raise EvaluationInputError("execution report schema/task mismatch")
    tolerance = read_json(task_dir / "hidden/tolerances.json")
    checks = []
    split_scores: dict[str, float] = {}
    valid_execution = True
    for split in ("public", "hidden"):
        cases = report.get("cases", {}).get(split)
        if not isinstance(cases, list):
            raise EvaluationInputError(f"missing {split} case reports")
        expected_dirs = sorted(path for path in (task_dir / split / "cases").iterdir() if path.is_dir())
        indexed = {row.get("case_id"): row for row in cases if isinstance(row, dict)}
        passed_count = 0
        for case_dir in expected_dirs:
            row = indexed.get(case_dir.name)
            passed = False
            diagnostics: dict[str, Any] = {}
            if not row or row.get("exit_code") != 0 or row.get("timed_out") is not False:
                valid_execution = False
                diagnostics["execution"] = "missing, failed, or timed out"
            else:
                output_root = safe_relative(execution_report.parent, row.get("output_dir"))
                output_path = safe_relative(output_root, "output.json")
                try:
                    actual = read_json(output_path)
                    expected = read_json(case_dir / "output.json")
                    if sha256_file(output_path) != row.get("output_sha256"):
                        raise EvaluationInputError("output hash mismatch")
                    diagnostics = compare_output(actual, expected, tolerance)
                    passed = diagnostics["passed"]
                except EvaluationInputError as exc:
                    valid_execution = False
                    diagnostics = {"error": str(exc)}
            passed_count += int(passed)
            checks.append({"id": f"{split}:{case_dir.name}", "split": split, "critical": True, "passed": passed, "diagnostics": diagnostics})
        split_scores[split] = passed_count / len(expected_dirs) if expected_dirs else 0.0
    score = 0.4 * split_scores["public"] + 0.6 * split_scores["hidden"]
    if not valid_execution:
        score = 0.0
    return {
        "schema_version": 4,
        "task_id": task_dir.name,
        "valid_execution": valid_execution,
        "public_score": split_scores["public"],
        "hidden_score": split_scores["hidden"],
        "score": float(score),
        "full_success": valid_execution and all(check["passed"] for check in checks),
        "checks": checks,
    }
