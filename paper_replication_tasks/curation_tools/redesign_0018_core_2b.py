#!/usr/bin/env python3
"""Apply the parameter-robust 2B redesign to 0018_core hidden cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from energy_tsa_core_scientific import solve


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "scibench_replication_0018_core"
EXPECTED = {
    "case_01": "53e4243d20056536eac3fe09472b4cd8184bdfe6171cdfa1a7a1770c463cc98a",
    "case_02": "74de45dff0b7e9d96fd1e821774328c91fc8215cb71b301517196f0bf7f44b00",
    "case_08": "f5ec6678ed4780292547eab6100fedd268ab87c330e504dc8e21cef93d4dca22",
}
STRONG_ZERO_WIND_CASE_01 = "eb472f3f91e96e783df16c1edcf6fe06ad93c10af1a6db2a0d21006b9b66ab98"
STABILIZED_CASE_01 = "007c23ba37306cc2135d61f000abbd6292d7c9e24feb5de9c7e22ebddbbda1d4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stabilize-case-01", action="store_true")
    parser.add_argument("--isolate-case-01", action="store_true")
    args = parser.parse_args()
    if args.isolate_case_01:
        path = TASK / "hidden/cases/case_01/input.json"
        if sha(path) != STABILIZED_CASE_01:
            raise RuntimeError("refusing to isolate unexpected case_01")
        case = json.loads(path.read_text())
        x = np.asarray(case["x"], dtype=float)
        x[:, :, [1, 2, 4, 5]] = 0.0
        case["x"] = x.tolist()
        write(path, case)
        started = time.monotonic()
        output = solve(case)
        elapsed = time.monotonic() - started
        output_path = path.with_name("output.json")
        write(output_path, output)
        provenance_path = TASK / "hidden/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        record = next(row for row in provenance["cases"]
                      if row["split"] == "hidden" and row["case_id"] == "case_01")
        record.update({"input_sha256": sha(path), "output_sha256": sha(output_path),
                       "runtime_seconds": elapsed,
                       "gold_source": "independent_scipy_provisional_pending_official_replay"})
        provenance["runtime_seconds"]["hidden/case_01"] = elapsed
        write(provenance_path, provenance)
        return
    if args.stabilize_case_01:
        path = TASK / "hidden/cases/case_01/input.json"
        if sha(path) != STRONG_ZERO_WIND_CASE_01:
            raise RuntimeError("refusing to stabilize unexpected case_01")
        case = json.loads(path.read_text())
        x = np.asarray(case["x"], dtype=float)
        x[31:34, :, 3:] = .01 * np.maximum(x[30:31, :, 3:], x[34:35, :, 3:])
        case["x"] = np.round(x, 6).tolist()
        write(path, case)
        started = time.monotonic()
        output = solve(case)
        elapsed = time.monotonic() - started
        output_path = path.with_name("output.json")
        write(output_path, output)
        provenance_path = TASK / "hidden/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        record = next(row for row in provenance["cases"]
                      if row["split"] == "hidden" and row["case_id"] == "case_01")
        record.update({"input_sha256": sha(path), "output_sha256": sha(output_path),
                       "runtime_seconds": elapsed,
                       "gold_source": "independent_scipy_provisional_pending_official_replay"})
        provenance["runtime_seconds"]["hidden/case_01"] = elapsed
        write(provenance_path, provenance)
        return
    cases: dict[str, dict] = {}
    for case_id, expected in EXPECTED.items():
        path = TASK / "hidden/cases" / case_id / "input.json"
        if sha(path) != expected:
            raise RuntimeError(f"refusing to redesign unexpected {case_id}")
        cases[case_id] = json.loads(path.read_text())

    case = cases["case_01"]
    x = np.asarray(case["x"], dtype=float)
    x[31:34, :, :3] *= 1.25
    x[31:34, :, 3:] = 0.0
    case["x"] = np.round(x, 6).tolist()

    case = cases["case_02"]
    current = np.asarray(case["x"], dtype=float)
    original = np.concatenate((current[24:48], current[:24], current[48:]))
    case["x"] = np.concatenate(
        [original[index:index + 7] for index in range(0, 72, 7)][::-1]
    ).tolist()

    case = cases["case_08"]
    case["x"] = np.asarray(case["x"], dtype=float)[:72].tolist()
    case["q"] = 1

    provenance_path = TASK / "hidden/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    for case_id, value in cases.items():
        case_root = TASK / "hidden/cases" / case_id
        write(case_root / "input.json", value)
        started = time.monotonic()
        output = solve(value)
        elapsed = time.monotonic() - started
        if elapsed >= 600:
            raise RuntimeError(f"runtime gate failed: {case_id}: {elapsed}")
        write(case_root / "output.json", output)
        record = next(row for row in provenance["cases"]
                      if row["split"] == "hidden" and row["case_id"] == case_id)
        record.update({
            "input_sha256": sha(case_root / "input.json"),
            "output_sha256": sha(case_root / "output.json"),
            "runtime_seconds": elapsed,
            "gold_source": "independent_scipy_provisional_pending_official_replay",
        })
        provenance["runtime_seconds"][f"hidden/{case_id}"] = elapsed
    provenance.pop("g5_audit", None)
    provenance.pop("g8_audit", None)
    provenance["promotion_blockers"] = [
        "G4 parameter-robust 2B redesign pending complete uncertainty audit",
        "G5 and G8 evidence stale after hidden redesign",
        "G6 blind identification blocked by upstream 429",
        "G7 must be rerun on the final redesigned bundle",
    ]
    write(provenance_path, provenance)


if __name__ == "__main__":
    main()
