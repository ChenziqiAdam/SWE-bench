#!/usr/bin/env python3
"""Reference submission entrypoint for task 0018: runs the real official Calliope/CBC pipeline
against a pinned clean checkout. Unlike other tasks' reference_cli.py (a fast, self-contained
independent implementation), this task's gold requires solving a MILP, so the reference solution
IS the official adapter itself -- proving the harness/scoring pipeline works end-to-end. The
independent, solver-neutral correctness audit is energy_tsa_scientific.py's cluster-assignment
match (see build_energy_tsa_task.py), not this entrypoint.

Usage: energy_reference_cli.py --checkout <clean-pinned-checkout> --input <input.json> --output <dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from energy_tsa_adapter import solve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = json.loads(args.input.read_text(encoding="utf-8"))
    result = solve(case, args.checkout)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "output.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
