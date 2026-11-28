#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Проверка AMQP снаружи контейнера: TCP + handshake RabbitMQ 0-9-1."""

import argparse
import socket
import sys

# Первый кадр, который сервер обязан прислать после protocol header.
PROTOCOL_HEADER = b"AMQP\x00\x00\x09\x01"
START_PREFIX = b"\x00\x0a\x00\x0a"  # class 10 (connection), method 10 (start)


def validate_start_frame(data: bytes) -> None:
    """Убедиться, что первый ответ сервера — Connection.Start."""
    if len(data) < 11:
        raise RuntimeError("слишком короткий ответ сервера")
    if data[0] != 0x01:
        raise RuntimeError(f"ожидался method frame, получен тип 0x{data[0]:02x}")
    if int.from_bytes(data[3:7], "big") < 4:
        raise RuntimeError("пустой method frame")
    if data[7:11] != START_PREFIX:
        raise RuntimeError("первый кадр не Connection.Start")


def check(host: str, port: int = 5672, timeout: float = 5.0) -> None:
    """Подключиться к host:port и дождаться Connection.Start."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(PROTOCOL_HEADER)
        chunks: list[bytes] = []
        while sum(len(chunk) for chunk in chunks) < 11:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    validate_start_frame(b"".join(chunks))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", nargs="?", default="localhost")
    parser.add_argument("port", nargs="?", type=int, default=5672)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    try:
        check(args.host, args.port, args.timeout)
    except (OSError, RuntimeError) as exc:
        print(f"✗ AMQP {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    print(f"✓ AMQP {args.host}:{args.port}: Connection.Start получен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
