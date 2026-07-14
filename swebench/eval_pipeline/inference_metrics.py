"""Normalize inference resource metrics emitted by agent CLIs."""
from __future__ import annotations

import json
from typing import Any


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _usage_metrics(usage: dict) -> dict:
    aliases = {
        "input_tokens": ("input_tokens", "inputTokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "outputTokens", "completion_tokens"),
        "cache_read_input_tokens": (
            "cache_read_input_tokens",
            "cacheReadInputTokens",
            "cached_input_tokens",
        ),
        "cache_creation_input_tokens": (
            "cache_creation_input_tokens",
            "cacheCreationInputTokens",
        ),
    }
    metrics = {}
    for target, names in aliases.items():
        for name in names:
            value = _number(usage.get(name))
            if value is not None:
                metrics[target] = int(value)
                break
    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics["total_tokens"] = metrics.get("input_tokens", 0) + metrics.get(
            "output_tokens", 0
        )
    return metrics


def metrics_from_stream_json(text: str) -> dict:
    """Extract final provider metrics from Codex/Claude-style JSONL output.

    Usage objects in intermediate events are often cumulative or repeated. We
    therefore prefer the last terminal result/turn event instead of summing all
    events, which would over-count long agent trajectories.
    """
    objects = []
    for line in (text or "").splitlines():
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            objects.append(obj)

    terminal = [
        obj
        for obj in objects
        if obj.get("type") in {"result", "turn.completed", "thread.completed"}
    ]
    candidates = terminal or [obj for obj in objects if isinstance(obj.get("usage"), dict)]
    if not candidates:
        return {}

    obj = candidates[-1]
    metrics = _usage_metrics(obj.get("usage") or {})
    mappings = {
        "provider_duration_seconds": ("duration_ms", 0.001),
        "provider_api_duration_seconds": ("duration_api_ms", 0.001),
        "time_to_first_token_seconds": ("ttft_ms", 0.001),
        "cost_usd": ("total_cost_usd", 1.0),
        "turns": ("num_turns", 1.0),
    }
    for target, (source, scale) in mappings.items():
        value = _number(obj.get(source))
        if value is not None:
            metrics[target] = int(value) if target == "turns" else value * scale
    return metrics


def with_wall_time(metrics: dict | None, elapsed_seconds: float) -> dict:
    result = dict(metrics or {})
    result["wall_time_seconds"] = round(max(0.0, elapsed_seconds), 6)
    return result
