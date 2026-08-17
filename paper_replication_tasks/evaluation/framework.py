"""v4 functional-case evaluator and safety checks."""

from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
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
    if "moment_basis" in expected and "deterministic_equations" in expected and "jump_equations" in expected:
        try:
            actual = _canonicalize_conditional_moment_output(actual)
            expected = _canonicalize_conditional_moment_output(expected)
        except EvaluationInputError as exc:
            return {"passed": False, "max_abs": 0.0, "rmse": 0.0, "structural_errors": [str(exc)]}
    if tolerance.get("comparison") == "mixed":
        errors, relative, structural, within = _mixed_errors(
            actual, expected, float(tolerance["atol"]), float(tolerance["rtol"])
        )
        maximum = max(errors, default=0.0)
        rmse = float(np.sqrt(np.mean(np.square(errors)))) if errors else 0.0
        return {"passed": not structural and within, "max_abs": maximum, "rmse": rmse,
                "max_relative": max(relative, default=0.0), "structural_errors": structural[:10]}
    if tolerance.get("comparison") == "fieldwise":
        errors, relative, structural, within = _fieldwise_errors(actual, expected, tolerance)
        maximum = max(errors, default=0.0)
        rmse = float(np.sqrt(np.mean(np.square(errors)))) if errors else 0.0
        return {"passed": not structural and within, "max_abs": maximum, "rmse": rmse,
                "max_relative": max(relative, default=0.0), "structural_errors": structural[:10]}
    errors, structural = _errors(actual, expected)
    maximum = max(errors, default=0.0)
    rmse = float(np.sqrt(np.mean(np.square(errors)))) if errors else 0.0
    passed = not structural and maximum <= tolerance["max_abs"] and rmse <= tolerance["rmse"]
    return {"passed": passed, "max_abs": maximum, "rmse": rmse, "structural_errors": structural[:10]}


def _mixed_errors(actual: Any, expected: Any, atol: float, rtol: float, path: str = "$") -> tuple[list[float], list[float], list[str], bool]:
    errors: list[float] = []
    relative: list[float] = []
    structural: list[str] = []
    within = True
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return errors, relative, [f"{path}: object keys/type differ"], False
        children = ((actual[key], expected[key], f"{path}.{key}") for key in expected)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return errors, relative, [f"{path}: array length/type differ"], False
        children = ((actual[index], target, f"{path}[{index}]") for index, target in enumerate(expected))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(float(actual)):
            return errors, relative, [f"{path}: expected finite number"], False
        difference = abs(float(actual) - float(expected))
        errors.append(difference)
        relative.append(difference / max(abs(float(expected)), 1e-300))
        return errors, relative, structural, difference <= atol + rtol * abs(float(expected))
    else:
        return errors, relative, ([] if actual == expected else [f"{path}: value differs"]), actual == expected
    for child_actual, child_expected, child_path in children:
        child_errors, child_relative, child_structural, child_within = _mixed_errors(child_actual, child_expected, atol, rtol, child_path)
        errors.extend(child_errors); relative.extend(child_relative); structural.extend(child_structural)
        within &= child_within
    return errors, relative, structural, within


def _fieldwise_errors(actual: Any, expected: Any, tolerance: dict[str, Any], path: str = "$") -> tuple[list[float], list[float], list[str], bool]:
    """Mixed comparison with an explicit rule selected by output field name."""
    rules = tolerance.get("field_rules")
    if not isinstance(rules, dict) or not rules:
        return [], [], ["fieldwise comparison has no rules"], False
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return [], [], [f"{path}: object keys/type differ"], False
        children = [(actual[key], expected[key], f"{path}.{key}") for key in expected]
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [], [], [f"{path}: array length/type differ"], False
        children = [(actual[index], target, f"{path}[{index}]") for index, target in enumerate(expected)]
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(float(actual)):
            return [], [], [f"{path}: expected finite number"], False
        field = next((name for name in rules if f".{name}" in path), None)
        if field is None:
            return [], [], [f"{path}: no tolerance rule"], False
        rule = rules[field]
        difference = abs(float(actual) - float(expected))
        relative = difference / max(abs(float(expected)), 1e-300)
        return [difference], [relative], [], difference <= float(rule["atol"]) + float(rule["rtol"]) * abs(float(expected))
    else:
        return [], [], ([] if actual == expected else [f"{path}: value differs"]), actual == expected
    errors: list[float] = []; relative: list[float] = []; structural: list[str] = []; within = True
    for child_actual, child_expected, child_path in children:
        child_errors, child_relative, child_structural, child_within = _fieldwise_errors(child_actual, child_expected, tolerance, child_path)
        errors.extend(child_errors); relative.extend(child_relative); structural.extend(child_structural); within &= child_within
    return errors, relative, structural, within


def _canonicalize_conditional_moment_output(value: dict[str, Any]) -> dict[str, Any]:
    keys = {"moment_basis", "deterministic_equations", "jump_equations", "sample_times", "selected_state_trajectory", "conditional_moment_trajectory"}
    if not isinstance(value, dict) or set(value) != keys:
        raise EvaluationInputError("conditional-moment output keys differ")
    basis = value["moment_basis"]
    selected_trajectory = value["selected_state_trajectory"]
    if not isinstance(basis, list) or not basis or not isinstance(selected_trajectory, list) or not selected_trajectory:
        raise EvaluationInputError("empty or invalid moment basis/selected trajectory")
    latent_count = len(basis[0]) if isinstance(basis[0], list) else -1
    selected_count = len(selected_trajectory[0]) if isinstance(selected_trajectory[0], list) else -1
    moment_count = len(basis)
    reaction_count = len(value["jump_equations"]) if isinstance(value["jump_equations"], list) else -1
    if latent_count < 1 or selected_count < 1 or reaction_count < 1:
        raise EvaluationInputError("invalid conditional-moment dimensions")
    if any(not isinstance(row, list) or len(row) != latent_count or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in row) for row in basis):
        raise EvaluationInputError("invalid moment_basis")

    def equation(terms: Any) -> list[dict[str, Any]]:
        if not isinstance(terms, list):
            raise EvaluationInputError("equation must be an array")
        combined: dict[tuple[int, ...], Fraction] = {}
        for term in terms:
            if not isinstance(term, dict) or set(term) != {"coefficient", "selected_exponents", "rate_exponents", "moment_exponents"}:
                raise EvaluationInputError("invalid Laurent term keys")
            coefficient = term["coefficient"]
            vectors = (term["selected_exponents"], term["rate_exponents"], term["moment_exponents"])
            widths = (selected_count, reaction_count, moment_count)
            if (not isinstance(coefficient, list) or len(coefficient) != 2 or
                    any(isinstance(x, bool) or not isinstance(x, int) for x in coefficient) or coefficient[1] == 0):
                raise EvaluationInputError("invalid rational coefficient")
            if any(not isinstance(vector, list) or len(vector) != width or any(isinstance(x, bool) or not isinstance(x, int) for x in vector) for vector, width in zip(vectors, widths)):
                raise EvaluationInputError("invalid Laurent exponent vector")
            exponent_key = tuple(x for vector in vectors for x in vector)
            combined[exponent_key] = combined.get(exponent_key, Fraction()) + Fraction(coefficient[0], coefficient[1])
        rows = []
        for exponents, coefficient in sorted(combined.items()):
            if coefficient == 0:
                continue
            a, b = selected_count, selected_count + reaction_count
            rows.append({"coefficient": [coefficient.numerator, coefficient.denominator], "selected_exponents": list(exponents[:a]), "rate_exponents": list(exponents[a:b]), "moment_exponents": list(exponents[b:])})
        return rows

    deterministic = value["deterministic_equations"]
    jumps = value["jump_equations"]
    if not isinstance(deterministic, list) or len(deterministic) != moment_count:
        raise EvaluationInputError("deterministic equation shape mismatch")
    if not isinstance(jumps, list) or len(jumps) != reaction_count or any(not isinstance(row, list) or len(row) != moment_count for row in jumps):
        raise EvaluationInputError("jump equation shape mismatch")
    result = dict(value)
    result["deterministic_equations"] = [equation(row) for row in deterministic]
    result["jump_equations"] = [[equation(row) for row in reaction] for reaction in jumps]
    return result


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
