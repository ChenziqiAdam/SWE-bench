#!/usr/bin/env python3
"""Construct the non-promoted 0018_core bundle and local scientific gold."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from energy_tsa_core_common import TASK_ID
from energy_tsa_core_scientific import solve

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/private/tmp/scibench_0018_plan_repo")
COMMIT = "c162068f61bafbe640bbd40ee4a47312498ed153"
COLS = ["demand_region2", "demand_region4", "demand_region5",
        "wind_region2", "wind_region5", "wind_region6"]


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _block(frame: pd.DataFrame, start: str, days: int) -> np.ndarray:
    values = frame.loc[start:].iloc[:days * 24][COLS].to_numpy(dtype=float)
    if values.shape != (days * 24, 6): raise RuntimeError("source block is incomplete")
    return values.reshape(days, 24, 6)


def cases(frame: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    def case(x: np.ndarray, n: int, p: float, q: int) -> dict:
        return {"x": np.round(x, 6).tolist(), "n": n, "p": p, "q": q}
    public_q2 = _block(frame, "2007-08-09", 120)
    public_q2[:, :, [1, 2, 4, 5]] = 0.0
    public = [
        case(_block(frame, "1986-02-03", 60), 8, .10, 0),
        case(_block(frame, "1991-04-17", 90), 12, .10, 1),
        case(public_q2, 16, .05, 2),
    ]
    a = _block(frame, "2011-01-11", 72); a[31:34, :, :3] *= 1.6875
    a[31:34, :, 3:] = .01 * np.maximum(a[30:31, :, 3:], a[34:35, :, 3:])
    a[:, :, [1, 2, 4, 5]] = 0
    base = _block(frame, "1998-03-01", 72)
    chronology = np.concatenate([base[i:i + 7] for i in range(0, 72, 7)][::-1])
    c = _block(frame, "2002-10-01", 60); c[37, :, :3] *= 1.65; c[37, :, 3:] = 0
    d = _block(frame, "2015-05-12", 84); d[50:52, :, :3] *= 1.2; d[50:52, :, 3:] *= .12
    e = _block(frame, "1983-09-03", 64); e[:, :, 5] = .25
    f = _block(frame, "1994-06-01", 48); f[:, :, :3] *= .55; f[:, :, 3:] = np.maximum(f[:, :, 3:], .65)
    g = np.concatenate((_block(frame, "2009-01-01", 45), _block(frame, "2009-07-01", 45)))
    h = _block(frame, "2016-09-01", 72)
    hidden = [case(a, 10, .10, 1), case(chronology, 10, .10, 1), case(c, 9, .10, 0),
              case(d, 12, .10, 1), case(e, 9, .10, 2), case(f, 12, .20, 0),
              case(g, 14, .10, 1), case(h, 18, .20, 1)]
    return public, hidden


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair-public-03", action="store_true")
    parser.add_argument("--repair-all", action="store_true")
    args = parser.parse_args()
    task = ROOT / TASK_ID
    if args.repair_all:
        provenance_path = task / "hidden/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        for split in ("public", "hidden"):
            for root in sorted((task / split / "cases").glob("case_*")):
                value = json.loads((root / "input.json").read_text())
                started = time.monotonic(); output = solve(value); elapsed = time.monotonic() - started
                if elapsed >= 600: raise RuntimeError(f"runtime gate failed: {split}/{root.name}: {elapsed}")
                write_json(root / "output.json", output)
                key = f"{split}/{root.name}"; provenance["runtime_seconds"][key] = elapsed
                record = next(row for row in provenance["cases"] if row["split"] == split and row["case_id"] == root.name)
                record["output_sha256"] = sha(root / "output.json"); record["runtime_seconds"] = elapsed
        write_json(provenance_path, provenance)
        return
    if args.repair_public_03:
        root = task / "public/cases/case_03"
        value = json.loads((root / "input.json").read_text())
        started = time.monotonic(); output = solve(value); elapsed = time.monotonic() - started
        if elapsed >= 600: raise RuntimeError(f"runtime gate failed: public/case_03: {elapsed}")
        write_json(root / "output.json", output)
        provenance_path = task / "hidden/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["runtime_seconds"]["public/case_03"] = elapsed
        record = next(row for row in provenance["cases"] if row["split"] == "public" and row["case_id"] == "case_03")
        record["output_sha256"] = sha(root / "output.json"); record["runtime_seconds"] = elapsed
        write_json(provenance_path, provenance)
        return
    if task.exists(): raise RuntimeError(f"refusing to overwrite {task}")
    if not SOURCE.is_dir() or SOURCE.joinpath(".git").exists() is False:
        raise RuntimeError("missing pinned source checkout")
    import subprocess
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    if head != COMMIT: raise RuntimeError("source checkout is not pinned")
    frame = pd.read_csv(SOURCE / "data/demand_wind_solar.csv", index_col=0)
    frame.index = pd.to_datetime(frame.index)
    public, hidden = cases(frame)
    records = []; runtimes = {}
    for split, suite in (("public", public), ("hidden", hidden)):
        for index, value in enumerate(suite, 1):
            case_id = f"case_{index:02d}"; root = task / split / "cases" / case_id
            write_json(root / "input.json", value)
            started = time.monotonic(); output = solve(value); elapsed = time.monotonic() - started
            if elapsed >= 600: raise RuntimeError(f"runtime gate failed: {split}/{case_id}: {elapsed}")
            write_json(root / "output.json", output); runtimes[f"{split}/{case_id}"] = elapsed
            records.append({"split": split, "case_id": case_id, "input_sha256": sha(root / "input.json"),
                            "output_sha256": sha(root / "output.json"), "runtime_seconds": elapsed,
                            "gold_source": "independent_scipy_candidate"})
    shutil.copyfile(ROOT / "scibench_replication_0018/public/paper.pdf", task / "public/paper.pdf")
    (task / "public/task.md").write_text(
        "# scibench_replication_0018_core\n\n"
        "Implement `solution.py`. The runner invokes it with `--input input.json --output new-output-dir`; "
        "write a finite `output.json`.\n")
    write_json(task / "public/interface.schema.json", {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "task_id", "entrypoint"],
        "properties": {"schema_version": {"const": 4}, "task_id": {"const": TASK_ID},
                       "entrypoint": {"const": ["python", "solution.py"]}},
    })
    write_json(task / "hidden/tolerances.json", {"comparison": "fieldwise", "field_rules": {
        "y": {"atol": 0.014901655163157556, "rtol": 6.3786900054417255e-06},
        "z": {"atol": 0.0, "rtol": 0.0},
        "r": {"atol": 0.0, "rtol": 0.0}, "w": {"atol": 0.0, "rtol": 0.0}}})
    write_json(task / "hidden/provenance.json", {
        "schema_version": 4, "task_id": TASK_ID, "lifecycle": "revise",
        "repository": "https://github.com/ahilbers/a_posteriori_tsa_storage", "commit": COMMIT,
        "legacy_task_preserved": "scibench_replication_0018", "cases": records,
        "candidate_implementation": "curation_tools/energy_tsa_core_scientific.py",
        "runtime_seconds": runtimes,
        "promotion_blockers": ["G5-G8 evidence must be regenerated after rebuilding the bundle"],
    })
    write_json(ROOT / "curation_reports/0018_core_validation.json", {
        "task_id": TASK_ID, "status": "REVISE", "gates": {f"G{i}": False for i in range(1, 9)},
        "note": "Candidate bundle generated; promotion is intentionally blocked pending complete evidence."})


if __name__ == "__main__": main()
