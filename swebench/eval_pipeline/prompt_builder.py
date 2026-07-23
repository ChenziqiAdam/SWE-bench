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

COVERAGE_GENERATION_SYSTEM_MESSAGE = (
    "You are an expert scientific-software test engineer. "
    "You must improve repository-wide test coverage without changing production code."
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
        "Use only APIs, names, signatures, and expected behavior supported by the issue; "
        "do not invent additional proposed behavior.\n"
        "For compiled tests, update test-only build registration or link dependencies when required.\n"
        "Place new tests in a separate function or hunk where possible so the fix patch can apply cleanly.\n"
        "Compile or run the focused generated test on the original checkout before returning it.\n"
        "The generated tests should fail on the original pre-fix codebase and pass "
        "after the golden fix patch is applied.\n"
        "Even if a related test already exists, you must add a new focused assertion "
        "or test case and return a non-empty patch that reproduces this issue.\n"
        "Return only a valid unified git diff."
    )


def _coverage_generation_instruction(instance: dict) -> str:
    from swebench.eval_pipeline.coverage_generation_eval import infer_coverage_targets

    targets = infer_coverage_targets(instance)
    target_text = "\n".join(f"    {path}" for path in targets)
    baseline_report = (instance.get("baseline_coverage_report") or "").strip()
    commands = []
    if instance.get("coverage_setup_command"):
        commands.append(f"Environment setup command: {instance['coverage_setup_command']}")
    if instance.get("coverage_test_command"):
        commands.append(f"Complete test command: {instance['coverage_test_command']}")
    command_text = ("\n" + "\n".join(commands) + "\n") if commands else ""
    return (
        "Improve whole-repository test coverage. Choose meaningful, poorly tested "
        "production modules using the independent baseline report below.\n"
        + (f"Preferred mutation targets (coverage remains repository-wide):\n{target_text}\n\n"
           if target_text else "")
        + f"<baseline_coverage_report>\n{baseline_report}\n"
        "</baseline_coverage_report>\n\n"
        f"{command_text}"
        "Requirements:\n"
        "1. Only add or modify test files and small test data files.\n"
        "2. Do not modify production code, configuration files, or existing test behavior.\n"
        "3. Add meaningful assertions, not merely execution-based tests.\n"
        "4. Keep the complete existing test suite passing.\n"
        "5. Focus on edge cases, numerical behavior, and scientific invariants.\n"
        "6. Run tests and coverage tools as useful, then leave the test edits in the working tree.\n"
        "Return only a valid unified git diff."
    )


def build_agent_prompt(instance: dict, eval_mode: str = "fix") -> Optional[str]:
    """
    The agent task: the GitHub issue / problem statement, with no solution hints.
    Returns None if the instance has no problem statement.
    """
    problem_statement = _problem_text(instance)
    repo = instance["repo"]

    if not problem_statement and eval_mode != "coverage_generation":
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

    if eval_mode == "coverage_generation":
        issue_context = (
            f"Background issue context:\n<issue>\n{problem_statement}\n</issue>"
            if problem_statement else ""
        )
        return (
            f"{COVERAGE_GENERATION_SYSTEM_MESSAGE}\n"
            f"Repository: {repo}\n\n"
            f"{_coverage_generation_instruction(instance)}\n\n"
            f"{media_ctx}{file_ctx}{issue_context}"
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
