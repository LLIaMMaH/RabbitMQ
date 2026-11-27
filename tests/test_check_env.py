# -*- coding: utf-8 -*-

"""Тесты scripts/check_env.py: парсер, транзакционность и envsubst."""

import json
import re
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_env  # noqa: E402

TEMPLATE = ROOT / ".env.template"
DEFINITIONS_TEMPLATE = ROOT / "rabbitmq" / "definitions.template.json"

VALID_KEYS = (
    "ADMIN",
    "MONITORING",
    "STREAM_GAME",
    "VALIDATION_WORKER",
    "MC_GATEWAY",
    "ZABBIX_MONITOR",
    "RABBITMQ_ERLANG_COOKIE",
)


def valid_env_text(**overrides: str) -> str:
    values = {key: "secret_" + key.lower() for key in VALID_KEYS}
    values.update(overrides)
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def env_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def env_keys(text: str) -> list[str]:
    return [line.split("=", 1)[0] for line in env_lines(text)]


def valid_env_like_template() -> str:
    """Шаблон с заполненными значениями, но с исходными комментариями."""
    text = TEMPLATE.read_text(encoding="utf-8")
    for key in VALID_KEYS:
        text = re.sub(
            rf"^{key}=.*$", f"{key}=secret_{key.lower()}", text, flags=re.M
        )
    return text


class ParseEnvValuesTest(unittest.TestCase):
    def test_literals_are_not_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(
                "ADMIN=p$ass! wo\"rd\\test\n"
                "MONITORING='mon $HOME ! space value'\n"
                "STREAM_GAME=\"stream $game ! value\"\n"
                "VALIDATION_WORKER=val#ue with space\n",
                encoding="utf-8",
            )
            values = check_env.parse_env_values(env)

        self.assertEqual(values["ADMIN"], r'p$ass! wo"rd\test')
        self.assertEqual(values["MONITORING"], "mon $HOME ! space value")
        self.assertEqual(values["STREAM_GAME"], "stream $game ! value")
        self.assertEqual(values["VALIDATION_WORKER"], "val#ue with space")

    def test_placeholders_recognised(self):
        for value in ("", "  ", "change_me", "CHANGE_ME", "<secret>"):
            with self.subTest(value=value):
                self.assertTrue(check_env._is_placeholder(value))
        for value in ("secret", "change_me_2", "abc$!"):
            with self.subTest(value=value):
                self.assertFalse(check_env._is_placeholder(value))


class SyncEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.template = self.dir / ".env.template"
        shutil.copyfile(TEMPLATE, self.template)

    def tearDown(self):
        self.tmp.cleanup()

    def write_env(self, text: str, mode: int = 0o600) -> Path:
        env = self.dir / ".env"
        env.write_text(text, encoding="utf-8")
        env.chmod(mode)
        return env

    def backups(self) -> list[Path]:
        return list(self.dir.glob(".env-*"))

    def test_existing_placeholder_blocks_all_writes(self):
        env = self.write_env(valid_env_text(ADMIN="change_me") + "EXTRA=drop\n", mode=0o644)
        before = env.read_bytes()

        report = check_env.sync_env(env, self.template)

        self.assertIn("ADMIN", report["unresolved"])
        self.assertEqual(env.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o644)
        self.assertEqual(self.backups(), [])

    def test_missing_key_blocks_all_writes(self):
        text = valid_env_text()
        text = text.replace("MONITORING=secret_monitoring\n", "")
        env = self.write_env(text + "EXTRA=drop\n", mode=0o644)
        before = env.read_bytes()

        report = check_env.sync_env(env, self.template)

        self.assertIn("MONITORING", report["unresolved"])
        self.assertEqual(env.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o644)
        self.assertEqual(self.backups(), [])

    def test_success_reorders_removes_extra_and_secures_files(self):
        extra = "\n".join(
            f"{key}=secret_{key.lower()}" for key in reversed(VALID_KEYS)
        ) + "\nEXTRA=drop\n"
        env = self.write_env(extra, mode=0o644)

        report = check_env.sync_env(env, self.template)

        self.assertEqual(report["unresolved"], [])
        self.assertIn("EXTRA", report["removed"])
        self.assertEqual(
            env_keys(env.read_text(encoding="utf-8")),
            env_keys(self.template.read_text(encoding="utf-8")),
        )
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        self.assertIn("EXTRA=drop", backups[0].read_text(encoding="utf-8"))

    def test_env_backups_are_rotated_and_private(self):
        for index in range(11):
            backup = self.dir / f".env-20260101-{index:06d}"
            backup.write_text("old", encoding="utf-8")
            backup.chmod(0o644)
        extra = "\n".join(
            f"{key}=secret_{key.lower()}" for key in reversed(VALID_KEYS)
        ) + "\nEXTRA=drop\n"
        env = self.write_env(extra, mode=0o644)

        report = check_env.sync_env(env, self.template)

        backups = sorted(self.backups())
        self.assertEqual(len(backups), check_env.ENV_BACKUP_KEEP)
        self.assertEqual(report["backup"], str(backups[-1]))
        self.assertEqual(stat.S_IMODE(backups[-1].stat().st_mode), 0o600)
        self.assertIn("EXTRA=drop", backups[-1].read_text(encoding="utf-8"))

    def test_mode_only_change_does_not_create_backup(self):
        env = self.write_env(valid_env_like_template(), mode=0o644)
        env.chmod(0o644)

        report = check_env.sync_env(env, self.template)

        self.assertTrue(report["mode_changed"])
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
        self.assertEqual(self.backups(), [])


@unittest.skipUnless(shutil.which("envsubst"), "envsubst (gettext-base) не установлен")
class RenderDefinitionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_env(self, text: str) -> Path:
        env = self.dir / ".env"
        env.write_text(text, encoding="utf-8")
        return env

    def test_passwords_with_shell_metacharacters_survive(self):
        expected = {
            "admin": r'p$ass! wo"rd\test',
            "monitoring": "mon $HOME ! space value",
            "stream_game": "stream$game!",
            "validation_worker": "val#ue with space",
            "mc_gateway": 'mc$!gate "q"',
            "zabbix_monitor": "zabbix ! value",
        }
        env = self.write_env(
            valid_env_text(
                ADMIN=expected["admin"],
                MONITORING=f"'{expected['monitoring']}'",
                STREAM_GAME=f"'{expected['stream_game']}'",
                VALIDATION_WORKER=expected["validation_worker"],
                MC_GATEWAY=f"'{expected['mc_gateway']}'",
                ZABBIX_MONITOR=expected["zabbix_monitor"],
            )
        )
        output = self.dir / "definitions.json"

        check_env.render_definitions(DEFINITIONS_TEMPLATE, output, env)

        data = json.loads(output.read_text(encoding="utf-8"))
        actual = {user["name"]: user["password"] for user in data["users"]}
        for name, password in expected.items():
            with self.subTest(user=name):
                self.assertEqual(actual[name], password)

    def test_definitions_file_is_private(self):
        env = self.write_env(valid_env_text())
        output = self.dir / "definitions.json"

        check_env.render_definitions(DEFINITIONS_TEMPLATE, output, env)

        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_placeholder_is_rejected(self):
        env = self.write_env(valid_env_text(ADMIN="change_me"))
        output = self.dir / "definitions.json"

        with self.assertRaises(ValueError):
            check_env.render_definitions(DEFINITIONS_TEMPLATE, output, env)

        self.assertFalse(output.exists())

    def test_unknown_variable_is_rejected(self):
        env = self.write_env(valid_env_text())
        template = self.dir / "bad-template.json"
        template.write_text(
            DEFINITIONS_TEMPLATE.read_text(encoding="utf-8").replace(
                "$ADMIN", "$UNKNOWN_VAR"
            ),
            encoding="utf-8",
        )
        output = self.dir / "definitions.json"

        with self.assertRaises(ValueError):
            check_env.render_definitions(template, output, env)

        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
