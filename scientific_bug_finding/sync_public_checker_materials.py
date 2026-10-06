#!/usr/bin/env python3
"""Generate agent-facing checker materials from the reviewed curator manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_checker_banks import PUBLIC_FIELDS


TRADITIONAL_FIELDS = (
    "id", "family", "source", "symbol", "software_property", "precondition",
    "invariant", "observation_point", "alarm", "rationale",
)


def sync_traditional(curator_manifest: Path, repository: Path) -> None:
    """Write TRADITIONAL_CHECKERS.{json,md} (reference-group bank, SANITIZER.md 12)."""
    payload = json.loads(curator_manifest.read_text())
    active = [{f: item[f] for f in TRADITIONAL_FIELDS} for item in payload["sanitizers"]]
    (repository / "TRADITIONAL_CHECKERS.json").write_text(json.dumps(active, indent=2) + "\n")
    lines = [
        "# Traditional checkers (generic software-correctness sanitizers)",
        "",
        "Inactive unless `SCIBENCH_TRADITIONAL_LOG` names a writable file. "
        "Hooks are called from the instrumented modules.",
        "",
        "Every checker is skipped when any of its arguments holds a finite number "
        "larger than 1e100 in magnitude (float64 overflow range, not a defect); "
        "preconditions below may be stricter.",
        "",
    ]
    for it in active:
        lines.append(
            f"- **{it['id']}** `{it['symbol']}` ({it['source']}) — {it['software_property']}. "
            f"Precondition: {it['precondition']}. Invariant: {it['invariant']}. "
            f"Observed {it['observation_point']}. Alarm: {it['alarm']}."
        )
    (repository / "TRADITIONAL_CHECKERS.md").write_text("\n".join(lines) + "\n")


def sync(curator_manifest: Path, repository: Path) -> None:
    payload = json.loads(curator_manifest.read_text())
    active = [
        {field: item[field] for field in PUBLIC_FIELDS}
        for item in payload["sanitizers"]
    ]
    public = {
        "schema_version": payload.get("schema_version", 2),
        "base_commit": payload["base_commit"],
        "note": (
            "Complete public scientific-checker bank. Inactive unless "
            "SCIBENCH_TRIGGER_LOG is set."
        ),
        "checkers": active,
    }
    (repository / "SCIENTIFIC_CHECKERS.json").write_text(
        json.dumps(public, indent=2, sort_keys=False) + "\n"
    )

    families = len({item["family"] for item in active})
    lines = [
        "# Scientific checkers",
        "",
        f"This bank exposes all {len(active)} instrumented checkers in {families} families.",
        "Every listed checker ID is public and scored.",
        "",
        "Set `SCIBENCH_TRIGGER_LOG` to a writable file and exercise the normal",
        "public API. Direct logger calls and synthetic fault injection are not",
        "valid benchmark triggers.",
        "",
        "See `SCIENTIFIC_CHECKERS.json` for each checker’s precondition,",
        "invariant, observation point, and alarm predicate.",
        "",
    ]
    (repository / "SCIENTIFIC_CHECKERS.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--traditional", action="store_true")
    args = parser.parse_args()
    if args.traditional:
        sync_traditional(args.manifest.resolve(), args.repo.resolve())
    else:
        sync(args.manifest.resolve(), args.repo.resolve())


if __name__ == "__main__":
    main()
