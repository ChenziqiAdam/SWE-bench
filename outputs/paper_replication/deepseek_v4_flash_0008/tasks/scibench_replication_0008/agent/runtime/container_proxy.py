#!/usr/bin/env python3
"""Relay one container-loopback port to a mounted Unix socket, then run a command."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading


def copy_bidirectionally(left: socket.socket, right: socket.socket) -> None:
    def copy(source: socket.socket, destination: socket.socket) -> None:
        try:
            while chunk := source.recv(65536):
                destination.sendall(chunk)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    reverse = threading.Thread(target=copy, args=(right, left), daemon=True)
    try:
        reverse.start()
        copy(left, right)
        reverse.join()
    finally:
        left.close()
        right.close()


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        separator = raw.index("--")
        unix_socket = raw[0]
        port = int(raw[1])
        command = raw[separator + 1 :]
    except (ValueError, IndexError):
        print("usage: container_proxy.py SOCKET PORT -- COMMAND ...", file=sys.stderr)
        return 2
    if not command or not 0 < port < 65536:
        print("invalid proxy port or empty command", file=sys.stderr)
        return 2

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
                target=copy_bidirectionally,
                args=(client, relay),
                daemon=True,
            ).start()

    thread = threading.Thread(target=accept_connections, daemon=True)
    thread.start()
    try:
        return subprocess.run(command, check=False).returncode
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
