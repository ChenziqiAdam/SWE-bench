"""Stage 1: Parse PRs.xlsx and fetch GitHub PR/issue content."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import openpyxl

from swebench.collect.utils import Repo, PR_KEYWORDS
from swebench.eval_pipeline.constants import (
    COL_REPO, COL_PR_NUMBER, COL_TITLE, COL_URL,
    COL_CATEGORY, COL_ALGORITHM_NAME, COL_PAPER_REFERENCE,
    COL_HAS_TEST, COL_TEST_LINKS, COL_HAS_ISSUE,
)

logger = logging.getLogger(__name__)


def instance_ids_to_pr_filter(instance_ids: set[str]) -> dict[str, set[int]]:
    """
    Convert a set of instance_ids like {"scikit-learn__scikit-learn-31856"}
    into {repo: {pr_number}} so the ingest stage can skip unneeded rows.
    Instance ID format: owner__repo-pr_number  (double underscore, trailing dash+number)
    """
    result: dict[str, set[int]] = {}
    for iid in instance_ids:
        # Split on last "-" to get pr_number, rest is repo slug with __ separating owner/name
        repo_slug, pr_str = iid.rsplit("-", 1)
        repo_full = repo_slug.replace("__", "/", 1)
        result.setdefault(repo_full, set()).add(int(pr_str))
    return result


def load_spreadsheet(path: str) -> list[dict]:
    """Read PRs.xlsx and return a list of row dicts."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    rows = []
    for raw_row in ws.iter_rows(min_row=2, values_only=True):
        row = dict(zip(headers, raw_row))
        # Skip rows with no repo or PR number
        if not row.get(COL_REPO) or not row.get(COL_PR_NUMBER):
            continue
        row[COL_PR_NUMBER] = int(row[COL_PR_NUMBER])
        rows.append(row)
    return rows


def fetch_pr_data(repo: Repo, pr_number: int) -> Optional[dict]:
    """Fetch PR metadata from GitHub."""
    pull = repo.call_api(
        repo.api.pulls.get,
        owner=repo.owner,
        repo=repo.name,
        pull_number=pr_number,
    )
    if pull is None:
        logger.warning(f"PR {repo.owner}/{repo.name}#{pr_number} not found")
        return None
    return pull


def fetch_issue_data(repo: Repo, issue_number: int) -> Optional[dict]:
    """Fetch issue metadata from GitHub."""
    issue = repo.call_api(
        repo.api.issues.get,
        owner=repo.owner,
        repo=repo.name,
        issue_number=int(issue_number),
    )
    return issue


def find_linked_issue_numbers(pull) -> list[str]:
    """
    Extract issue numbers referenced by a PR using keyword matching.
    Replicates logic from swebench/collect/utils.py::Repo.extract_resolved_issues
    but works without a Repo instance (no commit fetching).
    """
    issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
    comments_pat = re.compile(r"(?s)<!--.*?-->")
    text = (pull.title or "") + "\n" + (pull.body or "")
    text = comments_pat.sub("", text)
    references = issues_pat.findall(text)
    resolved = set()
    for word, issue_num in references:
        if word.lower() in PR_KEYWORDS:
            resolved.add(issue_num)
    return list(resolved)


def fetch_all(
    spreadsheet_path: str,
    github_token: Optional[str] = None,
    limit: Optional[int] = None,
    pr_numbers: Optional[dict[str, set[int]]] = None,
    repos: Optional[set[str]] = None,
) -> list[dict]:
    """
    Parse the spreadsheet and fetch GitHub data for each PR.

    Args:
        pr_numbers: optional {repo_full_name: {pr_number, ...}} filter.
                    When given, only those specific PRs are fetched.
                    Build this from instance_ids with _instance_ids_to_pr_filter().

    Returns a list of enriched row dicts with added keys:
      - pr_data: raw GitHub PR object (or None)
      - issue_numbers: list of linked issue number strings
      - issue_data: dict mapping issue_number -> GitHub issue object
    """
    if not github_token:
        raise ValueError(
            "A GitHub token is required to fetch PR/issue data.\n"
            "Pass --github_token YOUR_TOKEN or set the GITHUB_TOKEN environment variable.\n"
            "Create one at: https://github.com/settings/tokens (no scopes needed for public repos)."
        )
    rows = load_spreadsheet(spreadsheet_path)

    # Filter rows before hitting the GitHub API
    if repos:
        rows = [r for r in rows if r[COL_REPO] in repos]
        logger.info(f"Filtered spreadsheet to {len(rows)} row(s) matching --repos")
    if pr_numbers:
        rows = [
            r for r in rows
            if r[COL_REPO] in pr_numbers and r[COL_PR_NUMBER] in pr_numbers[r[COL_REPO]]
        ]
        logger.info(f"Filtered spreadsheet to {len(rows)} row(s) matching --instance_ids")

    if limit:
        rows = rows[:limit]

    # Cache Repo objects per owner/name
    repo_cache: dict[str, Repo] = {}

    enriched = []
    for i, row in enumerate(rows):
        repo_full = row[COL_REPO]  # e.g. "numpy/numpy"
        pr_number = row[COL_PR_NUMBER]
        owner, name = repo_full.split("/", 1)

        logger.info(f"[{i+1}/{len(rows)}] Fetching {repo_full}#{pr_number}")

        if repo_full not in repo_cache:
            try:
                repo_cache[repo_full] = Repo(owner, name, token=github_token)
            except Exception as e:
                logger.error(f"Failed to init Repo for {repo_full}: {e}")
                row["pr_data"] = None
                row["issue_numbers"] = []
                row["issue_data"] = {}
                enriched.append(row)
                continue

        repo = repo_cache[repo_full]
        pull = fetch_pr_data(repo, pr_number)
        row["pr_data"] = pull

        if pull is None:
            row["issue_numbers"] = []
            row["issue_data"] = {}
            enriched.append(row)
            continue

        has_issue_flag = str(row.get(COL_HAS_ISSUE) or "").strip().lower()
        if has_issue_flag == "no":
            row["issue_numbers"] = []
            row["issue_data"] = {}
            logger.debug(f"  Skipping issue scan for {repo_full}#{pr_number} (Has Issue=No)")
            enriched.append(row)
            continue

        issue_numbers = find_linked_issue_numbers(pull)
        row["issue_numbers"] = issue_numbers

        issue_data = {}
        for inum in issue_numbers:
            issue = fetch_issue_data(repo, inum)
            if issue is not None:
                issue_data[inum] = issue
        row["issue_data"] = issue_data

        if not issue_numbers:
            logger.warning(f"  No linked issues found for {repo_full}#{pr_number}")

        enriched.append(row)

    return enriched
