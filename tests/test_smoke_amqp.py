# -*- coding: utf-8 -*-

"""Тесты разбора первого кадра AMQP без реального сетевого подключения."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import smoke_amqp  # noqa: E402


def start_frame() -> bytes:
    return b"\x01\x00\x00\x00\x00\x00\x40\x00\x0a\x00\x0a" + b"\x00" * 64


class SmokeAmqpTest(unittest.TestCase):
    def test_valid_start_frame_is_accepted(self):
        smoke_amqp.validate_start_frame(start_frame())

    def test_short_response_is_rejected(self):
        with self.assertRaises(RuntimeError):
            smoke_amqp.validate_start_frame(b"\x01\x00\x00")

    def test_wrong_method_is_rejected(self):
        data = bytearray(start_frame())
        data[10] = 11  # connection.close вместо connection.start

        with self.assertRaises(RuntimeError):
            smoke_amqp.validate_start_frame(bytes(data))

    def test_non_method_frame_is_rejected(self):
        data = bytearray(start_frame())
        data[0] = 2  # heartbeat вместо method frame

        with self.assertRaises(RuntimeError):
            smoke_amqp.validate_start_frame(bytes(data))


if __name__ == "__main__":
    unittest.main()
