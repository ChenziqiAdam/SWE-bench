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
            "cache_read_tokens",
            "cached",
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
        or obj.get("event") == "result"
    ]
    candidates = terminal or [obj for obj in objects if isinstance(obj.get("usage"), dict)]
    if not candidates:
        # Claude stream-json can end before its terminal result (for example,
        # exit 129/SIGHUP) while still containing usage on assistant messages.
        # Keep the last usage snapshot per message id to avoid counting streamed
        # chunks repeatedly, then expose the observed lower bound explicitly.
        messages: dict[str, dict] = {}
        for index, event in enumerate(objects):
            message = event.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                continue
            key = str(message.get("id") or event.get("uuid") or index)
            messages[key] = message["usage"]
        if not messages:
            return {}
        observed: dict[str, int | bool] = {"usage_incomplete": True}
        for usage in messages.values():
            for key, value in _usage_metrics(usage).items():
                if key == "total_tokens":
                    continue
                observed[key] = int(observed.get(key, 0)) + int(value)
        observed["total_tokens"] = int(observed.get("input_tokens", 0)) + int(
            observed.get("output_tokens", 0)
        )
        observed["turns"] = len(messages)
        return observed

    obj = candidates[-1]
    if obj.get("event") == "result" and isinstance(obj.get("result"), dict):
        obj = obj["result"]
    stats = obj.get("stats") if isinstance(obj.get("stats"), dict) else {}
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else stats
    metrics = _usage_metrics(usage)
    # Gemini CLI's compact stream result reports aggregate usage directly in
    # ``result.stats``. Its detailed schema instead reports per-model token
    # objects, which must be summed once at the terminal event.
    models = stats.get("models") if isinstance(stats.get("models"), dict) else {}
    if not metrics and models:
        aggregate = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "total_tokens": 0,
        }
        for model in models.values():
            tokens = model.get("tokens") if isinstance(model, dict) else None
            if not isinstance(tokens, dict):
                continue
            aggregate["input_tokens"] += int(_number(tokens.get("prompt")) or 0)
            aggregate["output_tokens"] += int(_number(tokens.get("candidates")) or 0)
            aggregate["cache_read_input_tokens"] += int(
                _number(tokens.get("cached")) or 0
            )
            aggregate["total_tokens"] += int(_number(tokens.get("total")) or 0)
        metrics = {key: value for key, value in aggregate.items() if value}
    stats_total = _number(stats.get("total_tokens"))
    if stats_total is not None:
        metrics["total_tokens"] = int(stats_total)
    mappings = {
        "provider_duration_seconds": ("duration_ms", 0.001),
        "provider_api_duration_seconds": ("duration_api_ms", 0.001),
        "time_to_first_token_seconds": ("ttft_ms", 0.001),
        "cost_usd": ("total_cost_usd", 1.0),
        "turns": ("num_turns", 1.0),
    }
    for target, (source, scale) in mappings.items():
        value = _number(obj.get(source))
        if value is None:
            value = _number(stats.get(source))
        if value is not None:
            metrics[target] = int(value) if target == "turns" else value * scale
    duration_seconds = _number(obj.get("duration_seconds"))
    if duration_seconds is not None:
        metrics["provider_duration_seconds"] = duration_seconds
    for source in ("turns", "num_turns"):
        value = _number(stats.get(source))
        if value is not None:
            metrics["turns"] = int(value)
            break
    tool_calls = _number(stats.get("tool_calls"))
    tools = stats.get("tools") if isinstance(stats.get("tools"), dict) else {}
    if tool_calls is None:
        tool_calls = _number(tools.get("totalCalls"))
    if tool_calls is not None:
        metrics["tool_calls"] = int(tool_calls)
    elif objects:
        steps = {
            (
                event.get("step_update", {}).get("conversation_id"),
                event.get("step_update", {}).get("step_index"),
            )
            for event in objects
            if event.get("event") == "step_update"
            and isinstance(event.get("step_update"), dict)
            and event["step_update"].get("step_type") == "tool"
        }
        if steps:
            metrics["tool_calls"] = len(steps)
    return metrics


def with_wall_time(metrics: dict | None, elapsed_seconds: float) -> dict:
    result = dict(metrics or {})
    result["wall_time_seconds"] = round(max(0.0, elapsed_seconds), 6)
    return result
