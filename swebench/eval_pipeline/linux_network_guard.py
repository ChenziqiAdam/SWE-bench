"""Linux model-only inference guard using Bubblewrap and a fixed TCP relay.

Contract:
    python -m swebench.eval_pipeline.linux_network_guard \
        [--allow-endpoint URL] -- COMMAND ...
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

_MODULE_NAME = "swebench.eval_pipeline.linux_network_guard"


class GuardConfigurationError(RuntimeError):
    """Raised when a secure Linux guard cannot be constructed."""


def _loopback_target(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise GuardConfigurationError(
            f"--allow-endpoint must be an HTTP(S) URL, got {endpoint!r}"
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
        raise GuardConfigurationError(
            f"cannot resolve model endpoint {parsed.hostname!r}"
        ) from exc
    addresses = sorted({item[4][0] for item in infos})
    if not addresses or not all(
        ipaddress.ip_address(address).is_loopback for address in addresses
    ):
        raise GuardConfigurationError(
            "Linux model-only guard accepts only a host-loopback model endpoint"
        )
    return addresses[0], port


def _copy_bidirectionally(left: socket.socket, right: socket.socket) -> None:
    selector = selectors.DefaultSelector()
    try:
        left.setblocking(False)
        right.setblocking(False)
        selector.register(left, selectors.EVENT_READ, right)
        selector.register(right, selectors.EVENT_READ, left)
        while selector.get_map():
            for key, _ in selector.select():
                source = key.fileobj
                destination = key.data
                try:
                    chunk = source.recv(65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    selector.unregister(source)
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    continue
                destination.sendall(chunk)
    finally:
        selector.close()
        left.close()
        right.close()


def _serve_host_relay(
    listener: socket.socket,
    target: tuple[str, int],
    stop: threading.Event,
) -> None:
    listener.settimeout(0.2)
    while not stop.is_set():
        try:
            client, _ = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            break
        try:
            upstream = socket.create_connection(target, timeout=10)
        except OSError:
            client.close()
            continue
        threading.Thread(
            target=_copy_bidirectionally,
            args=(client, upstream),
            daemon=True,
        ).start()


def _serve_inside_proxy(
    unix_socket: str,
    port: int,
    command: list[str],
) -> int:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(32)
    listener.settimeout(0.2)
    stop = threading.Event()

    def accept_connections() -> None:
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                relay = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                relay.connect(unix_socket)
            except OSError:
                client.close()
                continue
            threading.Thread(
                target=_copy_bidirectionally,
                args=(client, relay),
                daemon=True,
            ).start()

    thread = threading.Thread(target=accept_connections, daemon=True)
    thread.start()
    try:
        return subprocess.run(command).returncode
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=1)


def _bubblewrap_command(
    bwrap: str,
    relay_dir: Path,
    port: int | None,
    command: list[str],
) -> list[str]:
    """Construct the namespace wrapper; the relay directory is the only host IPC."""
    inner = [
        sys.executable,
        "-m",
        _MODULE_NAME,
        "--_inside",
        str(relay_dir / "relay"),
    ]
    inner += [str(port or 0), "--", *command]
    wrapped = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/tmp",
        "--dir",
        str(relay_dir),
        "--bind",
        str(relay_dir),
        str(relay_dir),
        "--chdir",
        os.getcwd(),
    ]
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "SSH_AUTH_SOCK",
    ):
        wrapped += ["--unsetenv", name]
    return [*wrapped, *inner]


def _run_guard(endpoint: str | None, command: list[str]) -> int:
    if sys.platform != "linux":
        raise GuardConfigurationError("the Bubblewrap guard is Linux-only")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise GuardConfigurationError(
            "bubblewrap is required; install the distribution's bubblewrap package"
        )

    target = _loopback_target(endpoint) if endpoint else None
    relay_root = Path(tempfile.mkdtemp(prefix="swebench-network-"))
    relay_path = relay_root / "relay"
    listener = None
    stop = threading.Event()
    relay_thread = None
    try:
        if target:
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(relay_path))
            listener.listen(32)
            relay_thread = threading.Thread(
                target=_serve_host_relay,
                args=(listener, target, stop),
                daemon=True,
            )
            relay_thread.start()
        wrapped = _bubblewrap_command(
            bwrap,
            relay_root,
            target[1] if target else None,
            command,
        )
        return subprocess.run(wrapped).returncode
    finally:
        stop.set()
        if listener:
            listener.close()
        if relay_thread:
            relay_thread.join(timeout=1)
        shutil.rmtree(relay_root, ignore_errors=True)


def _verify_inside(port: int) -> int:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=3).close()
    except OSError as exc:
        print(f"model endpoint is not reachable inside guard: {exc}", file=sys.stderr)
        return 3
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
    except OSError:
        print("Linux model-only guard verification passed")
        return 0
    print("external network remained reachable inside guard", file=sys.stderr)
    return 4


def _parse_outer(argv: list[str]) -> tuple[str | None, bool, list[str]]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-endpoint")
    parser.add_argument("--verify", action="store_true")
    args, command = parser.parse_known_args(argv)
    if command and command[0] == "--":
        command = command[1:]
    if not args.verify and not command:
        parser.error("a command is required after --")
    if args.verify and not args.allow_endpoint:
        parser.error("--verify requires --allow-endpoint")
    return args.allow_endpoint, args.verify, command


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == ["--_inside"]:
        separator = raw.index("--")
        unix_socket = raw[1]
        port = int(raw[2])
        command = raw[separator + 1 :]
        if port:
            return _serve_inside_proxy(unix_socket, port, command)
        return subprocess.run(command).returncode
    if raw[:1] == ["--_verify-inside"]:
        return _verify_inside(int(raw[1]))

    endpoint, verify, command = _parse_outer(raw)
    if verify:
        _, port = _loopback_target(endpoint or "")
        command = [
            sys.executable,
            "-m",
            _MODULE_NAME,
            "--_verify-inside",
            str(port),
        ]
    try:
        return _run_guard(endpoint, command)
    except GuardConfigurationError as exc:
        print(f"Linux model-only guard unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
