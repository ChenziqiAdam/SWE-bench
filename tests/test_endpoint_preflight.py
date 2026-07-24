import json
import urllib.error

import pytest

from swebench.eval_pipeline.endpoint_preflight import (
    anthropic_messages_url,
    probe_anthropic_messages,
)


def test_anthropic_messages_url_accepts_root_and_v1_base():
    assert (
        anthropic_messages_url("http://localhost:4000")
        == "http://localhost:4000/v1/messages"
    )
    assert (
        anthropic_messages_url("http://localhost:4000/v1/")
        == "http://localhost:4000/v1/messages"
    )


def test_probe_sends_authenticated_anthropic_request(monkeypatch):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "OK"}]}).encode()

    def fake_urlopen(request, timeout):
        observed["request"] = request
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(
        "swebench.eval_pipeline.endpoint_preflight.urllib.request.urlopen",
        fake_urlopen,
    )
    probe_anthropic_messages(
        "http://localhost:4000",
        "model-alias",
        "proxy-secret",
        12,
    )

    request = observed["request"]
    assert request.full_url == "http://localhost:4000/v1/messages"
    assert request.get_header("Authorization") == "Bearer proxy-secret"
    assert request.get_header("X-api-key") == "proxy-secret"
    assert json.loads(request.data)["model"] == "model-alias"
    assert observed["timeout"] == 12


def test_probe_rejects_connection_failure(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.endpoint_preflight.urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")
        ),
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        probe_anthropic_messages(
            "http://localhost:4000",
            "model-alias",
            None,
            1,
        )
