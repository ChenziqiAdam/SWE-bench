import json

from swebench.eval_pipeline.inference_metrics import metrics_from_stream_json


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
