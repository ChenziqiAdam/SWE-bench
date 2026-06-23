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
from swebench.eval_pipeline.constants import COL_REPO, COL_PR_NUMBER, COL_PAPER_REFERENCE, COL_HAS_ISSUE
from swebench.harness.constants.c import MAP_REPO_VERSION_TO_SPECS_C

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


def _fetch_file_contents(
    repo_full: str,
    base_commit: str,
    patch: str,
    github_token: Optional[str] = None,
) -> dict[str, str]:
    """
    Fetch the content of each non-test file touched by the patch at base_commit.
    Returns {path: content}. Silently skips files that fail to fetch.
    """
    file_paths = re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)
    # Exclude test files and non-Python files (docs, build files)
    impl_paths = [
        p for p in file_paths
        if not any(x in p for x in ["test", "tests", "e2e"])
        and p.endswith((".py", ".pyx", ".pxd", ".h", ".cpp", ".cxx", ".cc"))
    ]

    headers = {"Authorization": f"token {github_token}"} if github_token else {}
    contents = {}
    for path in impl_paths:
        url = f"https://raw.githubusercontent.com/{repo_full}/{base_commit}/{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                contents[path] = resp.text
            else:
                logger.debug(f"Could not fetch {path} at {base_commit}: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"Error fetching {path}: {e}")
    return contents


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

    # base_commit (used below for file fetch + version lookup)
    base_commit = pull["base"]["sha"] if hasattr(pull, "__getitem__") else pull.base.sha

    # Fetch file contents at base_commit for prompt context
    file_contents = _fetch_file_contents(repo_full, base_commit, patch, github_token)

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
    version = _get_version(repo_full, base_commit, github_token, pr_number=pr_number)

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
        "has_issue": str(row.get(COL_HAS_ISSUE) or "").strip().lower() == "yes",
        "category": row.get("Category", ""),
        "algorithm_name": row.get("Algorithm Name", ""),
        "file_contents": file_contents,
    }


def _get_version(repo_full: str, base_commit: str, github_token: Optional[str], pr_number: Optional[int] = None) -> str:
    """
    Attempt to determine the repo version at base_commit.
    Falls back to "0" for repos not in SWE-bench's versioning map.
    """
    if repo_full in MAP_REPO_VERSION_TO_SPECS_C:
        if pr_number is None:
            raise ValueError(f"pr_number required for C/C++ repo {repo_full!r}")
        version_key = str(pr_number)
        if version_key not in MAP_REPO_VERSION_TO_SPECS_C[repo_full]:
            raise KeyError(
                f"No spec for {repo_full!r} PR #{pr_number}. "
                f"Add key {version_key!r} to MAP_REPO_VERSION_TO_SPECS_C in "
                f"swebench/harness/constants/c.py before running."
            )
        return version_key

    try:
        from swebench.versioning.get_versions import get_version
        stub = {"repo": repo_full, "base_commit": base_commit, "instance_id": ""}
        version = get_version(stub)
        if version:
            return version
    except Exception as e:
        logger.debug(f"Version lookup failed for {repo_full}@{base_commit}: {e}")

    # Fallback: repos with dynamic versioning (pandas, old numpy/scipy) need
    # alternative lookup strategies.
    return _get_version_fallback(repo_full, base_commit, github_token) or "0"


def _get_version_fallback(repo_full: str, base_commit: str, github_token: Optional[str]) -> Optional[str]:
    """Fallback version detection for repos that use dynamic versioning."""
    import re
    import requests

    headers: dict = {}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    raw_base = f"https://raw.githubusercontent.com/{repo_full}/{base_commit}"

    def fetch(path: str) -> Optional[str]:
        try:
            r = requests.get(f"{raw_base}/{path}", headers=headers, timeout=10)
            return r.text if r.status_code == 200 else None
        except Exception:
            return None

    if repo_full == "pandas-dev/pandas":
        # pandas whatsnew/index.rst lists versions newest-first
        text = fetch("doc/source/whatsnew/index.rst")
        if text:
            m = re.search(r"v(\d+\.\d+)", text)
            if m:
                return m.group(1)
        # Older pandas (pre-meson): setup.py has version= string
        text = fetch("setup.py")
        if text:
            m = re.search(r'version\s*=\s*["\'](\d+\.\d+)', text)
            if m:
                return m.group(1)

    elif repo_full == "numpy/numpy":
        # Old numpy: check release notes directory for highest version present
        for v in ["1.26", "1.25", "1.24", "1.23", "1.22", "1.21", "1.20", "1.19", "1.18", "1.17"]:
            text = fetch(f"doc/release/{v}.0-notes.rst")
            if text:
                return v
        # Also try doc/source/release.rst which lists versions newest-first
        text = fetch("doc/source/release.rst")
        if text:
            m = re.search(r"(\d+\.\d+)\.\d+ <release/", text)
            if m:
                return m.group(1)

    elif repo_full == "scipy/scipy":
        # meson.build has: version: 'X.Y.Z'
        text = fetch("meson.build")
        if text:
            m = re.search(r"version\s*:\s*['\"](\d+\.\d+)", text)
            if m:
                return m.group(1)
        # doc/source/release.rst lists versions newest-first
        text = fetch("doc/source/release.rst")
        if text:
            m = re.search(r"release\.(\d+\.\d+)", text)
            if m:
                return m.group(1)

    return None


def build_all_instances(
    enriched_rows: list[dict],
    github_token: Optional[str] = None,
    checkpoint_path: Optional[str] = None,
) -> list[dict]:
    """Build instances for all rows, skipping those that fail.

    If checkpoint_path is given, already-built instances are loaded from it on
    startup and each newly built instance is appended immediately, so a crash
    mid-run loses at most the current row.
    """
    # Load existing checkpoint
    existing: dict[str, dict] = {}
    if checkpoint_path and Path(checkpoint_path).exists():
        with open(checkpoint_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        inst = json.loads(line)
                        existing[inst["instance_id"]] = inst
                    except Exception:
                        pass
        if existing:
            logger.info(
                f"Instance checkpoint: loaded {len(existing)} already-built instances "
                f"from {checkpoint_path}"
            )

    instances = list(existing.values())
    skipped = 0
    built = 0

    for row in enriched_rows:
        repo_full = row.get(COL_REPO, "")
        pr_number = row.get(COL_PR_NUMBER, 0)
        instance_id = _make_instance_id(repo_full, pr_number)

        if instance_id in existing:
            skipped += 1
            continue

        inst = build_instance(row, github_token=github_token)
        if inst is not None:
            instances.append(inst)
            built += 1
            if checkpoint_path:
                Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
                with open(checkpoint_path, "a") as f:
                    f.write(json.dumps(inst) + "\n")

    if skipped:
        logger.info(f"Instance checkpoint: skipped {skipped} already-built rows")
    logger.info(f"Built {built} new + {skipped} cached = {len(instances)} total instances")
    return instances


def write_instances_jsonl(instances: list[dict], path: str) -> None:
    """Write instances to a .jsonl file loadable by load_swebench_dataset()."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for inst in instances:
            print(json.dumps(inst), file=f)
    logger.info(f"Wrote {len(instances)} instances to {path}")
