"""Stage 2: Build SWEbenchInstance-compatible dicts from fetched PR data."""
from __future__ import annotations

import json
import logging
import re
import requests
from pathlib import Path
from typing import Optional
from unidiff import PatchSet

from swebench.collect.utils import Repo
from swebench.eval_pipeline.constants import COL_REPO, COL_PR_NUMBER, COL_PAPER_REFERENCE

logger = logging.getLogger(__name__)

# Top-level test function: +def test_foo(
_TEST_FUNC_TOP_RE = re.compile(r"^\+(?:async\s+)?def\s+(test_\w+)\s*\(")
# Class method test (4 spaces indent): +    def test_foo(
_TEST_FUNC_METHOD_RE = re.compile(r"^\+    (?:async\s+)?def\s+(test_\w+)\s*\(")
# Class definition in context lines (no +/-): class TestFoo:
_CLASS_DEF_RE = re.compile(r"^ ?class\s+(\w+)\s*[:(]")
# Regex to find test file path from diff header
_TEST_FILE_RE = re.compile(r"^\+\+\+\s+b/(.+)$", re.MULTILINE)


def _get_diff(pull) -> str:
    """Download the raw unified diff for a PR."""
    diff_url = pull.get("diff_url") or pull["diff_url"]
    return requests.get(diff_url).text


def _split_patches(diff_text: str) -> tuple[str, str]:
    """
    Split a PR diff into implementation patch and test patch.
    Replicates swebench/collect/utils.py::extract_patches but works
    from a pre-fetched diff string.
    """
    patch_test = ""
    patch_fix = ""
    for hunk in PatchSet(diff_text):
        if any(word in hunk.path for word in ["test", "tests", "e2e", "testing"]):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test


def _parse_fail_to_pass(test_patch: str) -> list[str]:
    """
    Heuristically extract test function names added in test_patch.
    Returns pytest-style node IDs, mapping each function to the file it appears in.
    """
    if not test_patch:
        return []

    results = []
    current_file = None
    current_class = None
    for line in test_patch.splitlines():
        m = _TEST_FILE_RE.match(line)
        if m:
            current_file = m.group(1)
            current_class = None
            continue
        # Track class definitions (context or added lines)
        m = _CLASS_DEF_RE.match(line)
        if m:
            current_class = m.group(1)
            continue
        if current_file is None:
            continue
        # Top-level test function
        m = _TEST_FUNC_TOP_RE.match(line)
        if m:
            results.append(f"{current_file}::{m.group(1)}")
            continue
        # Class method test
        m = _TEST_FUNC_METHOD_RE.match(line)
        if m and current_class:
            results.append(f"{current_file}::{current_class}::{m.group(1)}")
    return results


def _make_instance_id(repo_full: str, pr_number: int) -> str:
    return (repo_full + "-" + str(pr_number)).replace("/", "__")


def build_instance(row: dict, github_token: Optional[str] = None) -> Optional[dict]:
    """
    Build a SWEbenchInstance-compatible dict for a single spreadsheet row.

    The result can be written to a .jsonl file and loaded by
    swebench/harness/utils.py::load_swebench_dataset().
    """
    pull = row.get("pr_data")
    if pull is None:
        logger.warning(f"Skipping {row[COL_REPO]}#{row[COL_PR_NUMBER]}: no PR data")
        return None

    repo_full = row[COL_REPO]
    pr_number = row[COL_PR_NUMBER]
    instance_id = _make_instance_id(repo_full, pr_number)

    # Fetch and split the diff
    try:
        diff_text = _get_diff(pull)
        patch, test_patch = _split_patches(diff_text)
    except Exception as e:
        logger.error(f"Failed to fetch diff for {instance_id}: {e}")
        return None

    if not patch:
        logger.warning(f"No implementation patch for {instance_id}, skipping")
        return None

    # Build problem statement from linked issues
    issue_data = row.get("issue_data", {})
    problem_statement = ""
    for inum, issue in issue_data.items():
        title = issue.title if hasattr(issue, "title") else issue.get("title", "")
        body = issue.body if hasattr(issue, "body") else issue.get("body", "")
        problem_statement += f"{title}\n{body}\n"
    problem_statement = problem_statement.strip()

    # FAIL_TO_PASS: heuristic parse from test patch
    fail_to_pass = _parse_fail_to_pass(test_patch)

    # version: attempt to get from the base commit tag, fall back to "0"
    base_commit = pull["base"]["sha"] if hasattr(pull, "__getitem__") else pull.base.sha
    version = _get_version(repo_full, base_commit, github_token)

    return {
        "repo": repo_full,
        "instance_id": instance_id,
        "pull_number": pr_number,
        "base_commit": base_commit,
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": problem_statement,
        "hints_text": "",
        "created_at": (
            pull["created_at"]
            if hasattr(pull, "__getitem__")
            else pull.created_at
        ),
        "version": version,
        "FAIL_TO_PASS": fail_to_pass,
        "PASS_TO_PASS": [],
        "environment_setup_commit": base_commit,
        # Extra fields for our pipeline
        "pr_title": pull["title"] if hasattr(pull, "__getitem__") else pull.title,
        "pr_body": (pull["body"] or "") if hasattr(pull, "__getitem__") else (pull.body or ""),
        "paper_reference": row.get(COL_PAPER_REFERENCE) or "",
        "issue_numbers": row.get("issue_numbers", []),
        "category": row.get("Category", ""),
        "algorithm_name": row.get("Algorithm Name", ""),
    }


def _get_version(repo_full: str, base_commit: str, github_token: Optional[str]) -> str:
    """
    Attempt to determine the repo version at base_commit.
    Falls back to "0" for repos not in SWE-bench's versioning map.
    """
    try:
        from swebench.versioning.get_versions import get_version
        stub = {"repo": repo_full, "base_commit": base_commit, "instance_id": ""}
        version = get_version(stub)
        return version or "0"
    except Exception as e:
        logger.debug(f"Version lookup failed for {repo_full}@{base_commit}: {e}")
        return "0"


def build_all_instances(
    enriched_rows: list[dict],
    github_token: Optional[str] = None,
) -> list[dict]:
    """Build instances for all rows, skipping those that fail."""
    instances = []
    for row in enriched_rows:
        inst = build_instance(row, github_token=github_token)
        if inst is not None:
            instances.append(inst)
    logger.info(f"Built {len(instances)}/{len(enriched_rows)} instances")
    return instances


def write_instances_jsonl(instances: list[dict], path: str) -> None:
    """Write instances to a .jsonl file loadable by load_swebench_dataset()."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for inst in instances:
            print(json.dumps(inst), file=f)
    logger.info(f"Wrote {len(instances)} instances to {path}")
