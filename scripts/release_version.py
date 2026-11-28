#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Расчёт следующей версии релиза по тегам и коммитам (только stdlib).

Формат тегов: vX.Y или vX.Y.Z. При bumpe patch к v1.4 получается v1.4.1,
при minor — v1.5, при major — v2.0. ``auto`` смотрит коммиты после
последнего тега: BREAKING/``feat!`` → major, ``feat:`` → minor, иначе patch.
"""

import argparse
import re
import subprocess
import sys

TAG_RE = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?$")
BREAKING_RE = re.compile(
    r"^(?:feat|fix|perf|refactor|build|chore)(?:\([^)]+\))?!:|\bBREAKING CHANGE\b",
    re.IGNORECASE,
)
FEAT_RE = re.compile(r"^feat(?:\([^)]+\))?:", re.IGNORECASE)
BUMPS = ("auto", "patch", "minor", "major")


def parse_tag(tag):
    """Вернуть (major, minor, patch) или None для постороннего тега."""
    match = TAG_RE.match(str(tag).strip())
    if not match:
        return None
    return tuple(int(match.group(group) or 0) for group in (1, 2, 3))


def format_version(parts):
    """v1.5.0 печатается как v1.5 — сохраняем принятый в проекте стиль."""
    major, minor, patch = parts
    if patch == 0:
        return f"v{major}.{minor}"
    return f"v{major}.{minor}.{patch}"


def bump_version(tag, bump):
    """Поднять версию; tag должен быть корректным тегом вида vX.Y[.Z]."""
    parts = parse_tag(tag)
    if parts is None:
        raise ValueError(f"некорректный тег: {tag!r}")
    major, minor, patch = parts
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    if bump == "patch":
        return (major, minor, patch + 1)
    raise ValueError(f"неизвестный тип бампа: {bump!r}")


def decide_bump(subjects, bump="auto"):
    """Выбрать тип бампа по темам коммитов или явному значению."""
    if bump != "auto":
        if bump not in BUMPS[1:]:
            raise ValueError(f"неизвестный тип бампа: {bump!r}")
        return bump
    if any(BREAKING_RE.search(subject) for subject in subjects):
        return "major"
    if any(FEAT_RE.match(subject) for subject in subjects):
        return "minor"
    return "patch"


def git(*args):
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def latest_tag():
    """Последний по версии тег vX.Y[.Z] (посторонние теги игнорируются)."""
    for tag in git("tag", "--list", "v*", "--sort=-version:refname").splitlines():
        if parse_tag(tag):
            return tag
    return None


def commits_since(tag):
    """Темы не-merge коммитов после тега (или все, если тегов ещё нет)."""
    revision = f"{tag}..HEAD" if tag else "HEAD"
    output = git("log", "--no-merges", "--format=%s", revision)
    return [line.strip() for line in output.splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bump", choices=BUMPS, default="auto")
    parser.add_argument("--version", help="явная версия (vX.Y[.Z]), перекрывает --bump")
    parser.add_argument("--output", help="файл для key=value (например, $GITHUB_OUTPUT)")
    args = parser.parse_args(argv)

    previous = latest_tag()
    known_tags = set(
        tag for tag in git("tag", "--list").splitlines() if parse_tag(tag)
    )
    subjects = commits_since(previous)

    if args.version:
        version = args.version.strip()
        if not TAG_RE.match(version):
            parser.error(f"некорректная версия: {version!r}, ожидается vX.Y[.Z]")
        bump = "explicit"
    else:
        if not subjects:
            print(
                "Нет новых коммитов с последнего тега — нечего помечать в релиз.",
                file=sys.stderr,
            )
            return 1
        bump = decide_bump(subjects, args.bump)
        version = format_version(bump_version(previous or "v0.0", bump))

    if version in known_tags:
        print(f"Тег {version} уже существует — выберите другую версию.", file=sys.stderr)
        return 1

    print(f"Предыдущий тег: {previous or '(нет)'}")
    print(f"Следующая версия: {version} (тип: {bump})")
    print(f"Коммитов с прошлого тега: {len(subjects)}")
    for subject in subjects[:20]:
        print(f"  - {subject}")
    if len(subjects) > 20:
        print(f"  ... и ещё {len(subjects) - 20}")

    if args.output:
        with open(args.output, "a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
            output.write(f"previous_tag={previous or ''}\n")
            output.write(f"bump={bump}\n")
            output.write(f"commit_count={len(subjects)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
