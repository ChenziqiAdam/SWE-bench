"""LLM client + patch-extraction helpers shared by the agent inference backends.

Supports three backends:
  - Anthropic native API  (claude-* models, or --endpoint pointing to Anthropic)
  - OpenAI native API     (gpt-* / o1-* models, no custom endpoint)
  - OpenAI-compatible API (any model via --endpoint + --api_key, e.g. Ollama,
                           Together AI, Mistral, vLLM, LM Studio, AWS Bedrock
                           converse proxy, etc.)

The OpenAI-compatible path is the generic fallback: if you supply --endpoint,
it is used regardless of model name, so you can point it at any provider.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_random_exponential

from swebench.inference.make_datasets.utils import extract_diff
from swebench.eval_pipeline.constants import (
    MODEL_COST_PER_INPUT,
    MODEL_COST_PER_OUTPUT,
)

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _split_prompt(prompt: str) -> tuple[str, str]:
    """Return (system_message, user_message) from a prompt string."""
    if "\n" in prompt:
        system_msg, user_msg = prompt.split("\n", 1)
    else:
        system_msg, user_msg = "", prompt
    return system_msg, user_msg


def _calc_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    cost_in = MODEL_COST_PER_INPUT.get(model_name, 0.0) * input_tokens
    cost_out = MODEL_COST_PER_OUTPUT.get(model_name, 0.0) * output_tokens
    return cost_in + cost_out


def _extract_diff(response: str) -> str:
    """Extract a unified diff from a model response.

    Improves on the shared extract_diff() for two failure modes seen with
    chatty models:
      1. Model emits a throwaway <patch>...</patch> block, then a better,
         refined block later — we prefer the LAST diff block, not the first.
      2. The final/best block is truncated (hit max_tokens) so its closing
         </patch> / ``` is missing — we salvage the trailing unclosed block.
    """
    import re
    if not response:
        return response or ""

    candidates: list[str] = []

    # Closed <patch>/<diff> tags and ```diff/```patch fences (in document order)
    for m in re.finditer(r"<(patch|diff)>(.*?)</\1>", response, re.DOTALL):
        candidates.append(m.group(2))
    for m in re.finditer(r"```(?:diff|patch)?\n(.*?)```", response, re.DOTALL):
        if "diff --git" in m.group(1) or "@@" in m.group(1):
            candidates.append(m.group(1))

    # Salvage a trailing UNCLOSED <patch>/<diff> block (truncated output)
    open_tag = re.search(r"<(patch|diff)>(?!.*</\1>)(.*)$", response, re.DOTALL)
    if open_tag and "diff --git" in open_tag.group(2):
        candidates.append(open_tag.group(2))

    # Keep only candidates that look like a diff
    diffs = [c for c in candidates if "diff --git" in c or c.lstrip().startswith(("--- ", "@@"))]

    # Prefer the LAST candidate whose body is structurally valid (no prose contamination).
    # A valid diff body is composed of: file headers (diff/---/+++/index/new file/deleted file),
    # hunk headers (@@), body lines (+/-/space/backslash), or blank lines. Anything else is prose.
    def _is_clean(d: str) -> bool:
        for ln in d.split("\n"):
            if not ln:
                continue
            if ln.startswith(("diff ", "--- ", "+++ ", "@@ ", "index ", "new file", "deleted file",
                              "+", "-", " ", "\\", "rename from", "rename to", "similarity index",
                              "Binary files")):
                continue
            return False
        return True

    for c in reversed(diffs):
        if _is_clean(c):
            return c.strip("\n") + "\n"

    # No clean candidate — fall back to the last extracted block (best effort)
    if diffs:
        return diffs[-1].strip("\n") + "\n"

    # Fall back to the shared extractor (handles bare diffs, other formats)
    return extract_diff(response)


def _clean_patch(patch: str) -> str:
    """Clean common model-output artifacts from a patch string."""
    if not patch:
        return patch

    import re
    # Strip markdown code fences (```diff ... ``` or ``` ... ```)
    patch = re.sub(r"^```[a-zA-Z]*\n?", "", patch.strip())
    patch = re.sub(r"\n?```$", "", patch)

    # Strip unclosed/closed <patch> tags
    patch = re.sub(r"^\s*<patch>\s*", "", patch)
    patch = re.sub(r"\s*</patch>\s*$", "", patch)

    # Strip trailing incomplete context lines (e.g. patch ends with '\n ' — a space
    # with no following newline, which causes GNU patch "ends in middle of line" error)
    import re as _re
    patch = _re.sub(r"\n[ \t]+$", "\n", patch)

    # Ensure patch ends with a newline
    if patch and not patch.endswith("\n"):
        patch += "\n"

    return patch


_GENERATED_ARTIFACT_DIR_PATTERNS = ("build", "build-", "cmake-build-", "_build")
_GENERATED_BYTECODE_SUFFIXES = (".pyc", ".pyo")


def _strip_generated_artifact_diff_blocks(patch: str) -> str:
    """Remove generated build and bytecode files from a captured git diff.

    Agent test runs can create untracked ``__pycache__`` files or build trees.
    ``git add -N .`` makes those files visible to the subsequent diff capture,
    but they are execution artifacts rather than authored model changes.
    """
    if not patch:
        return patch

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    kept: list[str] = []
    for block in blocks:
        path = block[0].split(" b/", 1)[-1].strip()
        parts = path.lower().split("/")
        filename = parts[-1]
        is_bytecode = (
            "__pycache__" in parts
            or filename.endswith(_GENERATED_BYTECODE_SUFFIXES)
        )
        is_build_output = any(
            part == pattern or part.startswith(pattern)
            for part in parts[:-1]
            for pattern in _GENERATED_ARTIFACT_DIR_PATTERNS
        )
        if not is_bytecode and not is_build_output:
            kept.extend(block)
    return "".join(kept)


def _repair_patch(patch: str) -> str:
    """
    Fix common model diff errors:
    1. Context lines missing the required leading space.
    2. Wrong line counts in @@ hunk headers (model miscounts added/removed lines).
    3. Missing trailing newline (causes "patch unexpectedly ends in middle of line").

    NOTE: Do NOT insert synthetic "index 0000000..0000000 100644" lines. git apply
    and GNU patch both work fine without an index line; but zeroed index hashes make
    git treat the file as a new-file creation → "already exists! Assuming -R" → applies
    in reverse → fails. Leave the index line absent if the model didn't produce one.
    """
    import re
    if not patch:
        return patch

    lines = patch.split("\n")
    # split("\n") yields a trailing "" when patch ends with "\n". That sentinel is
    # NOT part of any hunk body; if left in, the bare-empty → " " rule below turns
    # it into a phantom context line and inflates the final hunk's counts by 1.
    if lines and lines[-1] == "":
        lines.pop()
    repaired = []
    in_hunk = False

    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
            repaired.append(line)
        elif line.startswith(("diff ", "--- ", "+++ ", "index ", "new file", "deleted file")):
            in_hunk = False
            repaired.append(line)
        elif in_hunk and line == "":
            # Bare empty line inside a hunk must be a context line with a leading space
            repaired.append(" ")
        elif in_hunk and line and not line.startswith(("+", "-", " ", "\\")):
            # Missing leading space on a context line — add it
            repaired.append(" " + line)
        else:
            repaired.append(line)

    # Second pass: recompute hunk header line counts from actual content
    _hunk_re = re.compile(r"^(@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@)(.*)")
    fixed = []
    i = 0
    while i < len(repaired):
        line = repaired[i]
        m = _hunk_re.match(line)
        if m:
            old_start = int(m.group(2))
            new_start = int(m.group(3))
            suffix = m.group(4)
            # Collect hunk body
            body = []
            i += 1
            while i < len(repaired) and not (repaired[i].startswith("@@") or repaired[i].startswith("diff ")):
                body.append(repaired[i])
                i += 1
            # Count actual lines
            old_count = sum(1 for l in body if l.startswith(" ") or l.startswith("-"))
            new_count = sum(1 for l in body if l.startswith(" ") or l.startswith("+"))
            n_changes = sum(1 for l in body if l.startswith("+") or l.startswith("-"))
            # GNU patch rejects no-op hunks (only context, no +/-) as "malformed".
            # Skip them — they encode no change anyway.
            if n_changes == 0:
                continue
            fixed.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}")
            fixed.extend(body)
        else:
            fixed.append(line)
            i += 1

    result = "\n".join(fixed)
    # Ensure the patch ends with exactly one newline (split/join can drop the trailing \n,
    # and the empty-string-to-space rule can turn it into '\n ' which triggers
    # "patch unexpectedly ends in middle of line" in GNU patch).
    result = result.rstrip(" \t")
    if not result.endswith("\n"):
        result += "\n"
    return result


# ── per-backend call functions ────────────────────────────────────────────────

@retry(wait=wait_random_exponential(min=30, max=300), stop=stop_after_attempt(5))
def _call_anthropic_native(
    prompt: str, model_name: str, client, max_tokens: int = 4096
) -> tuple[str, float]:
    """Anthropic messages API (claude-* on api.anthropic.com)."""
    system_msg, user_msg = _split_prompt(prompt)
    response = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.2,
        top_p=0.95,
    )
    text = response.content[0].text
    cost = _calc_cost(model_name, response.usage.input_tokens, response.usage.output_tokens)
    return text, cost


@retry(wait=wait_random_exponential(min=10, max=60), stop=stop_after_attempt(3))
def _call_openai_compat(
    prompt: str, model_name: str, client, max_tokens: int = 4096
) -> tuple[str, float]:
    """OpenAI-compatible chat completions API.

    Works with: OpenAI, Ollama, Together AI, Mistral, vLLM, LM Studio,
    Groq, Fireworks, Anyscale, DeepSeek, and any other provider that
    speaks the /v1/chat/completions protocol.
    """
    system_msg, user_msg = _split_prompt(prompt)

    # Build kwargs conservatively — some providers (vLLM, Qwen, etc.) reject
    # top_p when temperature is also set, or don't support certain fields.
    kwargs: dict = dict(
        model=model_name,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as e:
        logger.error(f"API call failed: {type(e).__name__}: {e}")
        # Retry without temperature if the server rejected it
        err_str = str(e).lower()
        if any(kw in err_str for kw in ("temperature", "top_p", "400", "bad request", "invalid")):
            logger.warning("Retrying without temperature parameter")
            kwargs.pop("temperature", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise

    text = response.choices[0].message.content or ""
    if not text.strip():
        finish_reason = getattr(response.choices[0], "finish_reason", "unknown")
        raise ValueError(f"Model returned empty response (finish_reason={finish_reason})")
    input_tokens = getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0
    output_tokens = getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0
    cost = _calc_cost(model_name, input_tokens, output_tokens)
    return text, cost


def make_clients(
    model_name: str,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """
    Build and return (anthropic_client, openai_compat_client).

    Backend selection logic:
      1. If --endpoint is given → OpenAI-compatible client pointed at that URL.
         Works for Ollama, Together AI, Mistral, vLLM, LM Studio, Groq, etc.
      2. Else if model starts with "claude" → Anthropic native client.
      3. Else → OpenAI native client (api.openai.com).

    API key resolution order (same for all backends):
      --api_key CLI flag → ANTHROPIC_API_KEY / OPENAI_API_KEY env vars → "none"
      (some local providers like Ollama don't need a real key).
    """
    import openai as openai_mod

    anthropic_client = None
    openai_compat_client = None

    if endpoint:
        # Generic OpenAI-compatible path — works for any provider
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or "none"
        # timeout=600s prevents a hung remote socket from blocking the whole pipeline
        openai_compat_client = openai_mod.OpenAI(base_url=endpoint, api_key=resolved_key, timeout=600.0)
        logger.info(f"Using OpenAI-compatible endpoint: {endpoint} (model={model_name})")

    elif model_name.lower().startswith("claude"):
        from anthropic import Anthropic
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY or pass --api_key.")
        anthropic_client = Anthropic(api_key=resolved_key)
        logger.info(f"Using Anthropic native API (model={model_name})")

    else:
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY or pass --api_key.")
        openai_compat_client = openai_mod.OpenAI(api_key=resolved_key, timeout=600.0)
        logger.info(f"Using OpenAI native API (model={model_name})")

    return anthropic_client, openai_compat_client
