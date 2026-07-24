"""Authenticated Anthropic-compatible endpoint preflight."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse


def anthropic_messages_url(endpoint: str) -> str:
    """Return the Messages API URL for an Anthropic-compatible base URL."""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid HTTP(S) model endpoint: {endpoint!r}")
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path += "/messages"
    elif not path.endswith("/v1/messages"):
        path += "/v1/messages"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def probe_anthropic_messages(
    endpoint: str,
    model: str,
    api_key: str | None,
    timeout: float,
) -> None:
    """Send one real, minimal Messages request and validate its response."""
    payload = json.dumps(
        {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "Reply OK."}],
        }
    ).encode()
    headers = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    request = urllib.request.Request(
        anthropic_messages_url(endpoint),
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode(errors="replace")
        raise RuntimeError(
            f"Messages preflight returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Messages preflight could not connect: {exc.reason}") from exc
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Messages preflight returned non-JSON content") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("content"), list):
        raise RuntimeError(
            "Messages preflight response is not Anthropic-compatible "
            "(missing content list)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )
    try:
        probe_anthropic_messages(
            args.endpoint,
            args.model,
            api_key,
            args.timeout,
        )
    except Exception as exc:
        print(f"Anthropic endpoint preflight failed: {exc}", file=sys.stderr)
        return 2
    print("Anthropic endpoint preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
