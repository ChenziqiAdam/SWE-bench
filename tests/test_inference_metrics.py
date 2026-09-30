import json

from swebench.eval_pipeline.inference_metrics import (
    metrics_from_stream_json,
    turn_limit_exceeded,
)


def test_metrics_from_claude_result_event():
    stream = "\n".join(
        [
            json.dumps({"type": "assistant", "usage": {"input_tokens": 999}}),
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 2500,
                    "duration_api_ms": 2000,
                    "ttft_ms": 125,
                    "num_turns": 3,
                    "total_cost_usd": 0.42,
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cache_read_input_tokens": 30,
                        "cache_creation_input_tokens": 4,
                    },
                }
            ),
        ]
    )

    assert metrics_from_stream_json(stream) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 4,
        "total_tokens": 120,
        "provider_duration_seconds": 2.5,
        "provider_api_duration_seconds": 2.0,
        "time_to_first_token_seconds": 0.125,
        "cost_usd": 0.42,
        "turns": 3,
    }


def test_metrics_from_codex_turn_event_aliases():
    stream = json.dumps(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 12,
                "cached_input_tokens": 8,
                "output_tokens": 5,
            },
        }
    )

    metrics = metrics_from_stream_json(stream)
    assert metrics["total_tokens"] == 17
    assert metrics["cache_read_input_tokens"] == 8


def test_codex_raw_stream_preserves_usage_and_counts_observable_steps():
    stream = "\n".join(json.dumps(event) for event in [
        {"type": "thread.started", "thread_id": "example"},
        {"type": "item.started", "item": {"id": "tool-1", "type": "command_execution"}},
        {"type": "item.completed", "item": {"id": "tool-1", "type": "command_execution"}},
        {"type": "item.completed", "item": {"id": "message-1", "type": "agent_message"}},
        {"type": "turn.completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 60,
            "cache_write_input_tokens": 4, "output_tokens": 20,
            "reasoning_output_tokens": 7,
        }},
    ])
    metrics = metrics_from_stream_json(stream)
    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] == 20
    assert metrics["cache_read_input_tokens"] == 60
    assert metrics["cache_creation_input_tokens"] == 4
    assert metrics["reasoning_output_tokens"] == 7
    assert metrics["tool_calls"] == 1
    assert metrics["model_response_steps_observed"] == 2
    assert metrics["api_calls_exact_available"] is False


def test_metrics_recovers_observed_claude_usage_without_terminal_event():
    stream = "\n".join([
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "message-1",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        }),
        # A second streamed chunk for the same message must not be double-counted.
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "message-1",
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        }),
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "message-2",
                "usage": {
                    "input_tokens": 4,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 20,
                },
            },
        }),
    ])

    assert metrics_from_stream_json(stream) == {
        "usage_incomplete": True,
        "input_tokens": 14,
        "output_tokens": 4,
        "cache_read_input_tokens": 20,
        "total_tokens": 18,
        "turns": 2,
    }


def test_metrics_from_gemini_result_stats():
    stream = json.dumps({
        "type": "result",
        "status": "success",
        "stats": {
            "total_tokens": 250,
            "input_tokens": 50,
            "output_tokens": 200,
            "cached": 12,
            "duration_ms": 3000,
            "turns": 4,
            "tool_calls": 3,
        },
    })

    assert metrics_from_stream_json(stream) == {
        "input_tokens": 50,
        "output_tokens": 200,
        "cache_read_input_tokens": 12,
        "total_tokens": 250,
        "provider_duration_seconds": 3.0,
        "turns": 4,
        "tool_calls": 3,
    }


def test_metrics_from_gemini_detailed_stats():
    stream = json.dumps({
        "type": "result",
        "stats": {
            "models": {
                "gemini": {
                    "tokens": {"prompt": 20, "candidates": 5, "cached": 7, "total": 30},
                }
            },
            "tools": {"totalCalls": 2},
        },
    })

    assert metrics_from_stream_json(stream) == {
        "input_tokens": 20,
        "output_tokens": 5,
        "cache_read_input_tokens": 7,
        "total_tokens": 30,
        "tool_calls": 2,
    }


def test_metrics_from_antigravity_terminal_result_and_tool_steps():
    stream = "\n".join(
        [
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "c",
                        "step_index": 3,
                        "state": "ACTIVE",
                        "step_type": "tool",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "c",
                        "step_index": 3,
                        "state": "DONE",
                        "step_type": "tool",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "result",
                    "result": {
                        "status": "SUCCESS",
                        "duration_seconds": 4.5,
                        "num_turns": 2,
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 25,
                            "cache_read_tokens": 40,
                        },
                    },
                }
            ),
        ]
    )

    assert metrics_from_stream_json(stream) == {
        "input_tokens": 100,
        "output_tokens": 25,
        "cache_read_input_tokens": 40,
        "total_tokens": 125,
        "provider_duration_seconds": 4.5,
        "turns": 2,
        "tool_calls": 1,
    }


def test_turn_limit_exceeded_uses_backend_specific_metric_and_cap():
    assert turn_limit_exceeded("claude_code", {"turns": 141}) is True
    assert turn_limit_exceeded("claude_code", {"turns": 140}) is False
    assert turn_limit_exceeded("codex", {"model_response_steps_observed": 61}) is True
    assert turn_limit_exceeded("codex", {"model_response_steps_observed": 60}) is False
    assert turn_limit_exceeded("agy", {"tool_calls": 351}) is True
    assert turn_limit_exceeded("agy", {"tool_calls": 350}) is False


def test_turn_limit_exceeded_ignores_missing_metric_or_unknown_backend():
    assert turn_limit_exceeded("codex", {}) is False
    assert turn_limit_exceeded("unknown_backend", {"turns": 10_000}) is False
