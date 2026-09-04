#!/usr/bin/env python3
"""Curator reference submission for exercising the unified evaluator path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scientific import solve  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = solve("scibench_replication_0018_core", json.loads(args.input.read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "output.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
