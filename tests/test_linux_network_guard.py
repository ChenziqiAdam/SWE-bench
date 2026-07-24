import socket
import sys
import threading
from pathlib import Path

import pytest

from swebench.eval_pipeline.linux_network_guard import (
    GuardConfigurationError,
    _bubblewrap_command,
    _loopback_target,
    _parse_outer,
    _serve_host_relay,
    _serve_inside_proxy,
)


def test_linux_guard_accepts_only_loopback_endpoint(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.linux_network_guard.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 4000))],
    )
    assert _loopback_target("http://localhost:4000") == ("127.0.0.1", 4000)

    monkeypatch.setattr(
        "swebench.eval_pipeline.linux_network_guard.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("203.0.113.10", 443))],
    )
    with pytest.raises(GuardConfigurationError, match="host-loopback"):
        _loopback_target("https://api.example.test")


def test_linux_guard_contract_parser():
    assert _parse_outer(
        [
            "--allow-endpoint",
            "http://127.0.0.1:4000",
            "--",
            "agent",
            "--run",
        ]
    ) == ("http://127.0.0.1:4000", False, ["agent", "--run"])


def test_bubblewrap_boundary_unshares_network_and_hides_host_sockets(monkeypatch):
    monkeypatch.setattr(
        "swebench.eval_pipeline.linux_network_guard.os.getcwd",
        lambda: "/work/repo",
    )
    command = _bubblewrap_command(
        "/usr/bin/bwrap",
        Path("/tmp/relay"),
        4000,
        ["agent"],
    )
    assert "--unshare-net" in command
    assert command[command.index("--tmpfs") + 1] == "/run"
    assert command.count("--tmpfs") == 2
    assert "--unsetenv" in command
    assert "swebench.eval_pipeline.linux_network_guard" in command
    assert "__main__" not in command
    assert command[-1] == "agent"


def test_fixed_relay_connects_inside_proxy_to_configured_target(tmp_path):
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        upstream.bind(("127.0.0.1", 0))
    except PermissionError:
        upstream.close()
        pytest.skip("test sandbox forbids loopback listeners")
    upstream.listen(1)
    target = upstream.getsockname()

    def echo_once():
        client, _ = upstream.accept()
        with client:
            client.sendall(client.recv(4))

    echo_thread = threading.Thread(target=echo_once, daemon=True)
    echo_thread.start()

    relay_path = tmp_path / "relay"
    relay = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    relay.bind(str(relay_path))
    relay.listen(1)
    stop = threading.Event()
    relay_thread = threading.Thread(
        target=_serve_host_relay,
        args=(relay, target, stop),
        daemon=True,
    )
    relay_thread.start()

    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.bind(("127.0.0.1", 0))
    proxy_port = reservation.getsockname()[1]
    reservation.close()
    script = (
        "import socket;"
        f"s=socket.create_connection(('127.0.0.1',{proxy_port}),2);"
        "s.sendall(b'ping');"
        "assert s.recv(4)==b'ping'"
    )
    try:
        assert (
            _serve_inside_proxy(
                str(relay_path),
                proxy_port,
                [sys.executable, "-c", script],
            )
            == 0
        )
    finally:
        stop.set()
        relay.close()
        upstream.close()
        relay_thread.join(timeout=1)
        echo_thread.join(timeout=1)
