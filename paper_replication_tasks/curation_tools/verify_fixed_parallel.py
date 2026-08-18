#!/usr/bin/env python3
"""Verify parallel official execution against retained sequential Figure 2 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_fixed_sparsity_task import ROOT, cases
from fixed_sparsity_adapter import solve


def canonical(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    checkout = Path("/private/tmp/scibench_fixed_1")
    evidence = ROOT / "curation_reports/official_runs/0015/run_1/public_case_01.normalized.json"
    actual = solve(cases()[0][0], checkout)
    expected = json.loads(evidence.read_text(encoding="utf-8"))
    if canonical(actual) != canonical(expected):
        raise RuntimeError(f"parallel official mismatch: {canonical(actual)} != {canonical(expected)}")
    print(f"parallel official equivalence passed: {canonical(actual)}")


if __name__ == "__main__":
    main()
