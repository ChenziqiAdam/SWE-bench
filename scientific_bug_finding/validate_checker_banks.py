#!/usr/bin/env python3
"""Validate sanitizer metadata and optional instrumented repository checkouts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED = {
    "id",
    "family",
    "source",
    "symbol",
    "scientific_quantity",
    "precondition",
    "invariant",
    "observation_point",
    "alarm",
    "rationale",
}
PUBLIC_FIELDS = tuple(sorted(REQUIRED))
BANKS = {
    "biopython": (ROOT / "biopython_pilot/sanitizers.json", "Bio/_scientific_checkers.py", "BP"),
    "astropy": (ROOT / "astropy_pilot/sanitizers.json", "astropy/_scientific_checkers.py", "AP"),
    "obspy": (ROOT / "obspy_pilot/sanitizers.json", "obspy/_scientific_checkers.py", "OB"),
    "deepchem": (ROOT / "deepchem_pilot/sanitizers.json", "deepchem/_scientific_checkers.py", "DC"),
    "scanpy": (ROOT / "scanpy_pilot/sanitizers.json", "src/scanpy/_scientific_checkers.py", "SC"),
    "nilearn": (ROOT / "nilearn_pilot/sanitizers.json", "nilearn/_scientific_checkers.py", "NL"),
}


def load_items(path: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(path.read_text())
    return payload, payload["sanitizers"]


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def validate_bank(name: str, repo: Path | None) -> list[str]:
    metadata_path, checker_relpath, prefix = BANKS[name]
    payload, items = load_items(metadata_path)
    errors: list[str] = []
    ids = [item.get("id") for item in items]
    review = payload.get("quality_review", {})
    revised = set(review.get("revised_ids", []))
    if len(ids) != len(set(ids)):
        errors.append(f"{name}: duplicate sanitizer IDs")
    unknown_review_ids = revised - set(ids)
    if unknown_review_ids:
        errors.append(f"{name}: quality review has unknown IDs {sorted(unknown_review_ids)}")
    for index, item in enumerate(items):
        missing = sorted(REQUIRED - item.keys())
        if missing:
            errors.append(f"{name}[{index}]: missing fields {missing}")
        if not re.fullmatch(rf"{prefix}-[A-Z]+-\d{{3}}", str(item.get("id", ""))):
            errors.append(f"{name}[{index}]: invalid ID {item.get('id')!r}")
        for field in REQUIRED:
            if field in item and not str(item[field]).strip():
                errors.append(f"{item.get('id', name)}: empty {field}")

    if repo is None:
        return errors
    if not repo.is_dir():
        return errors + [f"{name}: checkout does not exist: {repo}"]
    expected_commits = [payload.get("instrumented_commit")]
    if review.get("local_repair_commit"):
        expected_commits.append(review["local_repair_commit"])
    expected_commits = [commit for commit in expected_commits if commit]
    actual_commit = git(repo, "rev-parse", "HEAD")
    if expected_commits and not any(
            actual_commit.startswith(commit) for commit in expected_commits):
        errors.append(f"{name}: HEAD {actual_commit} not in expected {expected_commits}")

    checker = repo / checker_relpath
    if not checker.is_file():
        return errors + [f"{name}: missing {checker_relpath}"]
    code_ids = set(re.findall(rf'["\']({prefix}-[A-Z]+-\d{{3}})["\']', checker.read_text()))
    if code_ids != set(ids):
        errors.append(
            f"{name}: metadata/code ID mismatch; missing={sorted(set(ids)-code_ids)}, "
            f"extra={sorted(code_ids-set(ids))}"
        )

    public_json = repo / "SCIENTIFIC_CHECKERS.json"
    public_md = repo / "SCIENTIFIC_CHECKERS.md"
    if not public_json.is_file():
        errors.append(f"{name}: missing public SCIENTIFIC_CHECKERS.json")
    else:
        public_payload = json.loads(public_json.read_text())
        public_items = (
            public_payload
            if isinstance(public_payload, list)
            else public_payload.get("sanitizers", public_payload.get("checkers", []))
        )
        # Historical quality-review labels remain provenance metadata; the
        # benchmark now exposes and scores the complete instrumented bank.
        curator_by_id = {item["id"]: item for item in items}
        public_by_id = {item.get("id"): item for item in public_items}
        if set(public_by_id) != set(curator_by_id):
            errors.append(
                f"{name}: public/curator ID mismatch; "
                f"missing={sorted(set(curator_by_id) - set(public_by_id))}, "
                f"extra={sorted(set(public_by_id) - set(curator_by_id))}"
            )
        else:
            mismatches = []
            for sanitizer_id, curator in curator_by_id.items():
                changed = [
                    field
                    for field in PUBLIC_FIELDS
                    if public_by_id[sanitizer_id].get(field) != curator.get(field)
                ]
                if changed:
                    mismatches.append(f"{sanitizer_id}({','.join(changed)})")
            if mismatches:
                errors.append(
                    f"{name}: public metadata differs: {', '.join(mismatches)}"
                )
    if not public_md.is_file():
        errors.append(f"{name}: missing public SCIENTIFIC_CHECKERS.md")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--biopython-repo", type=Path)
    parser.add_argument("--astropy-repo", type=Path)
    parser.add_argument("--obspy-repo", type=Path)
    parser.add_argument("--deepchem-repo", type=Path)
    parser.add_argument("--scanpy-repo", type=Path)
    parser.add_argument("--nilearn-repo", type=Path)
    args = parser.parse_args()
    all_errors: list[str] = []
    for name in BANKS:
        errors = validate_bank(name, getattr(args, f"{name}_repo"))
        count = len(load_items(BANKS[name][0])[1])
        print(f"{name}: {count} metadata entries; {len(errors)} error(s)")
        all_errors.extend(errors)
    for error in all_errors:
        print(f"ERROR: {error}")
    return bool(all_errors)


if __name__ == "__main__":
    raise SystemExit(main())
