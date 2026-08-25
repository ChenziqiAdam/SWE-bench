"""Local Anthropic-stream proxy with a persistent rolling request limiter."""
from __future__ import annotations

import email.utils
import http.client
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable


TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
FATAL_STATUSES = {400, 401, 403, 404, 422}


def normalize_openrouter_endpoint(endpoint: str) -> str:
    """Convert OpenAI-style OpenRouter URLs to its Anthropic-compatible base."""
    parsed = urllib.parse.urlparse(endpoint.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "openrouter.ai":
        raise ValueError("ENDPOINT must be an https://openrouter.ai URL")
    return "https://openrouter.ai/api"


def redact_secrets(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def classify_provider_failure(
    status: int | None,
    *,
    payload: bytes | str = b"",
    interrupted: bool = False,
) -> str | None:
    """Classify only credential/permission/model failures as globally fatal."""
    if interrupted or status is None:
        return "transient"
    if status in TRANSIENT_STATUSES or 500 <= status <= 599:
        return "transient"
    if status in {401, 403}:
        return "fatal"
    if isinstance(payload, bytes):
        detail = payload.decode(errors="replace").lower()
    else:
        detail = payload.lower()
    fatal_markers = (
        "invalid api key",
        "invalid x-api-key",
        "authentication",
        "unauthorized",
        "permission denied",
        "insufficient permission",
        "model not found",
        "model_not_found",
        "unknown model",
        "no endpoints found",
    )
    if status in {400, 404, 422}:
        if any(marker in detail for marker in fatal_markers):
            return "fatal"
        # A generic 404 is commonly a Claude Code capability probe. A generic
        # 400/422 can be instance-specific context/tool state and is retried
        # from a fresh CLI process rather than aborting successful peers.
        return None if status == 404 else "transient"
    return None


def retry_delay(
    attempt: int,
    retry_after: str | None,
    *,
    now: Callable[[], float] = time.time,
    uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    if retry_after:
        try:
            return min(900.0, max(0.0, float(retry_after)))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                return min(900.0, max(0.0, parsed.timestamp() - now()))
            except (TypeError, ValueError, OverflowError):
                pass
    ceiling = min(900.0, 2.0 ** min(attempt, 10))
    return uniform(ceiling / 2.0, ceiling)


class RollingWindowLimiter:
    """Thread-safe rolling limiter whose admissions survive process restarts."""

    def __init__(
        self,
        path: Path,
        limit: int = 20,
        window: float = 60.0,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.path = path
        self.limit = limit
        self.window = window
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()

    def _load(self, now: float) -> list[float]:
        try:
            value = json.loads(self.path.read_text())
            timestamps = value.get("admissions", [])
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            timestamps = []
        return sorted(
            float(item) for item in timestamps if now - self.window < float(item) <= now
        )

    def _save(self, timestamps: list[float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"admissions": timestamps}) + "\n")
        os.replace(temporary, self.path)

    def acquire(self) -> float:
        while True:
            with self._lock:
                now = self.clock()
                timestamps = self._load(now)
                if len(timestamps) < self.limit:
                    timestamps.append(now)
                    self._save(timestamps)
                    return now
                delay = max(0.001, timestamps[0] + self.window - now)
            self.sleep(delay)

    def record(self, admitted_at: float) -> None:
        """Persist an upstream admission performed before the proxy started."""
        with self._lock:
            timestamps = self._load(max(self.clock(), admitted_at))
            timestamps.append(admitted_at)
            self._save(sorted(timestamps))


class ClaudeStreamGateway:
    """Forward Claude Code messages to OpenRouter without retaining payloads."""

    def __init__(
        self,
        upstream_base: str,
        api_key: str,
        state_dir: Path,
        *,
        rpm: int = 20,
        opener: Callable[..., object] = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        initial_admissions: list[float] | None = None,
    ):
        self.upstream_base = upstream_base.rstrip("/")
        self.api_key = api_key
        self.state_dir = state_dir
        self.limiter = RollingWindowLimiter(state_dir / "rate_limit_state.json", rpm)
        self.opener = opener
        self.sleeper = sleeper
        self.initial_admissions = list(initial_admissions or [])
        self.failures: dict[str, list[dict]] = defaultdict(list)
        self._failure_lock = threading.Lock()
        self._diagnostic_lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.local_base = ""

    def _diagnostic(self, value: dict) -> None:
        value = {k: v for k, v in value.items() if k not in {"body", "headers", "api_key"}}
        path = self.state_dir / "gateway_diagnostics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._diagnostic_lock, path.open("a") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

    @staticmethod
    def _stream_response(response, writer) -> None:
        """Copy an upstream response incrementally without buffering its body."""
        while True:
            chunk = response.read(65536)
            if not chunk:
                return
            writer.write(chunk)
            flush = getattr(writer, "flush", None)
            if flush:
                flush()

    def _record_failure(
        self, instance_id: str, kind: str, status: int | None, retry_after: str | None = None
    ) -> None:
        with self._failure_lock:
            self.failures[instance_id].append(
                {"kind": kind, "status": status, "retry_after": retry_after}
            )

    def failure_for(self, instance_id: str) -> str | None:
        with self._failure_lock:
            failures = list(self.failures.get(instance_id, []))
        if any(item["kind"] == "fatal" for item in failures):
            return "fatal"
        if any(item["kind"] == "transient" for item in failures):
            return "transient"
        return None

    def retry_after_for(self, instance_id: str) -> str | None:
        with self._failure_lock:
            values = [
                item.get("retry_after")
                for item in self.failures.get(instance_id, [])
                if item.get("retry_after")
            ]
        return values[-1] if values else None

    def clear_failure(self, instance_id: str) -> None:
        with self._failure_lock:
            self.failures.pop(instance_id, None)

    def _handler(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                parts = self.path.split("/", 3)
                instance_id = urllib.parse.unquote(parts[2]) if len(parts) > 3 and parts[1] == "instance" else "preflight"
                upstream_path = "/" + parts[3] if len(parts) > 3 and parts[1] == "instance" else self.path
                started = time.monotonic()
                gateway.limiter.acquire()
                request = urllib.request.Request(
                    gateway.upstream_base + upstream_path,
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {gateway.api_key}",
                        "Content-Type": self.headers.get("Content-Type", "application/json"),
                        "Accept": self.headers.get("Accept", "text/event-stream"),
                        "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
                    },
                )
                status = None
                try:
                    response = gateway.opener(request, timeout=900)
                    status = getattr(response, "status", 200)
                    self.send_response(status)
                    for name, value in response.headers.items():
                        if name.lower() in {"content-type", "request-id", "retry-after"}:
                            self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    gateway._stream_response(response, self.wfile)
                    gateway.clear_failure(instance_id)
                except urllib.error.HTTPError as exc:
                    status = exc.code
                    payload = exc.read()
                    kind = classify_provider_failure(status, payload=payload)
                    if kind:
                        gateway._record_failure(
                            instance_id, kind, status, exc.headers.get("Retry-After")
                        )
                    self.send_response(status)
                    if exc.headers.get("Retry-After"):
                        self.send_header("Retry-After", exc.headers["Retry-After"])
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (
                    OSError,
                    urllib.error.URLError,
                    TimeoutError,
                    http.client.HTTPException,
                ):
                    gateway._record_failure(instance_id, "transient", None)
                    try:
                        self.send_error(502, "upstream connection failed")
                    except OSError:
                        pass
                finally:
                    gateway._diagnostic(
                        {
                            "timestamp": time.time(),
                            "instance_id": instance_id,
                            "status": status,
                            "duration_seconds": round(time.monotonic() - started, 3),
                        }
                    )

        return Handler

    def start(self) -> str:
        for admitted_at in self.initial_admissions:
            self.limiter.record(admitted_at)
        self.initial_admissions.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.local_base = f"http://{host}:{port}"
        return self.local_base

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)
