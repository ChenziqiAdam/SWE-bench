"""Stage 3: Build level 1/2/3 prompts for each instance."""
from __future__ import annotations

import logging
from typing import Optional

from swebench.eval_pipeline.constants import PATCH_INSTRUCTION

logger = logging.getLogger(__name__)

SYSTEM_MESSAGE = (
    "You are an expert software engineer. "
    "You will be given a task and must produce a git patch to solve it."
)

_LEVEL_DESCRIPTIONS = {
    1: "PR description (title + body)",
    2: "GitHub issue description",
    3: "Related paper reference + repo context",
}

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


def build_level1_prompt(instance: dict) -> Optional[str]:
    """
    Level 1: Full PR description. Easiest — the model sees the intended solution.
    """
    pr_title = (instance.get("pr_title") or "").strip()
    pr_body = (instance.get("pr_body") or "").strip()
    repo = instance["repo"]

    if not pr_title and not pr_body:
        logger.warning(f"[{instance['instance_id']}] No PR title/body for level 1")
        return None

    task_text = f"PR Title: {pr_title}\n\n{pr_body}" if pr_body else f"PR Title: {pr_title}"
    file_ctx = _format_file_contents(instance)

    return (
        f"{SYSTEM_MESSAGE}\n"
        f"Repository: {repo}\n\n"
        f"Here is the pull request that needs to be implemented:\n"
        f"<pr>\n{task_text}\n</pr>\n\n"
        f"{file_ctx}"
        f"{PATCH_INSTRUCTION}"
    )


def build_level2_prompt(instance: dict) -> Optional[str]:
    """
    Level 2: GitHub issue description only. No solution hints.
    """
    problem_statement = (instance.get("problem_statement") or "").strip()
    repo = instance["repo"]

    if not problem_statement:
        logger.warning(f"[{instance['instance_id']}] No problem statement for level 2")
        return None

    file_ctx = _format_file_contents(instance)

    return (
        f"{SYSTEM_MESSAGE}\n"
        f"Repository: {repo}\n\n"
        f"Here is the issue that needs to be resolved:\n"
        f"<issue>\n{problem_statement}\n</issue>\n\n"
        f"{file_ctx}"
        f"{PATCH_INSTRUCTION}"
    )


def build_level3_prompt(instance: dict) -> Optional[str]:
    """
    Level 3: Related paper reference + repo context. Hardest.
    Only applicable to instances with a paper_reference.
    """
    paper_ref = (instance.get("paper_reference") or "").strip()
    repo = instance["repo"]
    algorithm_name = (instance.get("algorithm_name") or "").strip()

    if not paper_ref:
        return None

    algo_hint = f" specifically the '{algorithm_name}' algorithm" if algorithm_name else ""
    file_ctx = _format_file_contents(instance)

    return (
        f"{SYSTEM_MESSAGE}\n"
        f"Repository: {repo}\n\n"
        f"Implement{algo_hint} as described in the following paper reference:\n"
        f"<paper>\n{paper_ref}\n</paper>\n\n"
        f"{file_ctx}"
        f"Study the existing codebase, understand how similar algorithms are implemented, "
        f"and produce a patch that adds this algorithm in a consistent style.\n\n"
        f"{PATCH_INSTRUCTION}"
    )


def build_prompts_for_instance(instance: dict) -> dict[int, Optional[str]]:
    """
    Build all applicable prompts for one instance.
    Returns a dict: {level: prompt_str or None}
    """
    return {
        1: build_level1_prompt(instance),
        2: build_level2_prompt(instance),
        3: build_level3_prompt(instance),
    }


def build_all_prompts(instances: list[dict]) -> dict[str, dict[int, Optional[str]]]:
    """
    Build prompts for all instances.
    Returns: {instance_id: {1: prompt, 2: prompt, 3: prompt_or_None}}
    """
    result = {}
    for inst in instances:
        result[inst["instance_id"]] = build_prompts_for_instance(inst)

    # Log coverage
    for level in [1, 2, 3]:
        count = sum(1 for p in result.values() if p[level] is not None)
        logger.info(f"Level {level} ({_LEVEL_DESCRIPTIONS[level]}): {count}/{len(instances)} instances have prompts")

    return result
