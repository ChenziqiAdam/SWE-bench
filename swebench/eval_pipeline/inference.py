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
import traceback
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


def _load_existing_ids(output_file: str) -> set[str]:
    """Return instance_ids already written to the output file (for resuming)."""
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


def _clean_patch(patch: str) -> str:
    """Clean common model-output artifacts from a patch string."""
    if not patch:
        return patch

    # Strip markdown code fences (```diff ... ``` or ``` ... ```)
    import re
    patch = re.sub(r"^```[a-zA-Z]*\n?", "", patch.strip())
    patch = re.sub(r"\n?```$", "", patch)

    # Strip unclosed/closed <patch> tags
    patch = re.sub(r"^\s*<patch>\s*", "", patch)
    patch = re.sub(r"\s*</patch>\s*$", "", patch)

    # Ensure patch ends with a newline
    if patch and not patch.endswith("\n"):
        patch += "\n"

    return patch


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
) -> None:
    """
    Run inference for one level across all instances.

    Args:
        instances: list of SWEbenchInstance dicts
        prompts: {instance_id: prompt_str or None} — None means skip this level
        model_name: model identifier passed to the API (e.g. "claude-sonnet-4-6",
                    "gpt-4o", "mistral-large", "llama3:70b", ...)
        output_file: path to write JSONL predictions
        max_cost: stop if cumulative cost exceeds this (USD)
        anthropic_client: Anthropic SDK client (for claude-* on api.anthropic.com)
        openai_compat_client: openai.OpenAI client (for any OpenAI-compatible endpoint)
    """
    existing_ids = _load_existing_ids(output_file)
    if existing_ids:
        logger.info(f"Resuming: {len(existing_ids)} predictions already written")

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    total_cost = 0.0

    with open(output_file, "a") as f:
        for inst in tqdm(instances, desc=f"Inference ({model_name})"):
            instance_id = inst["instance_id"]

            if instance_id in existing_ids:
                continue

            prompt = prompts.get(instance_id)
            if prompt is None:
                logger.debug(f"Skipping {instance_id}: no prompt for this level")
                # Write empty patch so the eval harness can record it as unresolved
                record = {
                    "instance_id": instance_id,
                    "model_patch": "",
                    "model_name_or_path": model_name,
                    "skipped": True,
                }
                print(json.dumps(record), file=f, flush=True)
                continue

            try:
                response_text, cost = _call_model(
                    prompt, model_name,
                    anthropic_client=anthropic_client,
                    openai_compat_client=openai_compat_client,
                    max_tokens=max_tokens,
                )
                patch = extract_diff(response_text)
                patch = _clean_patch(patch)
                total_cost += cost
                logger.info(f"{instance_id}: cost=${cost:.4f}, total=${total_cost:.2f}")

                record = {
                    "instance_id": instance_id,
                    "model_patch": patch,
                    "model_name_or_path": model_name,
                    "full_output": response_text,
                }
                print(json.dumps(record), file=f, flush=True)

            except Exception as e:
                logger.error(f"Error on {instance_id}: {e}")
                traceback.print_exc()
                record = {
                    "instance_id": instance_id,
                    "model_patch": "",
                    "model_name_or_path": model_name,
                    "error": str(e),
                }
                print(json.dumps(record), file=f, flush=True)

            if max_cost is not None and total_cost >= max_cost:
                logger.warning(f"Reached max cost ${max_cost:.2f}, stopping")
                break

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
        openai_compat_client = openai_mod.OpenAI(base_url=endpoint, api_key=resolved_key)
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
        openai_compat_client = openai_mod.OpenAI(api_key=resolved_key)
        logger.info(f"Using OpenAI native API (model={model_name})")

    return anthropic_client, openai_compat_client
