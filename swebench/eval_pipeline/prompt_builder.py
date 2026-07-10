"""Stage 3: Build the agent prompt (issue/problem statement) for each instance."""
from __future__ import annotations

import logging
from typing import Optional

from swebench.eval_pipeline.constants import PATCH_INSTRUCTION
from swebench.eval_pipeline.media_assets import format_issue_media_for_prompt

logger = logging.getLogger(__name__)

SYSTEM_MESSAGE = (
    "You are an expert software engineer. "
    "You will be given a task and must produce a git patch to solve it."
)

TEST_GENERATION_SYSTEM_MESSAGE = (
    "You are an expert software engineer. "
    "You will be given a bug report and must produce a git patch that adds or "
    "modifies tests only."
)

# Max chars per file to include in the prompt (~200k chars fits in DeepSeek 1M context)
_MAX_FILE_CHARS = 200_000


def _format_file_contents(instance: dict) -> str:
    """
    Format the relevant file contents from instance['file_contents'] for inclusion
    in the prompt. Returns an empty string if no contents available.
    """
    file_contents: dict = instance.get("file_contents") or {}
    if not file_contents:
        return ""

    parts = [
        "Here are the current contents of the files you will need to modify. "
        "Each line is prefixed with its 1-based line number followed by a tab — "
        "use these EXACT line numbers when constructing your @@ hunk headers. "
        "Do NOT include the line-number prefix in the diff itself.\n"
    ]
    for path, content in file_contents.items():
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + "\n... [truncated]"
        numbered = "\n".join(
            f"{i}\t{line}" for i, line in enumerate(content.split("\n"), start=1)
        )
        parts.append(f"<file path=\"{path}\">\n{numbered}\n</file>")
    return "\n".join(parts) + "\n\n"


def _problem_text(instance: dict) -> str:
    problem_statement = (instance.get("problem_statement") or "").strip()
    if problem_statement:
        return problem_statement
    pr_title = (instance.get("pr_title") or "").strip()
    pr_body = (instance.get("pr_body") or "").strip()
    return f"{pr_title}\n\n{pr_body}".strip()


def _test_generation_instruction() -> str:
    return (
        "Write a minimal regression test patch for the issue above.\n"
        "Do not fix the bug or modify implementation/source files.\n"
        "Only add or modify tests and any small test data files required by those tests.\n"
        "The generated tests should fail on the original pre-fix codebase and pass "
        "after the golden fix patch is applied.\n"
        "Return only a valid unified git diff."
    )


def build_agent_prompt(instance: dict, eval_mode: str = "fix") -> Optional[str]:
    """
    The agent task: the GitHub issue / problem statement, with no solution hints.
    Returns None if the instance has no problem statement.
    """
    problem_statement = _problem_text(instance)
    repo = instance["repo"]

    if not problem_statement:
        logger.warning(f"[{instance['instance_id']}] No problem statement — cannot build agent prompt")
        return None

    file_ctx = _format_file_contents(instance)
    media_ctx = format_issue_media_for_prompt(instance)

    if eval_mode == "test_generation":
        return (
            f"{TEST_GENERATION_SYSTEM_MESSAGE}\n"
            f"Repository: {repo}\n\n"
            f"Here is the issue that needs a regression test:\n"
            f"<issue>\n{problem_statement}\n</issue>\n\n"
            f"{media_ctx}"
            f"{file_ctx}"
            f"{_test_generation_instruction()}"
        )

    return (
        f"{SYSTEM_MESSAGE}\n"
        f"Repository: {repo}\n\n"
        f"Here is the issue that needs to be resolved:\n"
        f"<issue>\n{problem_statement}\n</issue>\n\n"
        f"{media_ctx}"
        f"{file_ctx}"
        f"{PATCH_INSTRUCTION}"
    )


def build_level1_prompt(instance: dict) -> str:
    """Compatibility prompt for the legacy frontend level-1 view."""
    title = (instance.get("pr_title") or "").strip()
    body = (instance.get("pr_body") or "").strip()
    repo = instance.get("repo", "")
    return (
        f"{SYSTEM_MESSAGE}\n"
        f"Repository: {repo}\n\n"
        f"Pull request title:\n{title}\n\n"
        f"Pull request body:\n{body}\n\n"
        f"{PATCH_INSTRUCTION}"
    )


def build_level2_prompt(instance: dict) -> Optional[str]:
    """Compatibility prompt for the legacy frontend level-2 view."""
    return build_agent_prompt(instance, eval_mode="fix")


def build_level3_prompt(instance: dict) -> Optional[str]:
    """Compatibility prompt for the legacy frontend level-3 view."""
    paper_reference = (instance.get("paper_reference") or "").strip()
    if not paper_reference:
        return None
    base_prompt = build_agent_prompt(instance, eval_mode="fix")
    if base_prompt is None:
        return None
    return (
        f"{base_prompt}\n\n"
        f"Relevant scientific reference:\n{paper_reference}"
    )


def build_all_prompts(
    instances: list[dict],
    eval_mode: str = "fix",
) -> dict[str, Optional[str]]:
    """
    Build the agent prompt for all instances.
    Returns: {instance_id: prompt_str or None}
    """
    result = {
        inst["instance_id"]: build_agent_prompt(inst, eval_mode=eval_mode)
        for inst in instances
    }
    count = sum(1 for p in result.values() if p is not None)
    logger.info(f"Agent prompts: {count}/{len(instances)} instances have a problem statement")
    return result
