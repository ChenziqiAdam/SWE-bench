import http.server
import shutil
import socket
import subprocess
import sys
import threading

import pytest

from swebench.eval_pipeline.network_isolation import (
    NetworkIsolationError,
    _find_bubblewrap,
    guard_command,
    preflight_anthropic_endpoint,
    require_nested_container_guard,
)
from swebench.eval_pipeline.linux_network_guard import _copy_bidirectionally


def test_linux_relay_handles_bidirectional_backpressure():
    client, relay_left = socket.socketpair()
    relay_right, server = socket.socketpair()
    payload_to_server = b"a" * (2 * 1024 * 1024)
    payload_to_client = b"b" * (2 * 1024 * 1024)
    received: dict[str, bytes] = {}

    def send_and_close(sock, payload):
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)

    def receive_all(name, sock):
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
        received[name] = b"".join(chunks)

    relay = threading.Thread(
        target=_copy_bidirectionally,
        args=(relay_left, relay_right),
    )
    workers = [
        relay,
        threading.Thread(target=send_and_close, args=(client, payload_to_server)),
        threading.Thread(target=send_and_close, args=(server, payload_to_client)),
        threading.Thread(target=receive_all, args=("client", client)),
        threading.Thread(target=receive_all, args=("server", server)),
    ]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        assert not any(worker.is_alive() for worker in workers)
        assert received["server"] == payload_to_server
        assert received["client"] == payload_to_client
    finally:
        client.close()
        server.close()


def test_external_guard_contract(monkeypatch):
    monkeypatch.setenv("SWE_BENCH_NETWORK_GUARD", "/trusted/guard --strict")
    assert guard_command(
        ["agent", "--run"],
        policy="model-only",
        endpoint="http://127.0.0.1:4000",
    ) == [
        "/trusted/guard",
        "--strict",
        "--allow-endpoint",
        "http://127.0.0.1:4000",
        "--",
        "agent",
        "--run",
    ]


def test_guard_fails_closed_without_supported_boundary(monkeypatch):
    monkeypatch.delenv("SWE_BENCH_NETWORK_GUARD", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(NetworkIsolationError, match="requires Bubblewrap"):
        guard_command(["agent"], policy="model-only")


def test_linux_uses_builtin_bubblewrap_guard(monkeypatch):
    monkeypatch.delenv("SWE_BENCH_NETWORK_GUARD", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/bwrap" if name == "bwrap" else None,
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 4000))],
    )
    command = guard_command(
        ["agent"],
        policy="model-only",
        endpoint="http://127.0.0.1:4000",
    )
    assert command[-4:] == [
        "--allow-endpoint",
        "http://127.0.0.1:4000",
        "--",
        "agent",
    ]
    assert "swebench.eval_pipeline.linux_network_guard" in command


def test_bubblewrap_discovery_checks_fixed_paths_for_nohup(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.os.path.isfile",
        lambda path: path == "/usr/bin/bwrap",
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.os.access",
        lambda path, mode: path == "/usr/bin/bwrap",
    )
    assert _find_bubblewrap() == "/usr/bin/bwrap"


def test_bubblewrap_discovery_accepts_explicit_user_install(monkeypatch):
    monkeypatch.setenv("SWE_BENCH_BWRAP", "/home/researcher/.local/bin/bwrap")
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.os.path.isfile",
        lambda path: path == "/home/researcher/.local/bin/bwrap",
    )
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.os.access",
        lambda path, mode: path == "/home/researcher/.local/bin/bwrap",
    )
    assert _find_bubblewrap() == "/home/researcher/.local/bin/bwrap"


def test_bubblewrap_discovery_rejects_relative_override(monkeypatch):
    monkeypatch.setenv("SWE_BENCH_BWRAP", "bin/bwrap")
    with pytest.raises(NetworkIsolationError, match="absolute executable"):
        _find_bubblewrap()


def test_macos_guard_rejects_direct_public_model_endpoint(monkeypatch):
    monkeypatch.delenv("SWE_BENCH_NETWORK_GUARD", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("203.0.113.10", 443)),
        ],
    )
    with pytest.raises(NetworkIsolationError, match="loopback model gateway"):
        guard_command(
            ["agent"],
            policy="model-only",
            endpoint="https://api.example.test",
        )


def test_nested_container_backend_fails_closed():
    with pytest.raises(NetworkIsolationError, match="nested container"):
        require_nested_container_guard("model-only", "sweagent")
    require_nested_container_guard("unrestricted", "sweagent")


def test_anthropic_preflight_runs_through_guard_and_redacts_key(monkeypatch):
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            2,
            "",
            "proxy rejected secret-key",
        )

    monkeypatch.setenv("SWE_BENCH_NETWORK_GUARD", "/trusted/guard")
    monkeypatch.setattr(
        "swebench.eval_pipeline.network_isolation.subprocess.run",
        fake_run,
    )
    with pytest.raises(NetworkIsolationError, match="<redacted>") as exc:
        preflight_anthropic_endpoint(
            "http://127.0.0.1:4000",
            model="model-alias",
            api_key="secret-key",
            policy="model-only",
        )

    assert "secret-key" not in str(exc.value)
    assert observed["command"][:4] == [
        "/trusted/guard",
        "--allow-endpoint",
        "http://127.0.0.1:4000",
        "--",
    ]
    assert observed["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret-key"


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("sandbox-exec"),
    reason="macOS sandbox-exec integration test",
)
def test_macos_guard_allows_only_model_endpoint(monkeypatch):
    monkeypatch.delenv("SWE_BENCH_NETWORK_GUARD", raising=False)
    try:
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            http.server.SimpleHTTPRequestHandler,
        )
    except PermissionError:
        pytest.skip("test runner cannot bind a loopback socket")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    script = f"""\
import socket
import sys

socket.create_connection(("127.0.0.1", {port}), 2).close()
try:
    socket.create_connection(("1.1.1.1", 443), 2)
except OSError:
    sys.exit(0)
sys.exit(9)
"""
    command = guard_command(
        [sys.executable, "-c", script],
        policy="model-only",
        endpoint=f"http://127.0.0.1:{port}",
    )
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    finally:
        server.shutdown()
        server.server_close()
    if "sandbox_apply: Operation not permitted" in result.stderr:
        pytest.skip("outer test sandbox forbids nested sandbox-exec")
    assert result.returncode == 0, result.stderr
