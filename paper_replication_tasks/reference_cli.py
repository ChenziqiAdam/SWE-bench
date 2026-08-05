#!/usr/bin/env python3
"""Clean-room reference submission used by acceptance tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scientific import solve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    result = solve(args.task_id, value)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "output.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
