"""Resumable Issues_No_Tests inference with the official mini-swe-agent CLI.

Same protocol as ``offline_codex_run`` (issue-only prompt, fresh base checkout,
waves, per-instance checkpoints, trajectory audit, manual review queue); only
the agent process differs. Inference runs locally and writes
``agent_predictions.jsonl`` for evaluation on a server.

Under the default ``model-only`` policy the agent process can reach nothing but
a loopback gateway started by this script. The gateway forwards to an
OpenAI-compatible upstream and injects the real API key, so the key never
enters the sandboxed process. ``unrestricted`` is a non-benchmark debug mode.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import http.client
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from swebench.eval_pipeline.inference import _clean_patch, _repair_patch
from swebench.eval_pipeline.inference_metrics import with_wall_time
from swebench.eval_pipeline.inference_security import (
    inference_hidden_paths,
    inference_input_hash,
    inference_worktree_root,
)
from swebench.eval_pipeline.mini_swe_agent_inference import (
    _command,
    _installed_mini_version,
    _load_trajectory,
    _mini_swe_agent_bin,
    _redact,
    _trajectory_metrics,
)
from swebench.eval_pipeline.network_isolation import (
    guard_command,
    validate_network_policy,
)
from swebench.issue_pipeline import offline_codex_run as base
from swebench.issue_pipeline.offline_codex_pilot import (
    _NETWORK_COMMAND_PATTERNS,
    EVAL_MODE,
    AuditFinding,
    _strip_build_artifact_diff_blocks,
    _untracked_root_scratch_paths,
    _untracked_scratch_noise_paths,
    audit_patch_paths,
    build_pilot_prompt,
)
from swebench.eval_pipeline.codex_inference import _capture_patch

AGENT_BACKEND = "mini_swe_agent"
TIMEOUT = 900
COMMAND_TIMEOUT = 300
DUMMY_KEY = "sk-local-gateway"
DEFAULT_UPSTREAM = "https://api.openai.com"
GATEWAY_ATTEMPTS = 5
_RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504, 529}
# Provider/network trouble, not a model outcome: leave the instance pending.
_QUOTA_MARKERS = (
    "insufficient_quota",
    "exceeded your current quota",
    "usage limit",
    "upstream error",
    "ratelimiterror",
    "apiconnectionerror",
    "serviceunavailableerror",
    "internalservererror",
    "timeouterror",
    "overloaded",
)


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    try:
        return min(float(retry_after), 60.0) if retry_after else min(2.0**attempt, 30.0)
    except ValueError:
        return min(2.0**attempt, 30.0)


# --------------------------------------------------------------------------- #
# Loopback gateway
# --------------------------------------------------------------------------- #
INSTANCE_HEADER = "X-SWE-Instance"
_LOG_BODY_CAP = 32 * 1024 * 1024
_KEEP_HEADERS = (
    "x-request-id",
    "openai-processing-ms",
    "openai-version",
    "retry-after",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
)


def _summarize_request(body: bytes | None) -> dict:
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload[key]
        for key in ("model", "stream", "reasoning", "reasoning_effort", "service_tier", "store")
        if key in payload
    } | {
        "tools": len(payload.get("tools") or []),
        "input_items": len(payload["input"]) if isinstance(payload.get("input"), list) else None,
    }


def _summarize_response(data: bytes) -> dict:
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    summary = {
        key: payload[key]
        for key in ("id", "model", "status", "service_tier", "error", "incomplete_details")
        if payload.get(key) is not None
    }
    if isinstance(payload.get("usage"), dict):
        summary["usage"] = payload["usage"]
    return summary


class _GatewayHandler(BaseHTTPRequestHandler):
    # HTTP/1.0: the response ends when the connection closes, so streamed
    # upstream bodies can be relayed without knowing their length.
    protocol_version = "HTTP/1.0"
    upstream: str = DEFAULT_UPSTREAM
    api_key: str = ""
    log_path: Path | None = None
    log_lock = threading.Lock()

    def log_message(self, *args: Any) -> None:  # keep the key out of any log
        return

    def _log(self, record: dict) -> None:
        if self.log_path is None:
            return
        with self.log_lock, self.log_path.open("a") as handle:
            print(json.dumps(record, ensure_ascii=False), file=handle, flush=True)

    def _forward(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(403, "only /v1/ routes are proxied")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        parsed = urlparse(self.upstream)
        conn_cls = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept-Encoding": "identity",
        }
        for name in ("Content-Type", "Accept", "OpenAI-Beta"):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        prefix = parsed.path.rstrip("/")
        started = time.time()
        record: dict[str, Any] = {
            "ts": started,
            "instance_id": self.headers.get(INSTANCE_HEADER),
            "method": self.command,
            "path": self.path,
            "request_bytes": len(body or b""),
            "request": _summarize_request(body),
            "attempts": [],
        }
        for attempt in range(1, GATEWAY_ATTEMPTS + 1):
            last = attempt == GATEWAY_ATTEMPTS
            conn = None
            attempt_started = time.time()
            try:
                conn = conn_cls(parsed.netloc, timeout=600)
                conn.request(
                    self.command, prefix + self.path, body=body, headers=headers
                )
                response = conn.getresponse()
                record["attempts"].append(
                    {"status": response.status, "headers_s": round(time.time() - attempt_started, 3)}
                )
                if response.status in _RETRY_STATUSES and not last:
                    data = response.read()
                    # A spent quota never recovers by retrying.
                    if b"insufficient_quota" not in data:
                        record["attempts"][-1]["error_body"] = data[:500].decode(errors="replace")
                        delay = _retry_delay(response.getheader("Retry-After"), attempt)
                        conn.close()
                        time.sleep(delay)
                        continue
                    self._finish(record, response, data)
                    conn.close()
                    return
                self._finish(record, response)
                conn.close()
                return
            except OSError as exc:
                if conn is not None:
                    conn.close()
                record["attempts"].append({"error": type(exc).__name__})
                if last:
                    record["final"] = "gateway_502"
                    record["latency_s"] = round(time.time() - started, 3)
                    self._log(record)
                    self.send_error(502, f"upstream error: {type(exc).__name__}")
                    return
                time.sleep(_retry_delay(None, attempt))

    def _finish(
        self, record: dict, response: http.client.HTTPResponse, data: bytes | None = None
    ) -> None:
        self.send_response(response.status)
        for name in ("Content-Type", "Retry-After"):
            if response.getheader(name):
                self.send_header(name, response.getheader(name))
        self.end_headers()
        captured = bytearray()
        total = 0
        try:
            if data is not None:
                self.wfile.write(data)
                captured.extend(data)
                total = len(data)
            else:
                while chunk := response.read(8192):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    total += len(chunk)
                    if len(captured) < _LOG_BODY_CAP:
                        captured.extend(chunk)
        finally:
            record["status"] = response.status
            record["response_bytes"] = total
            record["latency_s"] = round(time.time() - record["ts"], 3)
            record["response_headers"] = {
                name: response.getheader(name)
                for name in _KEEP_HEADERS
                if response.getheader(name)
            }
            if "json" in (response.getheader("Content-Type") or "") and total <= _LOG_BODY_CAP:
                record["response"] = _summarize_response(bytes(captured))
            self._log(record)

    do_POST = do_GET = _forward


class LoopbackGateway:
    """127.0.0.1 forwarder that adds the real API key to OpenAI-style calls.

    With ``log_path`` every upstream call (including retries and failures that
    never reach the agent trajectory) is appended as one JSON line, attributed
    to an instance through the ``X-SWE-Instance`` request header.
    """

    def __init__(self, upstream: str, api_key: str, log_path: Path | None = None) -> None:
        handler = type(
            "Handler",
            (_GatewayHandler,),
            {
                "upstream": upstream,
                "api_key": api_key,
                "log_path": log_path,
                "log_lock": threading.Lock(),
            },
        )
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def __enter__(self) -> "LoopbackGateway":
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()


# --------------------------------------------------------------------------- #
# Trajectory audit
# --------------------------------------------------------------------------- #
def trajectory_commands(trajectory: dict) -> list[tuple[int, str]]:
    """Return (message index, shell command) for every action the agent took."""
    commands: list[tuple[int, str]] = []
    for index, message in enumerate(trajectory.get("messages") or []):
        if not isinstance(message, dict):
            continue
        extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
        for action in extra.get("actions") or []:
            if isinstance(action, dict) and action.get("command"):
                commands.append((index, str(action["command"])))
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if isinstance(arguments, dict) and arguments.get("command"):
                commands.append((index, str(arguments["command"])))
    return commands


def audit_trajectory(trajectory: dict) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    seen: set[tuple[str, str]] = set()
    for index, command in trajectory_commands(trajectory):
        for kind, pattern in _NETWORK_COMMAND_PATTERNS:
            if pattern.search(command) and (kind, command) not in seen:
                seen.add((kind, command))
                findings.append(AuditFinding(kind, index, command))
    return findings


# --------------------------------------------------------------------------- #
# Step log and usage accounting
# --------------------------------------------------------------------------- #
def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _usage_row(usage: dict | None) -> dict:
    usage = usage if isinstance(usage, dict) else {}
    in_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    out_details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    input_tokens = _int(usage.get("input_tokens", usage.get("prompt_tokens")))
    output_tokens = _int(usage.get("output_tokens", usage.get("completion_tokens")))
    cached = _int(in_details.get("cached_tokens"))
    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached,
        "cache_write_tokens": _int(in_details.get("cache_write_tokens")),
        "uncached_input_tokens": max(input_tokens - cached, 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": _int(out_details.get("reasoning_tokens")),
        "total_tokens": _int(usage.get("total_tokens")) or input_tokens + output_tokens,
    }


def build_step_log(trajectory: dict) -> list[dict]:
    """One row per model call: usage, reasoning, commentary, tool calls, results.

    ``gpt-6.1-sol`` returns reasoning only as encrypted items, so we record how
    many reasoning items/tokens a step had, never the reasoning text.
    """
    messages = [m for m in trajectory.get("messages") or [] if isinstance(m, dict)]
    steps: list[dict] = []
    by_call: dict[str, dict] = {}
    for message in messages:
        extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
        if message.get("object") == "response":  # Responses API
            output = message.get("output") or []
            row = {
                "step": len(steps) + 1,
                "response_id": message.get("id"),
                "created_at": message.get("created_at"),
                "timestamp": extra.get("timestamp"),
                "model": message.get("model"),
                "status": message.get("status"),
                "service_tier": message.get("service_tier"),
                "reasoning_setting": message.get("reasoning"),
                "usage": _usage_row(message.get("usage")),
                "cost_reported": extra.get("cost"),
                "reasoning_items": sum(1 for o in output if o.get("type") == "reasoning"),
                "reasoning_summary": [
                    part.get("text")
                    for o in output
                    if o.get("type") == "reasoning"
                    for part in (o.get("summary") or [])
                    if isinstance(part, dict)
                ],
                "reasoning_encrypted_chars": sum(
                    len(o.get("encrypted_content") or "")
                    for o in output
                    if o.get("type") == "reasoning"
                ),
                "commentary": [
                    part.get("text")
                    for o in output
                    if o.get("type") == "message"
                    for part in (o.get("content") or [])
                    if isinstance(part, dict) and part.get("text")
                ],
                "tool_calls": [],
                "observations": [],
            }
            actions = {a.get("tool_call_id"): a for a in extra.get("actions") or [] if isinstance(a, dict)}
            for item in output:
                if item.get("type") != "function_call":
                    continue
                try:
                    arguments = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {"raw": item.get("arguments")}
                call = {
                    "call_id": item.get("call_id"),
                    "name": item.get("name"),
                    "command": (arguments.get("command") if isinstance(arguments, dict) else None)
                    or (actions.get(item.get("call_id")) or {}).get("command"),
                }
                row["tool_calls"].append(call)
                by_call[item.get("call_id")] = row
            steps.append(row)
        elif message.get("type") == "function_call_output":
            row = by_call.get(message.get("call_id"))
            if row is None:
                continue
            start = row.get("timestamp")
            end = extra.get("timestamp")
            row["observations"].append(
                {
                    "call_id": message.get("call_id"),
                    "returncode": extra.get("returncode"),
                    "output_chars": len(extra.get("raw_output") or ""),
                    "exec_s": round(end - start, 3)
                    if isinstance(start, (int, float)) and isinstance(end, (int, float))
                    else None,
                    "exception": extra.get("exception_info") or None,
                }
            )
        elif message.get("role") == "exit":
            steps.append({"exit": message.get("content"), "extra": extra or None})
    return steps


LONG_CONTEXT_TOKENS = 272_000


def call_cost(usage: dict, prices: dict) -> float:
    """USD for one call. Cache writes are a subset of non-cached input and have
    their own rate; above 272K input tokens the whole request is surcharged
    (2x input/cache rates, 1.5x output). Reasoning tokens are inside output."""
    long_context = usage["input_tokens"] > LONG_CONTEXT_TOKENS
    rate_mult, out_mult = (2.0, 1.5) if long_context else (1.0, 1.0)
    write = min(usage["cache_write_tokens"], usage["uncached_input_tokens"])
    plain = usage["uncached_input_tokens"] - write
    write_price = prices.get("cache_write", prices["input"])
    return (
        (plain * prices["input"] + write * write_price + usage["cached_tokens"] * prices["cached_input"])
        * rate_mult
        + usage["output_tokens"] * prices["output"] * out_mult
    ) / 1e6


def usage_totals(steps: list[dict], prices: dict | None = None) -> dict:
    calls = [step for step in steps if "usage" in step]
    totals = {
        key: sum(step["usage"][key] for step in calls)
        for key in (
            "input_tokens",
            "cached_tokens",
            "cache_write_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    totals["api_calls"] = len(calls)
    totals["tool_calls"] = sum(len(step["tool_calls"]) for step in calls)
    totals["max_context_tokens"] = max((s["usage"]["input_tokens"] for s in calls), default=0)
    totals["cache_hit_fraction"] = (
        round(totals["cached_tokens"] / totals["input_tokens"], 4) if totals["input_tokens"] else None
    )
    if prices and calls:
        totals["cost_usd_estimated"] = round(sum(call_cost(c["usage"], prices) for c in calls), 6)
    return totals


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_usage_summary(output_dir: Path, prices: dict | None = None) -> dict:
    """Aggregate per-step logs and reconcile them with the gateway call log."""
    trajectories = output_dir / "trajectories"
    gateway = _read_jsonl(output_dir / "gateway_calls.jsonl")
    per_instance: dict[str, dict] = {}
    for path in sorted(trajectories.glob("*.steps.jsonl")):
        instance_id = path.name[: -len(".steps.jsonl")]
        per_instance[instance_id] = usage_totals(_read_jsonl(path), prices)
    for call in gateway:
        row = per_instance.setdefault(call.get("instance_id") or "unattributed", {})
        row["gateway_calls"] = row.get("gateway_calls", 0) + 1
        retries = max(len(call.get("attempts", [])) - 1, 0)
        row["gateway_retries"] = row.get("gateway_retries", 0) + retries
        row["gateway_failed_calls"] = row.get("gateway_failed_calls", 0) + (
            0 if _int(call.get("status")) < 400 and call.get("status") else 1
        )
        usage = (call.get("response") or {}).get("usage")
        if usage:
            usage_row = _usage_row(usage)
            row["gateway_input_tokens"] = row.get("gateway_input_tokens", 0) + usage_row["input_tokens"]
            row["gateway_output_tokens"] = row.get("gateway_output_tokens", 0) + usage_row["output_tokens"]
            row["gateway_cached_tokens"] = row.get("gateway_cached_tokens", 0) + usage_row["cached_tokens"]
        row["gateway_latency_s"] = round(row.get("gateway_latency_s", 0) + (call.get("latency_s") or 0), 3)
    keys = (
        "api_calls", "tool_calls", "input_tokens", "cached_tokens", "cache_write_tokens",
        "output_tokens", "reasoning_tokens", "total_tokens", "cost_usd_estimated",
        "gateway_calls", "gateway_retries", "gateway_failed_calls",
        "gateway_input_tokens", "gateway_output_tokens", "gateway_cached_tokens",
    )
    observed: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for path in trajectories.glob("*.steps.jsonl"):
        for step in _read_jsonl(path):
            if "usage" in step:
                effort = json.dumps(step.get("reasoning_setting"), sort_keys=True)
                observed[effort] = observed.get(effort, 0) + 1
                tier = str(step.get("service_tier"))
                tiers[tier] = tiers.get(tier, 0) + 1
    summary = {
        "reasoning_setting_observed_calls": observed,
        "service_tier_observed_calls": tiers,
        "prices_usd_per_million": prices,
        "instances": len(per_instance),
        "totals": {
            key: round(sum(row.get(key, 0) for row in per_instance.values()), 6)
            for key in keys
            if key != "cost_usd_estimated" or prices
        },
        "per_instance": per_instance,
        "note": (
            "gateway_* counts every upstream call incl. retries and calls missing from "
            "the trajectory; a gap against trajectory tokens is spend the agent log omits."
        ),
    }
    base._atomic_json(output_dir / "usage_summary.json", summary)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["instance_id", *keys], extrasaction="ignore")
    writer.writeheader()
    for instance_id, row in per_instance.items():
        writer.writerow({"instance_id": instance_id, **row})
    base._atomic_write(output_dir / "usage_per_instance.csv", stream.getvalue())
    return summary


# --------------------------------------------------------------------------- #
# Single-instance runner (drop-in for offline_codex_pilot._run_one)
# --------------------------------------------------------------------------- #
class Settings:
    """Run-wide options, set once by ``main`` before any instance starts."""

    api_base: str | None = None
    agent_key: str | None = None  # key placed in the agent env
    secret: str | None = None  # real key, redacted from every saved artifact
    network_policy = "model-only"
    model_class: str | None = "litellm_response"
    prices: dict | None = None  # USD per 1M tokens: input, cached_input, output
    config_path: str | None = None
    command_timeout = COMMAND_TIMEOUT
    cost_limit = 0.0
    hidden_paths: list[str] = []
    runtime_dir: Path | None = None  # root; one private subdir per instance
    wave_ids: tuple[str, ...] = ()
    template_path: Path | None = None


def _agent_env(config_dir: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not re.search(r"(API_KEY|TOKEN|SECRET|PASSWORD)", key, re.I)
    }
    env.update(
        {
            "MSWEA_GLOBAL_CONFIG_DIR": str(config_dir),
            "MSWEA_CONFIGURED": "true",
            "MSWEA_SILENT_STARTUP": "1",
            # New models are missing from LiteLLM's price table; recompute cost
            # from token usage instead of letting mini abort.
            "MSWEA_COST_TRACKING": "ignore_errors",
            # Do not let LiteLLM try to download its price map at startup.
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        }
    )
    if Settings.api_base:
        # The gateway is on loopback; a proxy would route around it and be
        # denied by the sandbox.
        for key in [k for k in env if k.lower().endswith("_proxy")]:
            del env[key]
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    if Settings.agent_key:
        env["OPENAI_API_KEY"] = Settings.agent_key
    return env


def _is_quota_failure(output_dir: Path, prediction: dict) -> bool:
    error = str(prediction.get("error") or "")
    if not (error.startswith("mini_exit_") or error == "no_trajectory"):
        return False
    # mini died before its first model call (bad config, missing file, ...):
    # a harness problem, never a model outcome.
    if not (prediction.get("metrics") or {}).get("api_calls"):
        return True
    stem = output_dir / "trajectories" / prediction["instance_id"]
    # Only mini's own stderr and the tail of stdout: the full trajectory holds
    # tool output that can legitimately mention these words.
    text = ""
    for suffix, tail in ((".stderr.log", None), (".stdout.log", -3000)):
        path = Path(f"{stem}{suffix}")
        if path.exists():
            content = path.read_text(errors="replace").lower()
            text += content if tail is None else content[tail:]
    return any(marker in text for marker in _QUOTA_MARKERS)


def _archive_quota_trajectory(output_dir: Path, instance_id: str) -> None:
    parent = output_dir / "quota_attempt_archive" / instance_id
    parent.mkdir(parents=True, exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix="attempt_", dir=parent))
    for suffix in (".traj.json", ".stdout.log", ".stderr.log", ".command.json"):
        source = output_dir / "trajectories" / f"{instance_id}{suffix}"
        if source.exists():
            shutil.move(str(source), archive / source.name)


def _runtime_dir(instance_id: str) -> Path:
    return Settings.runtime_dir / f"inst_{instance_id}"


def run_one(
    instance: dict,
    repo_dir: Path,
    output_dir: Path,
    model: str,
    timeout: int,
    effort: str | None = None,
) -> tuple[dict, dict]:
    instance_id = instance["instance_id"]
    trajectories = output_dir / "trajectories"
    traj_path = trajectories / f"{instance_id}.traj.json"
    stdout_path = trajectories / f"{instance_id}.stdout.log"
    stderr_path = trajectories / f"{instance_id}.stderr.log"
    command_path = trajectories / f"{instance_id}.command.json"
    runtime_dir = _runtime_dir(instance_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_traj = runtime_dir / "trajectory.json"
    # Concurrent agents share the checkout root and the runtime root. The
    # sandbox lets a process read whatever is not hidden, so hide the other
    # agents' checkouts and live trajectories from this one.
    siblings = [
        str(path.resolve())
        for path in repo_dir.parent.iterdir()
        if path.resolve() != repo_dir.resolve()
    ] + [
        str(_runtime_dir(other).resolve())
        for other in Settings.wave_ids
        if other != instance_id and _runtime_dir(other).exists()
    ]

    prompt = build_pilot_prompt(instance)
    command = _command(
        executable=_mini_swe_agent_bin(),
        repo_dir=repo_dir,
        prompt=prompt,
        trajectory_path=runtime_traj,
        model_name=model,
        config_path=Settings.config_path,
        command_timeout=Settings.command_timeout,
        cost_limit=Settings.cost_limit,
        api_base=Settings.api_base,
    )
    if Settings.model_class:
        command += ["--model-class", Settings.model_class]
    if Settings.template_path:
        command += ["--config", str(Settings.template_path)]
    command += [
        "--config",
        "model.model_kwargs.extra_headers="
        + json.dumps({INSTANCE_HEADER: instance_id}),
    ]
    if effort is not None:
        # The Responses API takes a nested ``reasoning`` object.
        key, value = (
            ("reasoning", {"effort": effort})
            if Settings.model_class == "litellm_response"
            else ("reasoning_effort", effort)
        )
        command += ["--config", f"model.model_kwargs.{key}={json.dumps(value)}"]
    command_path.write_text(
        json.dumps([c if c != prompt else "<prompt>" for c in command], indent=2) + "\n"
    )
    command = guard_command(
        command,
        policy=Settings.network_policy,
        endpoint=Settings.api_base,
        hidden_paths=[*Settings.hidden_paths, *siblings]
        if Settings.network_policy == "model-only"
        else [],
    )

    started = time.perf_counter()
    stdout = stderr = ""
    error: str | None = None
    exit_code: int | None = None
    try:
        result = subprocess.run(
            command,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_agent_env(runtime_dir),
        )
        stdout, stderr, exit_code = result.stdout or "", result.stderr or "", result.returncode
        if exit_code:
            error = f"mini_exit_{exit_code}"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        error = "timeout"
    except OSError as exc:
        stderr = f"{type(exc).__name__}: {exc}\n"
        error = "process_error"

    stdout_path.write_text(_redact(stdout, Settings.secret))
    stderr_path.write_text(_redact(stderr, Settings.secret))
    trajectory = _load_trajectory(runtime_traj, Settings.secret)
    if not trajectory:
        error = error or "no_trajectory"
        trajectory = {
            "info": {
                "mini_version": _installed_mini_version(),
                "harness_error": _redact(error, Settings.secret),
            },
            "messages": [],
            "trajectory_format": "swebench-mini-swe-agent-error-1",
        }
    traj_path.write_text(json.dumps(trajectory, indent=2))
    steps = build_step_log(trajectory)
    steps_path = trajectories / f"{instance_id}.steps.jsonl"
    steps_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in steps))
    shutil.rmtree(runtime_dir, ignore_errors=True)
    trajectory_hash = hashlib.sha256(traj_path.read_bytes()).hexdigest()

    findings = audit_trajectory(trajectory)
    scratch_paths = _untracked_root_scratch_paths(repo_dir) | _untracked_scratch_noise_paths(repo_dir)
    patch = _repair_patch(
        _clean_patch(
            _strip_build_artifact_diff_blocks(
                _capture_patch(repo_dir), scratch_paths=scratch_paths
            )
        )
    )
    changed_paths, disallowed_paths = audit_patch_paths(repo_dir, scratch_paths=scratch_paths)
    metrics = _trajectory_metrics(trajectory)
    # Cost tracking is off (model missing from LiteLLM's price table), so mini's
    # 0.0 is not a real cost; use cost_usd_estimated when prices are given.
    metrics.pop("cost_usd", None)
    totals = usage_totals(steps, Settings.prices)
    if totals["api_calls"]:
        metrics.update(
            {
                "api_calls": totals["api_calls"],
                "turns": totals["api_calls"],
                "api_calls_exact_available": True,
                "tool_calls": totals["tool_calls"],
                "input_tokens": totals["input_tokens"],
                "output_tokens": totals["output_tokens"],
                "cache_read_input_tokens": totals["cached_tokens"],
                "cache_creation_input_tokens": totals["cache_write_tokens"],
                "reasoning_output_tokens": totals["reasoning_tokens"],
                "total_tokens": totals["total_tokens"],
                "max_context_tokens": totals["max_context_tokens"],
                "cache_hit_fraction": totals["cache_hit_fraction"],
            }
        )
        if "cost_usd_estimated" in totals:
            metrics["cost_usd_estimated"] = totals["cost_usd_estimated"]
    metrics = with_wall_time(metrics, time.perf_counter() - started)

    stripped_disallowed_paths: list[str] = []
    if findings:
        error = "attempted_network"
    elif disallowed_paths:
        remaining = _repair_patch(
            _clean_patch(
                _strip_build_artifact_diff_blocks(patch, scratch_paths=set(disallowed_paths))
            )
        )
        if remaining.strip():
            patch = remaining
            stripped_disallowed_paths = list(disallowed_paths)
        else:
            error = "disallowed_patch_scope"
    # Same rule as the codex runner: errors other than timeout clear the patch
    # but keep it, unscored, in ``discarded_patch``.
    discarded_patch = ""
    if error and error != "timeout":
        discarded_patch, patch = patch, ""

    audit = {
        "status": "failed" if error else "passed",
        "network_isolation": (
            "loopback_gateway_only"
            if Settings.network_policy == "model-only"
            else "unrestricted_debug"
        ),
        "network_findings": [finding.as_dict() for finding in findings],
        "changed_paths": changed_paths,
        "disallowed_paths": disallowed_paths,
        **(
            {"stripped_disallowed_paths": stripped_disallowed_paths}
            if stripped_disallowed_paths
            else {}
        ),
        "trajectory_path": str(traj_path.relative_to(output_dir)),
        "trajectory_sha256": trajectory_hash,
        "steps_path": str(steps_path.relative_to(output_dir)),
        "manual_review": "pending",
    }
    record = {
        "instance_id": instance_id,
        "model_patch": patch,
        "model_name_or_path": model,
        "agent_backend": AGENT_BACKEND,
        "eval_mode": EVAL_MODE,
        "inference_input_hash": inference_input_hash(instance),
        "offline_audit": audit,
        "trajectory_sha256": trajectory_hash,
        "metrics": metrics,
    }
    if error:
        record["error"] = error
    if discarded_patch:
        record["discarded_patch"] = discarded_patch
    return record, {"instance_id": instance_id, **audit, "exit_code": exit_code}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _run_wave(wave: list[dict], *args: Any, **kwargs: Any) -> Any:
    """Prepare private runtime dirs for the whole wave, then run it."""
    Settings.wave_ids = tuple(item["instance_id"] for item in wave)
    for instance_id in Settings.wave_ids:
        shutil.rmtree(_runtime_dir(instance_id), ignore_errors=True)
        _runtime_dir(instance_id).mkdir(parents=True)
    try:
        yield from _ORIGINAL_RUN_WAVE(wave, *args, run_one=run_one, **kwargs)
    finally:
        for instance_id in Settings.wave_ids:
            shutil.rmtree(_runtime_dir(instance_id), ignore_errors=True)
        Settings.wave_ids = ()


_ORIGINAL_RUN_WAVE = base._run_wave
_ORIGINAL_REBUILD = base._rebuild_outputs


def _rebuild_outputs(output_dir: Path, *args: Any, **kwargs: Any) -> None:
    _ORIGINAL_REBUILD(output_dir, *args, **kwargs)
    path = output_dir / "offline_audit.json"
    audit = json.loads(path.read_text())
    audit["agent_backend"] = AGENT_BACKEND
    audit["tool_network"] = (
        "loopback_gateway_only"
        if Settings.network_policy == "model-only"
        else "unrestricted_debug"
    )
    base._atomic_json(path, audit)


@contextmanager
def _mini_backend() -> Iterator[None]:
    """Point the shared codex runner at mini for the duration of a run."""
    patches = {
        "_run_wave": _run_wave,
        "_rebuild_outputs": _rebuild_outputs,
        "_is_quota_failure": _is_quota_failure,
        "_archive_quota_trajectory": _archive_quota_trajectory,
    }
    saved = {name: getattr(base, name) for name in patches}
    for name, value in patches.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(base, name, value)


# mini's stock template tells the agent to edit source files to fix the issue,
# which contradicts the test-generation task, so only that workflow is swapped.
_TEMPLATE_EDITS = (
    ("Please solve this issue: {{task}}", "Complete the following task: {{task}}"),
    (
        "You can execute bash commands and edit files to implement the necessary changes.",
        "You can execute bash commands and edit files to carry out the task.",
    ),
    (
        "2. Create a script to reproduce the issue\n"
        "3. Edit the source code to resolve the issue\n"
        "4. Verify your fix works by running your script again\n"
        "5. Test edge cases to ensure your fix is robust\n"
        "6. Submit your changes",
        "2. Write the regression test described in the task\n"
        "3. Run the test to check it behaves as the task requires; do not change non-test source files\n"
        "4. Remove scratch files so only the final test files remain\n"
        "5. Submit your changes",
    ),
)


def write_template_override(path: Path) -> str:
    """Render mini's instance template with the test-generation workflow."""
    import importlib.util

    import yaml

    # Locate the package without importing it: its import loads a global dotenv.
    spec = importlib.util.find_spec("minisweagent")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("mini-swe-agent is not importable from this Python")
    config = Path(next(iter(spec.submodule_search_locations))) / "config" / "mini.yaml"
    stock = yaml.safe_load(config.read_text())["agent"]["instance_template"]
    template = stock
    for old, new in _TEMPLATE_EDITS:
        if old not in template:
            raise SystemExit(
                "mini-swe-agent's template changed; update _TEMPLATE_EDITS "
                f"(missing: {old[:50]!r})"
            )
        template = template.replace(old, new, 1)
    path.write_text(json.dumps({"agent": {"instance_template": template}}, indent=2))
    return hashlib.sha256(template.encode()).hexdigest()


def _read_env_key(path: Path, name: str) -> str | None:
    """Return one variable from a dotenv file without exporting the rest."""
    if not path.is_file():
        return None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            return value or None
    return None


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", type=Path, required=True)
    parser.add_argument("--instances", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True, help="LiteLLM model, e.g. openai/gpt-5")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default=None)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--command-timeout", type=int, default=COMMAND_TIMEOUT)
    parser.add_argument("--cost-limit", type=float, default=0, help="USD per instance; 0 disables")
    parser.add_argument(
        "--model-class",
        default="litellm_response",
        help="mini model class; litellm_response = OpenAI Responses API, "
        "'litellm' = chat completions ('' keeps mini's default)",
    )
    for flag, label in (
        ("--price-input", "uncached input"),
        ("--price-cached-input", "cached input"),
        ("--price-output", "output (incl. reasoning)"),
    ):
        parser.add_argument(
            flag, type=float, default=None, help=f"USD per 1M {label} tokens (these three go together)"
        )
    parser.add_argument(
        "--price-cache-write", type=float, default=None,
        help="USD per 1M cache-write tokens (defaults to --price-input)",
    )
    parser.add_argument("--mini-config", default=None, help="extra mini-swe-agent YAML config")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--wave-size", type=int, default=3)
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument(
        "--network-policy", choices=["model-only", "unrestricted"], default="model-only"
    )
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="dotenv file read for the API key only if it is not in the environment",
    )
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM, help="OpenAI-compatible base URL")
    parser.add_argument(
        "--limit", type=int, default=None, help="run only the first N instances (pilot)"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--review-all", action="store_true")
    parser.add_argument("--finalize-reviews", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.timeout <= 0 or args.command_timeout <= 0:
        raise SystemExit("timeouts must be positive")
    if args.cost_limit < 0:
        raise SystemExit("--cost-limit cannot be negative")
    if args.workers < 1 or args.wave_size < 1:
        raise SystemExit("workers and wave-size must be >= 1")
    prices = [args.price_input, args.price_cached_input, args.price_output]
    if any(p is not None for p in prices) and not all(p is not None for p in prices):
        raise SystemExit("give all of --price-input/--price-cached-input/--price-output or none")
    Settings.prices = (
        {
            **dict(zip(("input", "cached_input", "output"), prices)),
            **({"cache_write": args.price_cache_write} if args.price_cache_write is not None else {}),
        }
        if prices[0] is not None
        else None
    )
    if args.mini_config and not Path(args.mini_config).expanduser().is_file():
        raise SystemExit(f"mini config not found: {args.mini_config}")
    if args.resume and args.dry_run:
        raise SystemExit("--resume and --dry-run cannot be combined")
    if args.finalize_reviews and not (args.resume and args.review_all):
        raise SystemExit("--finalize-reviews requires --resume and --review-all")

    instances = base.select_full_instances(args.excel, args.instances)
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be >= 1")
        instances = instances[: args.limit]
    manifest = base._manifest_config(
        excel_path=args.excel,
        instance_paths=args.instances,
        instances=instances,
        model=args.model,
        timeout=args.timeout,
        workers=args.workers,
        wave_size=args.wave_size,
        review_all=args.review_all,
        effort=args.effort,
    )
    manifest.update(
        {
            "agent_backend": AGENT_BACKEND,
            "mini_swe_agent_version": _installed_mini_version(),
            "network_policy": args.network_policy,
            "command_timeout_seconds": args.command_timeout,
            "cost_limit_usd": args.cost_limit,
            "limit": args.limit,
            "effort_requested": args.effort,
            "effort_note": (
                "not set: API default; the effort actually applied is recorded per call "
                "in steps.jsonl (reasoning_setting) and totalled in usage_summary.json"
                if args.effort is None
                else "set explicitly via model_kwargs"
            ),
            "model_class": args.model_class or None,
            "prices_usd_per_million": Settings.prices,
            "mini_config_sha256": (
                base._file_hash(Path(args.mini_config).expanduser())
                if args.mini_config
                else None
            ),
        }
    )
    if args.dry_run:
        print(json.dumps({**manifest, "pending_count": len(instances)}, indent=2))
        return 0

    if not shutil.which(_mini_swe_agent_bin()) and not Path(_mini_swe_agent_bin()).is_file():
        raise SystemExit("mini-swe-agent not found; run `uv pip install mini-swe-agent`")
    api_key = os.environ.get(args.api_key_env) or _read_env_key(
        args.env_file, args.api_key_env
    )
    if not api_key:
        raise SystemExit(f"${args.api_key_env} is not set")

    args.output_dir.parent.mkdir(parents=True, exist_ok=True)
    Settings.network_policy = args.network_policy
    Settings.config_path = args.mini_config
    Settings.model_class = args.model_class or None
    Settings.command_timeout = args.command_timeout
    Settings.cost_limit = args.cost_limit
    Settings.secret = api_key
    Settings.runtime_dir = inference_worktree_root("mini-offline-config")
    template_dir = Path(tempfile.mkdtemp(prefix="template_", dir=Settings.runtime_dir))
    Settings.template_path = template_dir / "testgen_template.yaml"
    manifest["mini_instance_template_sha256"] = write_template_override(Settings.template_path)
    if args.network_policy == "model-only":
        # Computed before any checkout exists so the agent's own repo is not hidden.
        Settings.hidden_paths = inference_hidden_paths(args.output_dir.parent / "_")
        Settings.agent_key = DUMMY_KEY
    else:
        Settings.hidden_paths = []
        Settings.agent_key = api_key

    try:
        with _mini_backend():
            if args.network_policy == "model-only":
                gateway_log = args.output_dir / "gateway_calls.jsonl"
                with LoopbackGateway(args.upstream, api_key, gateway_log) as gateway:
                    Settings.api_base = gateway.base_url
                    validate_network_policy("model-only", gateway.base_url, Settings.hidden_paths)
                    _run(args, instances, manifest)
            else:
                Settings.api_base = None
                _run(args, instances, manifest)
    except base.QuotaLimitStop as exc:
        message = str(exc).replace(
            "Codex usage limit hit",
            "Infrastructure failure (quota, connectivity or mini failed to start)",
        )
        raise SystemExit(f"{message}; fix it, then rerun with --resume")
    finally:
        shutil.rmtree(template_dir, ignore_errors=True)
        if (args.output_dir / "trajectories").is_dir():
            write_usage_summary(args.output_dir, Settings.prices)
    return 0


def _run(args: argparse.Namespace, instances: list[dict], manifest: dict) -> None:
    base.run_full(
        instances,
        args.output_dir,
        manifest=manifest,
        resume=args.resume,
        review_all=args.review_all,
        finalize_reviews=args.finalize_reviews,
        model=args.model,
        timeout=args.timeout,
        workers=args.workers,
        wave_size=args.wave_size,
        github_token=args.github_token,
        effort=args.effort,
    )


if __name__ == "__main__":
    raise SystemExit(main())
