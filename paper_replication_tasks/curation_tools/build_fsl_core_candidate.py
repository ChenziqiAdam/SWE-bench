#!/usr/bin/env python3
"""Build the neutral-name FSL candidate and retain two official runs."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from fsl_core_scientific import solve as independent_solve

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidates/fsl_core_candidate"
EVIDENCE = ROOT / "curation_reports/official_runs/fsl_core_candidate"
OFFICIAL_PYTHON = Path("/private/tmp/scibench-fsl-official/bin/python")
CHECKOUTS = [Path("/private/tmp/fsl_run_1"), Path("/private/tmp/fsl_run_2")]
COMMIT = "006852b348a48a20a9a0e584cf73f08c8964ef98"


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(values) -> list[list[float]]:
    return [[float(z.real), float(z.imag)] for z in np.asarray(values, complex).reshape(-1)]


def _one_dimensional(n: int, m: int, terms: dict[int, complex]) -> dict:
    coefficients = np.zeros(2**n, complex)
    for frequency, amplitude in terms.items():
        coefficients[frequency % coefficients.size] = amplitude
    return {"dimension": 1, "n": n, "m": m, "samples": _pairs(np.fft.fft(coefficients))}


def _two_dimensional(n: int, m: int, terms: dict[tuple[int, int], complex]) -> dict:
    coefficients = np.zeros((2**n, 2**n), complex)
    for (first, second), amplitude in terms.items():
        coefficients[first % coefficients.shape[0], second % coefficients.shape[1]] = amplitude
    return {"dimension": 2, "n": n, "m": m, "samples": _pairs(np.fft.fft2(coefficients))}


def cases() -> tuple[list[dict], list[dict], list[dict]]:
    public = [
        _one_dimensional(5, 2, {0: 1.4, 1: 0.55 - 0.2j, -1: 0.55 + 0.2j, 3: -0.18j, -3: 0.18j}),
        _one_dimensional(6, 3, {0: 0.3 + 0.4j, 1: -0.8 + 0.15j, -2: 0.45 - 0.7j, 5: -0.2 - 0.35j, -7: 0.12 + 0.5j}),
        _two_dimensional(3, 1, {(0, 0): 0.8 + 0.1j, (1, 0): 0.3 - 0.5j, (0, -1): -0.4 + 0.2j, (-1, 1): 0.65 + 0.35j}),
    ]
    hidden_specs = [
        ("DC and sparse support", _one_dimensional(4, 2, {0: -0.7 + 0.9j, 2: 0.25 - 0.4j})),
        ("negative-frequency indexing", _one_dimensional(5, 2, {0: 0.2, -1: 0.75 + 0.1j, -3: -0.6 + 0.45j})),
        ("highest retained frequency", _one_dimensional(6, 3, {0: -0.1j, 7: 0.9 - 0.2j, -7: -0.35 - 0.65j})),
        ("phase branch cut", _one_dimensional(5, 2, {0: np.exp(1j * (np.pi - 1e-9)), 1: 0.8 * np.exp(-1j * (np.pi - 2e-9)), -1: 0.45j, 3: -0.2 + 0.1j})),
        ("n equals m plus one", _one_dimensional(4, 3, {0: 0.25 + 0.3j, 2: -0.4j, -3: 0.55 + 0.1j, 7: -0.2 + 0.7j})),
        ("large zero-padding gap", _one_dimensional(9, 1, {0: 0.9 - 0.2j, 1: -0.35 + 0.5j, -1: 0.15 - 0.45j})),
        ("two-dimensional quadrant ordering", _two_dimensional(4, 2, {(0, 0): 0.2, (3, 3): 0.4 + 0.1j, (3, -3): -0.7j, (-3, 3): -0.35 + 0.6j, (-3, -3): 0.8 - 0.2j})),
        ("two-dimensional axis and endian asymmetry", _two_dimensional(5, 2, {(0, 0): -0.1 + 0.2j, (1, -2): 0.9 + 0.3j, (-3, 2): -0.5 + 0.65j, (3, 0): 0.25j, (0, -1): -0.7 + 0.1j})),
    ]
    return public, [case for _, case in hidden_specs], [
        {"case_id": f"case_{index:02d}", "hazard": name}
        for index, (name, _) in enumerate(hidden_specs, 1)
    ]


def _flatten_numbers(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten_numbers(item, key if not prefix else prefix)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_numbers(item, prefix)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield prefix, float(value)


def main() -> None:
    if CANDIDATE.exists() or EVIDENCE.exists():
        raise RuntimeError("refusing to overwrite existing candidate/evidence")
    if any(subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip() != COMMIT for path in CHECKOUTS):
        raise RuntimeError("official checkout commit mismatch")
    if any(subprocess.check_output(["git", "-C", str(path), "status", "--porcelain"], text=True).strip() for path in CHECKOUTS):
        raise RuntimeError("official checkout is dirty")

    public, hidden, hazards = cases()
    all_cases = [(split, i, case) for split, rows in (("public", public), ("hidden", hidden)) for i, case in enumerate(rows, 1)]
    with tempfile.TemporaryDirectory(prefix="fsl_candidate_", dir=ROOT) as temporary:
        stage = Path(temporary)
        staged_task = stage / "task"
        staged_evidence = stage / "evidence"
        official_runs: list[list[dict]] = []
        adapter = ROOT / "curation_tools/fsl_official_adapter.py"
        for run, checkout in enumerate(CHECKOUTS, 1):
            values = []
            for split, index, case in all_cases:
                input_path = stage / f"inputs/{split}_case_{index:02d}.json"
                output_path = staged_evidence / f"run_{run}/{split}_case_{index:02d}.json"
                _write(input_path, case)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([str(OFFICIAL_PYTHON), str(adapter), "--checkout", str(checkout), "--input", str(input_path), "--output", str(output_path)], check=True)
                values.append(json.loads(output_path.read_text()))
            official_runs.append(values)
        if json.dumps(official_runs[0], sort_keys=True, separators=(",", ":")) != json.dumps(official_runs[1], sort_keys=True, separators=(",", ":")):
            raise RuntimeError("official runs are not byte-identical after canonical JSON normalization")

        maxima = {name: 0.0 for name in ("coefficient_state", "rotation_y", "rotation_z", "phase", "statevector")}
        independent_values = []
        for (split, index, _), official in zip(all_cases, official_runs[0]):
            input_path = stage / f"inputs/{split}_case_{index:02d}.json"
            independent = independent_solve(input_path)
            independent_values.append(independent)
            _write(staged_evidence / f"independent/{split}_case_{index:02d}.json", independent)
            for field in maxima:
                left = [number for key, number in _flatten_numbers(official[field], field)]
                right = [number for key, number in _flatten_numbers(independent[field], field)]
                if len(left) != len(right):
                    raise RuntimeError(f"independent shape mismatch: {field}")
                maxima[field] = max(maxima[field], max((abs(a - b) for a, b in zip(left, right)), default=0.0))

        tolerance = {"comparison": "fieldwise", "field_rules": {
            field: {"atol": max(1e-10, 8.0 * error), "rtol": 1e-10}
            for field, error in maxima.items()
        }}
        if any(rule["atol"] > 1e-7 for rule in tolerance["field_rules"].values()):
            raise RuntimeError(f"official/independent discrepancy too large: {maxima}")

        records = []
        for (split, index, case), output in zip(all_cases, official_runs[0]):
            case_root = staged_task / split / "cases" / f"case_{index:02d}"
            _write(case_root / "input.json", case)
            _write(case_root / "output.json", output)
            records.append({"split": split, "case_id": f"case_{index:02d}", "input_sha256": _sha(case_root / "input.json"), "output_sha256": _sha(case_root / "output.json")})

        public_root = staged_task / "public"
        public_root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile("/private/tmp/fsl_paper.pdf", public_root / "paper.pdf")
        (public_root / "task.md").write_text("solution.py\n")
        _write(public_root / "interface.schema.json", {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
            "required": ["schema_version", "task_id", "entrypoint"],
            "properties": {"schema_version": {"const": 4}, "task_id": {"const": "candidate_core"}, "entrypoint": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}]}},
        })
        _write(staged_task / "hidden/tolerances.json", tolerance)
        _write(staged_task / "hidden/provenance.json", {
            "schema_version": 4, "lifecycle": "candidate", "candidate_name": "fsl_core_candidate",
            "repository": "https://github.com/mcmahon-lab/Fourier-Series-Loader", "commit": COMMIT,
            "paper_version": "arXiv:2302.03888v3 (journal-complete author manuscript)", "paper_sha256": _sha(public_root / "paper.pdf"),
            "gold_source": "pinned_official_checkout", "cases": records, "hazards": hazards,
            "official_reproduction": {"two_clean_runs_byte_identical": True, "adapter_sha256": _sha(adapter), "raw_and_normalized_outputs": "curation_reports/official_runs/fsl_core_candidate"},
            "independent_audit": {"status": "passed", "maximum_absolute_discrepancy": max(maxima.values()), "field_maximum_absolute_discrepancy": maxima, "derived_tolerances": tolerance},
            "independent_implementation_sha256": _sha(ROOT / "curation_tools/fsl_core_scientific.py"),
            "environment_lock_sha256": _sha(ROOT / "curation_tools/environments/fsl-candidate-environment.yml"),
        })
        CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(staged_task, CANDIDATE)
        shutil.move(staged_evidence, EVIDENCE)
    print(json.dumps({"candidate": str(CANDIDATE), "maximum_discrepancy": maxima, "tolerances": tolerance}, indent=2))


if __name__ == "__main__":
    main()
