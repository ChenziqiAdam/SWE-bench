"""Restricted public-bundle file tools and API loop for 0017_core blind gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


def read_env(path: Path) -> dict[str, str]:
    required = {"ENDPOINT", "API_KEY", "MODEL_NAME"}
    allowed = required | {"FALLBACK_MODEL_NAME"}; result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1); key = key.strip()
        if key in allowed:
            result[key] = value.strip().strip("'\"")
    if required - result.keys():
        raise RuntimeError(f"missing .env fields: {sorted(required - result.keys())}")
    if not result.get("FALLBACK_MODEL_NAME"):
        result.pop("FALLBACK_MODEL_NAME", None)
    return result


TOOLS = [
    {"type": "function", "function": {"name": "list_public_files", "description": "List files in the read-only public benchmark bundle.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_public_text", "description": "Read a UTF-8 public file chunk. Use offsets for large JSON or CSV files.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50000}}, "required": ["path"], "additionalProperties": False}}},
]


def public_files(root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in sorted(root.rglob("*")) if path.is_file()]


def handle_tool(root: Path, name: str, arguments: str) -> str:
    args = json.loads(arguments or "{}")
    if name == "list_public_files":
        return json.dumps(public_files(root))
    if name != "read_public_text":
        raise RuntimeError(f"unknown tool {name}")
    relative = Path(args["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("path outside public bundle")
    path = (root / relative).resolve(); path.relative_to(root.resolve())
    if path.suffix.lower() == ".pdf":
        return json.dumps({"path": relative.as_posix(), "error": "paper text is already supplied in the prompt"})
    offset = int(args.get("offset", 0)); limit = int(args.get("limit", 20000))
    text = path.read_text(encoding="utf-8")
    return json.dumps({"path": relative.as_posix(), "offset": offset, "total_characters": len(text), "content": text[offset:offset + limit]})


def run_context(env: dict[str, str], prompt: str, public_root: Path, timeout: float, extra_tools: list[dict] | None = None, extra_handler=None) -> tuple[str, str]:
    endpoint = env["ENDPOINT"].rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tools = TOOLS + (extra_tools or [])
    actual_model = ""
    # Large public CSV/output artifacts may require many bounded reads. Keep a
    # finite fail-closed ceiling while allowing the blind agent to inspect them.
    for _ in range(100):
        response = requests.post(endpoint, headers={"Authorization": f"Bearer {env['API_KEY']}", "Content-Type": "application/json"},
                                 json={"model": env["MODEL_NAME"], "messages": messages, "tools": tools, "temperature": 0.1, "max_tokens": 12000,
                                       "reasoning": {"effort": "minimal", "exclude": True}}, timeout=timeout)
        response.raise_for_status(); envelope = response.json()
        actual_model = envelope.get("model", "")
        if actual_model != env["MODEL_NAME"]:
            raise RuntimeError(f"actual model mismatch: configured={env['MODEL_NAME']!r}, actual={actual_model!r}")
        message = envelope["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("model returned no final content")
            return content.strip(), actual_model
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        for call in calls:
            function = call["function"]
            if function["name"] in {"list_public_files", "read_public_text"}:
                result = handle_tool(public_root, function["name"], function.get("arguments", "{}"))
            elif extra_handler:
                result = extra_handler(function["name"], function.get("arguments", "{}"))
            else:
                raise RuntimeError(f"unexpected tool {function['name']}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    raise RuntimeError("model exceeded tool-call turn limit")
