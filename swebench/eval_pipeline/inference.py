"""Stage 4: Call LLM APIs and output JSONL patches per level.

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

import json
import logging
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_random_exponential
from tqdm.auto import tqdm

from swebench.inference.make_datasets.utils import extract_diff
from swebench.eval_pipeline.constants import (
    MODEL_COST_PER_INPUT,
    MODEL_COST_PER_OUTPUT,
)

logger = logging.getLogger(__name__)


def _load_existing_ids(output_file: str, model_name: str | None = None) -> set[str]:
    """Return instance_ids already written to the output file (for resuming).

    If model_name is provided, only count rows whose model_name_or_path matches —
    this prevents re-runs with a different model from silently inheriting another
    model's predictions.
    """
    existing = set()
    path = Path(output_file)
    if not path.exists():
        return existing
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if model_name is not None and obj.get("model_name_or_path") != model_name:
                    continue
                existing.add(obj["instance_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return existing


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


def _call_model(
    prompt: str,
    model_name: str,
    *,
    anthropic_client=None,
    openai_compat_client=None,
    max_tokens: int = 4096,
) -> tuple[str, float]:
    """Dispatch to the right backend."""
    if anthropic_client is not None:
        return _call_anthropic_native(prompt, model_name, anthropic_client, max_tokens)
    if openai_compat_client is not None:
        return _call_openai_compat(prompt, model_name, openai_compat_client, max_tokens)
    raise ValueError("No client provided — pass anthropic_client or openai_compat_client")


def run_inference_for_level(
    instances: list[dict],
    prompts: dict[str, Optional[str]],
    model_name: str,
    output_file: str,
    max_cost: Optional[float] = None,
    max_tokens: int = 4096,
    anthropic_client=None,
    openai_compat_client=None,
    max_workers: int = 8,
) -> None:
    """
    Run inference for one level across all instances, parallelised across workers.

    API calls are I/O-bound (network round-trips to the LLM provider), so
    ThreadPoolExecutor gives near-linear speedup up to the provider's rate limit.
    Default 8 workers is safe for most providers; reduce if you hit 429s.

    Args:
        instances: list of SWEbenchInstance dicts
        prompts: {instance_id: prompt_str or None} — None means skip this level
        model_name: model identifier passed to the API
        output_file: path to write JSONL predictions
        max_cost: stop if cumulative cost exceeds this (USD)
        max_workers: parallel API call threads (default 8)
        anthropic_client: Anthropic SDK client (for claude-* on api.anthropic.com)
        openai_compat_client: openai.OpenAI client (for any OpenAI-compatible endpoint)
    """
    existing_ids = _load_existing_ids(output_file, model_name=model_name)
    if existing_ids:
        logger.info(f"Resuming: {len(existing_ids)} predictions already written for {model_name}")

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    # Filter to instances that actually need work.
    todo = [i for i in instances if i["instance_id"] not in existing_ids]

    total_cost = 0.0
    cost_lock = threading.Lock()
    write_lock = threading.Lock()
    stop_event = threading.Event()

    def _process_one(inst: dict) -> None:
        nonlocal total_cost
        if stop_event.is_set():
            return
        instance_id = inst["instance_id"]
        prompt = prompts.get(instance_id)

        if prompt is None:
            logger.debug(f"Skipping {instance_id}: no prompt for this level")
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "skipped": True,
            }
            with write_lock:
                with open(output_file, "a") as f:
                    print(json.dumps(record), file=f, flush=True)
            return

        try:
            response_text, cost = _call_model(
                prompt, model_name,
                anthropic_client=anthropic_client,
                openai_compat_client=openai_compat_client,
                max_tokens=max_tokens,
            )
            patch = _extract_diff(response_text)
            patch = _clean_patch(patch)
            patch = _repair_patch(patch)

            with cost_lock:
                total_cost += cost
                current_total = total_cost
            logger.info(f"{instance_id}: cost=${cost:.4f}, total=${current_total:.2f}")

            record = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": model_name,
                "full_output": response_text,
            }
        except Exception as e:
            logger.error(f"Error on {instance_id}: {e}")
            traceback.print_exc()
            record = {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": model_name,
                "error": str(e),
            }

        with write_lock:
            with open(output_file, "a") as f:
                print(json.dumps(record), file=f, flush=True)

        if max_cost is not None:
            with cost_lock:
                if total_cost >= max_cost:
                    logger.warning(f"Reached max cost ${max_cost:.2f}, stopping")
                    stop_event.set()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_process_one, inst): inst for inst in todo}
        with tqdm(total=len(todo), desc=f"Inference ({model_name})") as pbar:
            for fut in as_completed(futs):
                fut.result()  # re-raise any unexpected exception
                pbar.update(1)

    logger.info(f"Total inference cost: ${total_cost:.4f}")


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
