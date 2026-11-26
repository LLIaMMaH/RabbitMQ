# -*- coding: utf-8 -*-

"""Сверка .env с .env.template и безопасная генерация definitions.json.

Перестраивает .env в точном порядке .env.template:
- комментарии, секции и порядок строк берутся из шаблона;
- значения переменных — из текущего .env (для недостающих — значения
  по умолчанию из шаблона, если это не плейсхолдер);
- лишние активные переменные удаляются.

Если файл нужно изменить, перед записью создаётся резервная копия
.env-YYYYMMDD-HHMMSS.

Плейсхолдеры шаблона (``change_me``, ``<...>``, пустое значение) в .env
молча не подставляются: недостающий обязательный ключ с таким значением
попадает в отчёт и блокирует запуск — оператор заполняет его вручную.

Значения читаются обычным парсером, а не ``. ./.env``: пароли с ``$``, ``!``,
пробелами и кавычками не исполняются shell и не теряются.

Запуск:
  python3 scripts/check_env.py [ENV_FILE] [ENV_TEMPLATE]
  python3 scripts/check_env.py [ENV_FILE] [ENV_TEMPLATE] \
      --subst DEFINITIONS_TEMPLATE OUTPUT
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
TEMPLATE_FILE = ROOT / ".env.template"

_ASSIGNMENT_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=")
_PLACEHOLDER_IN_TEMPLATE_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")

# Явный список переменных, которые подставляются в definitions.template.json.
# Если в шаблоне появится новый $VAR, генерация упадёт, пока его не добавят
# сюда и в .env.template — так нельзя случайно подставить пустоту.
SUBST_VARS = (
    "ADMIN",
    "MONITORING",
    "STREAM_GAME",
    "VALIDATION_WORKER",
    "MC_GATEWAY",
    "ZABBIX_MONITOR",
)

# Значения-плейсхолдеры из шаблона: их нельзя бездумно подставлять в .env,
# иначе при добавлении нового ключа (например нового пользователя) в .env
# попадёт заглушка вместо реального секрета.
_PLACEHOLDER_BRACKETED_RE = re.compile(r"^<[^=]*>$")
# Точные значения-заглушки, использующиеся в .env.template этого проекта.
_PLACEHOLDER_EXACT = {"change_me"}


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_placeholder(value: str) -> bool:
    """Значение-заглушка из шаблона, которое нельзя вставлять молча.

    ``change_me``, ``<...>`` и пустое значение считаются плейсхолдерами:
    если ключа в .env нет, такое значение не подставляется, а попадает в
    ``unresolved`` — чтобы оператор заполнил его реальным значением вручную.
    """
    value = value.strip()
    return (
        not value
        or _PLACEHOLDER_BRACKETED_RE.match(value) is not None
        or value.lower() in _PLACEHOLDER_EXACT
    )


def _key_of(line: str) -> str | None:
    """Имя переменной из строки вида KEY=value, иначе None."""
    if _is_comment(line):
        return None
    match = _ASSIGNMENT_RE.match(line)
    return match.group(1) if match else None


def _unquote_value(raw: str) -> str:
    """Снять обрамляющие кавычки, не выполняя подстановок.

    Одинарные кавычки — полностью статичное значение. В двойных
    разбираются только ``\\"`` и ``\\\\``; ``$`` и ``!`` остаются как есть.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == "'":
            return inner
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def parse_env_values(env_path: Path) -> dict[str, str]:
    """Прочитать .env в словарь без вызова shell.

    Строки вида ``KEY='a $b'`` и ``KEY="a b"`` возвращаются без кавычек.
    Внутренние комментарии не отрезаются: ``#`` и ``!`` могут быть частью
    пароля. Комментарии распознаются только с начала строки.
    """
    values: dict[str, str] = {}
    for line in _read_lines(env_path):
        key = _key_of(line)
        if key is not None:
            values[key] = _unquote_value(line.split("=", 1)[1])
    return values


def _json_escape(value: str) -> str:
    """Подготовить значение для вставки внутрь кавычек JSON-строки."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_definitions(
    template_path: Path,
    output_path: Path,
    env_path: Path,
) -> None:
    """Сгенерировать definitions.json через envsubst с явным списком переменных.

    Никакого ``set -a; . ./.env``: значения берутся парсером и передаются
    в envsubst через окружение дочернего процесса. envsubst получает
    SHELL-FORMAT со списком SUBST_VARS, поэтому посторонние ``$VAR`` в шаблоне
    не подставляются молча.
    """
    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    template = template_path.read_text(encoding="utf-8")
    used = set(_PLACEHOLDER_IN_TEMPLATE_RE.findall(template))
    unknown = sorted(used - set(SUBST_VARS))
    if unknown:
        raise ValueError(
            "В definitions.template.json есть переменные вне явного списка: "
            + ", ".join(f"${name}" for name in unknown)
        )

    values = parse_env_values(env_path)
    missing = [name for name in SUBST_VARS if name not in values]
    if missing:
        raise ValueError(
            "В .env нет переменных для definitions: " + ", ".join(missing)
        )

    child_env = os.environ.copy()
    child_env.update({name: _json_escape(values[name]) for name in SUBST_VARS})
    shell_format = " ".join(f"${name}" for name in SUBST_VARS)

    try:
        proc = subprocess.run(
            ["envsubst", shell_format],
            input=template,
            text=True,
            capture_output=True,
            env=child_env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("envsubst не найден в PATH") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"envsubst завершился с кодом {proc.returncode}: {proc.stderr.strip()}")

    try:
        json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Сгенерированный JSON некорректен: {exc}") from exc

    output_path.write_text(proc.stdout, encoding="utf-8")


def sync_env(
    env_path: Path,
    template_path: Path,
    *,
    backup: bool = True,
    backup_suffix: str | None = None,
) -> dict[str, list[str] | str | None]:
    """Синхронизировать .env с шаблоном.

    Args:
        env_path: Путь к файлу .env.
        template_path: Путь к файлу .env.template.
        backup: Создавать ли резервную копию перед изменением.
        backup_suffix: Суффикс (дата-время) для имени копии.

    Returns:
        Словарь с отчётом: added, removed, unresolved, backup (путь к копии
        или None). ``unresolved`` — обязательные ключи из шаблона, которых нет
        в .env и чьё шаблонное значение является плейсхолдером: их нельзя
        вставлять, нужно заполнить вручную.

    Raises:
        FileNotFoundError: Если .env или шаблон отсутствуют.
    """
    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")
    if not env_path.is_file():
        raise FileNotFoundError(f"{env_path} not found. Create it from {template_path}")

    env_values: dict[str, str] = {}
    for line in _read_lines(env_path):
        key = _key_of(line)
        if key is not None:
            env_values[key] = line.split("=", 1)[1].strip()

    new_lines: list[str] = []
    added: list[str] = []
    unresolved: list[str] = []
    template_keys: set[str] = set()

    for line in _read_lines(template_path):
        key = _key_of(line)
        if key is None:
            new_lines.append(line)
            continue
        template_keys.add(key)
        if key in env_values:
            new_lines.append(f"{key}={env_values[key]}")
        elif _is_placeholder(line.split("=", 1)[1]):
            # Плейсхолдер не вставляем — пусть оператор укажет реальное значение.
            unresolved.append(key)
        else:
            new_lines.append(line)
            added.append(key)

    removed = [k for k in env_values if k not in template_keys]

    old_content = env_path.read_text(encoding="utf-8")
    new_content = "\n".join(new_lines) + "\n"

    if new_content == old_content:
        return {"added": [], "removed": [], "unresolved": unresolved, "backup": None}

    backup_path: Path | None = None
    if backup:
        timestamp = backup_suffix or datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = Path(str(env_path) + "-" + timestamp)
        backup_path.write_text(old_content, encoding="utf-8")

    env_path.write_text(new_content, encoding="utf-8")

    return {
        "added": added,
        "removed": removed,
        "unresolved": unresolved,
        "backup": str(backup_path) if backup_path else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("env_path", nargs="?", type=Path, default=ENV_FILE)
    parser.add_argument("template_path", nargs="?", type=Path, default=TEMPLATE_FILE)
    parser.add_argument(
        "--subst",
        nargs=2,
        metavar=("DEFINITIONS_TEMPLATE", "OUTPUT"),
        type=Path,
        help="сгенерировать definitions.json через envsubst с явным списком переменных",
    )
    args = parser.parse_args()

    print(f"Проверка {args.env_path.name} относительно {args.template_path.name}...")
    try:
        report = sync_env(args.env_path, args.template_path)
    except FileNotFoundError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1

    added = report["added"]
    removed = report["removed"]
    unresolved = report["unresolved"]
    backup = report["backup"]

    if unresolved:
        print(
            "ВНИМАНИЕ: в .env не заданы обязательные ключи "
            "(в шаблоне только плейсхолдеры):",
            file=sys.stderr,
        )
        for key in unresolved:
            print(f"  - {key} (задайте реальное значение вручную в .env)", file=sys.stderr)
        print("Проверка прервана — заполните значения и повторите.", file=sys.stderr)
        return 1

    if added:
        print(f"Добавлено: {', '.join(added)}")
    if removed:
        print(f"Удалено: {', '.join(removed)}")
    if not added and not removed and backup is None:
        print("Изменений не требуется — файл актуален.")
    elif not added and not removed:
        print("Порядок строк приведён к .env.template.")
    if backup:
        print(f"Резервная копия: {backup}")

    if args.subst:
        template_path, output_path = args.subst
        try:
            render_definitions(template_path, output_path, args.env_path)
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            print(f"Ошибка генерации definitions: {e}", file=sys.stderr)
            return 1
        print(f"Сгенерирован {output_path} через envsubst ({len(SUBST_VARS)} переменных).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
