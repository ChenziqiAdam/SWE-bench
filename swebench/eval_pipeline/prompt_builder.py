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


def build_agent_prompt(instance: dict) -> Optional[str]:
    """
    The agent task: the GitHub issue / problem statement, with no solution hints.
    Returns None if the instance has no problem statement.
    """
    problem_statement = (instance.get("problem_statement") or "").strip()
    repo = instance["repo"]

    if not problem_statement:
        logger.warning(f"[{instance['instance_id']}] No problem statement — cannot build agent prompt")
        return None

    file_ctx = _format_file_contents(instance)
    media_ctx = format_issue_media_for_prompt(instance)

    return (
        f"{SYSTEM_MESSAGE}\n"
        f"Repository: {repo}\n\n"
        f"Here is the issue that needs to be resolved:\n"
        f"<issue>\n{problem_statement}\n</issue>\n\n"
        f"{media_ctx}"
        f"{file_ctx}"
        f"{PATCH_INSTRUCTION}"
    )


def build_all_prompts(instances: list[dict]) -> dict[str, Optional[str]]:
    """
    Build the agent prompt for all instances.
    Returns: {instance_id: prompt_str or None}
    """
    result = {inst["instance_id"]: build_agent_prompt(inst) for inst in instances}
    count = sum(1 for p in result.values() if p is not None)
    logger.info(f"Agent prompts: {count}/{len(instances)} instances have a problem statement")
    return result
