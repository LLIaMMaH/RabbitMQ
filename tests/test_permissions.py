# -*- coding: utf-8 -*-

"""Инвариант прав из AGENTS.md: префиксные regex, а не открытые ``.*``.

Отдельная проверка нужна, чтобы не повторить баг с ``\\.*`` (ноль и более
точек) вместо ``\\..*`` (точка + что угодно): ``mc.dlx.3`` должен матчиться,
а ``mc.dlxX`` — нет.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFINITIONS = ROOT / "rabbitmq" / "definitions.template.json"

# Исключения, явно зафиксированные в AGENTS.md / README.md.
FULL_ACCESS = {"admin"}
READ_ONLY_ALL = {"monitoring", "zabbix_monitor"}

VHOSTS = {"/", "/stream-game", "/validation", "/mc-gateway"}
APP_VHOSTS = VHOSTS - {"/"}
# RabbitMQ-Health работает только в прикладных вхостах, Zabbix — во всех.
READ_ONLY_VHOSTS = {
    "monitoring": APP_VHOSTS,
    "zabbix_monitor": VHOSTS,
}


def load_permissions() -> list[dict[str, str]]:
    data = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    return data["permissions"]


class PermissionInvariantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.permissions = load_permissions()

    def pattern(self, user: str, vhost: str, action: str) -> str:
        for perm in self.permissions:
            if perm["user"] == user and perm["vhost"] == vhost:
                return perm[action]
        self.fail(f"нет прав {action} для {user} на {vhost}")

    @staticmethod
    def matches(pattern: str, resource: str) -> bool:
        return re.fullmatch(pattern, resource) is not None

    def test_application_patterns_are_anchored_and_minimal(self):
        for perm in self.permissions:
            if perm["user"] in FULL_ACCESS | READ_ONLY_ALL:
                continue
            with self.subTest(user=perm["user"], vhost=perm["vhost"]):
                for action in ("configure", "read", "write"):
                    pattern = perm[action]
                    self.assertTrue(pattern.startswith("^"), pattern)
                    self.assertTrue(pattern.endswith("$"), pattern)
                    # Точная ошибка из AGENTS.md: \.* вместо \..*
                    self.assertNotIn(r"\.*", pattern, pattern)
                    # Единственное допустимое `.*` — хвост (\..*)?.
                    without_suffix = pattern.replace(r"(\..*)?", "")
                    self.assertNotIn(".*", without_suffix, pattern)

    def test_mc_gateway_dlx_suffix_is_a_dot_then_anything(self):
        for action in ("configure", "read", "write"):
            pattern = self.pattern("mc_gateway", "/mc-gateway", action)
            with self.subTest(action=action):
                for resource in ("mc.dlx.3", "mc.dlx.3.reply", "mc.retry.7",
                                 "mc.gateway.1", "mc.commands.2", "mc.server.9"):
                    self.assertTrue(self.matches(pattern, resource), (pattern, resource))
                for resource in ("mc.dlxX", "mc.dlx3", "mc.dlxX.3",
                                 "mc.gatewayX", "other.dlx.3"):
                    self.assertFalse(self.matches(pattern, resource), (pattern, resource))

    def test_stream_game_dlx_suffix_is_a_dot_then_anything(self):
        for action in ("configure", "read"):
            pattern = self.pattern("stream_game", "/stream-game", action)
            with self.subTest(action=action):
                self.assertTrue(self.matches(pattern, "game.dlx.3"))
                self.assertFalse(self.matches(pattern, "game.dlxX"))

    def test_validation_worker_suffix_is_a_dot_then_anything(self):
        pattern = self.pattern("validation_worker", "/validation", "read")
        for resource in ("validation.tasks.42", "validation.results.7"):
            self.assertTrue(self.matches(pattern, resource), resource)
        for resource in ("validation.tasksX", "validation.resultsX", "validation.other.1"):
            self.assertFalse(self.matches(pattern, resource), resource)

        configure = self.pattern("validation_worker", "/validation", "configure")
        self.assertEqual(configure, "^$")
        self.assertFalse(self.matches(configure, "validation.tasks.1"))

    def test_monitoring_exceptions_are_read_only_on_every_vhost(self):
        for user in sorted(READ_ONLY_ALL):
            actual = {
                perm["vhost"]
                for perm in self.permissions
                if perm["user"] == user
            }
            with self.subTest(user=user):
                self.assertEqual(actual, READ_ONLY_VHOSTS[user])
                for vhost in READ_ONLY_VHOSTS[user]:
                    self.assertEqual(self.pattern(user, vhost, "read"), ".*")
                    self.assertEqual(self.pattern(user, vhost, "configure"), "^$")
                    self.assertEqual(self.pattern(user, vhost, "write"), "^$")

    def test_admin_has_full_access_on_application_vhosts(self):
        for vhost in sorted(APP_VHOSTS):
            with self.subTest(vhost=vhost):
                for action in ("configure", "read", "write"):
                    self.assertEqual(self.pattern("admin", vhost, action), ".*")

    def test_no_application_user_has_open_read(self):
        for perm in self.permissions:
            if perm["user"] in FULL_ACCESS | READ_ONLY_ALL:
                continue
            with self.subTest(user=perm["user"], vhost=perm["vhost"]):
                self.assertNotEqual(perm["read"], ".*")


if __name__ == "__main__":
    unittest.main()
