# -*- coding: utf-8 -*-

"""Плагины заданы декларативно, а не включаются на работающем брокере."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "rabbitmq" / "enabled_plugins"
COMPOSE = ROOT / "docker-compose.yml"
MAKEFILE = ROOT / "Makefile"


class EnabledPluginsTest(unittest.TestCase):
    def test_file_is_valid_erlang_term_with_required_plugins(self):
        text = PLUGINS.read_text(encoding="utf-8")
        term = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("%")
        ).strip()

        self.assertRegex(term, r"^\[[A-Za-z0-9_, ]+\]\.$")
        plugins = {name.strip() for name in term[1:-2].split(",") if name.strip()}
        self.assertIn("rabbitmq_management", plugins)
        self.assertIn("rabbitmq_prometheus", plugins)

    def test_compose_mounts_plugins_file(self):
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn(
            "./rabbitmq/enabled_plugins:/etc/rabbitmq/enabled_plugins:ro",
            compose,
        )

    def test_makefile_does_not_enable_plugins_at_runtime(self):
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertNotIn("rabbitmq-plugins enable", makefile)


if __name__ == "__main__":
    unittest.main()
