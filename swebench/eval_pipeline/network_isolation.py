"""Fail-closed network isolation for inference agent processes."""
from __future__ import annotations

import ipaddress
import os
import shlex
import shutil
import socket
import subprocess
import sys
from urllib.parse import urlparse


class NetworkIsolationError(RuntimeError):
    """Raised when the requested inference network boundary is unavailable."""


def _endpoint_addresses(endpoint: str) -> tuple[list[str], int]:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NetworkIsolationError(
            f"model-only network isolation requires an HTTP(S) endpoint, got {endpoint!r}"
        )
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(
            parsed.hostname,
            port,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise NetworkIsolationError(
            f"could not resolve model endpoint {parsed.hostname!r} before isolation"
        ) from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise NetworkIsolationError(
            f"model endpoint {parsed.hostname!r} has no IPv4 address"
        )
    return addresses, port


def _macos_profile(endpoint: str | None) -> str:
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        # DNS may resolve only the endpoint addresses calculated before launch.
        '(allow network-outbound (literal "/private/var/run/mDNSResponder"))',
    ]
    if endpoint:
        addresses, port = _endpoint_addresses(endpoint)
        if not all(ipaddress.ip_address(address).is_loopback for address in addresses):
            raise NetworkIsolationError(
                "macOS model-only isolation requires a loopback model gateway; "
                "route the remote API through localhost or configure "
                "SWE_BENCH_NETWORK_GUARD"
            )
        lines.append(
            f'(allow network-outbound (remote ip "localhost:{port}"))'
        )
    return "\n".join(lines)


def guard_command(
    command: list[str],
    *,
    policy: str,
    endpoint: str | None = None,
) -> list[str]:
    """Wrap ``command`` in an OS network sandbox.

    ``model-only`` permits only the configured model endpoint. With no endpoint
    it denies all network, which is suitable for builtin-agent shell tools.
    Unsupported platforms fail closed unless a trusted external guard is
    configured through ``SWE_BENCH_NETWORK_GUARD``. The external guard contract
    is: ``guard [--allow-endpoint URL] -- COMMAND ...``.
    """
    if policy == "unrestricted":
        return list(command)
    if policy != "model-only":
        raise ValueError(f"unknown inference network policy: {policy}")

    external_guard = os.environ.get("SWE_BENCH_NETWORK_GUARD")
    if external_guard:
        wrapped = shlex.split(external_guard)
        if endpoint:
            wrapped += ["--allow-endpoint", endpoint]
        return wrapped + ["--", *command]

    sandbox_exec = shutil.which("sandbox-exec")
    if sys.platform == "darwin" and sandbox_exec:
        return [
            sandbox_exec,
            "-p",
            _macos_profile(endpoint),
            *command,
        ]

    bwrap = shutil.which("bwrap")
    if sys.platform.startswith("linux") and bwrap:
        if endpoint:
            addresses, _ = _endpoint_addresses(endpoint)
            if not all(
                ipaddress.ip_address(address).is_loopback for address in addresses
            ):
                raise NetworkIsolationError(
                    "Linux model-only isolation requires a loopback model gateway"
                )
        wrapped = [
            sys.executable,
            "-m",
            "swebench.eval_pipeline.linux_network_guard",
        ]
        if endpoint:
            wrapped += ["--allow-endpoint", endpoint]
        return [*wrapped, "--", *command]

    raise NetworkIsolationError(
        "model-only inference networking is unavailable on this platform; "
        "configure a trusted SWE_BENCH_NETWORK_GUARD or explicitly select "
        "--inference_network_policy unrestricted for non-benchmark debugging"
    )


def validate_network_policy(policy: str, endpoint: str | None = None) -> None:
    """Validate that a requested guard can be constructed before inference."""
    guard_command(["/usr/bin/true"], policy=policy, endpoint=endpoint)


def preflight_anthropic_endpoint(
    endpoint: str,
    *,
    model: str,
    api_key: str | None,
    policy: str,
    timeout: int = 30,
) -> None:
    """Verify a real Messages request through the configured network guard."""
    command = guard_command(
        [
            sys.executable,
            "-m",
            "swebench.eval_pipeline.endpoint_preflight",
            "--endpoint",
            endpoint,
            "--model",
            model,
            "--timeout",
            str(timeout),
        ],
        policy=policy,
        endpoint=endpoint,
    )
    env = dict(os.environ)
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
        env=env,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        if api_key:
            detail = detail.replace(api_key, "<redacted>")
        raise NetworkIsolationError(
            "Anthropic-compatible model endpoint preflight failed"
            + (f": {detail}" if detail else "")
        )


def require_nested_container_guard(policy: str, backend: str) -> None:
    """Reject policies that cannot cover a backend's nested execution layer."""
    if policy == "model-only":
        raise NetworkIsolationError(
            f"{backend} launches tools in a nested container whose egress is not "
            "yet controlled; use a supported host backend for formal runs"
        )
