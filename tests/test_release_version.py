# -*- coding: utf-8 -*-

"""Тесты расчёта версии будущего релиза."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import release_version  # noqa: E402


class ParseTagTest(unittest.TestCase):
    def test_short_tag(self):
        self.assertEqual(release_version.parse_tag("v1.4"), (1, 4, 0))

    def test_full_tag(self):
        self.assertEqual(release_version.parse_tag("v1.4.2"), (1, 4, 2))

    def test_unrelated_tag_is_ignored(self):
        self.assertIsNone(release_version.parse_tag("latest"))


class VersionArithmeticTest(unittest.TestCase):
    def test_patch_keeps_style_and_adds_component(self):
        self.assertEqual(release_version.bump_version("v1.4", "patch"), (1, 4, 1))

    def test_minor_drops_patch(self):
        self.assertEqual(release_version.bump_version("v1.4.2", "minor"), (1, 5, 0))

    def test_major_resets(self):
        self.assertEqual(release_version.bump_version("v1.4", "major"), (2, 0, 0))

    def test_format_matches_project_style(self):
        self.assertEqual(release_version.format_version((1, 5, 0)), "v1.5")
        self.assertEqual(release_version.format_version((1, 4, 1)), "v1.4.1")

    def test_invalid_bump_is_rejected(self):
        with self.assertRaises(ValueError):
            release_version.bump_version("v1.4", "unknown")


class AutoBumpTest(unittest.TestCase):
    def test_feat_means_minor(self):
        self.assertEqual(
            release_version.decide_bump(["fix: старое", "feat: новое"], "auto"),
            "minor",
        )

    def test_fixes_only_mean_patch(self):
        self.assertEqual(
            release_version.decide_bump(["fix: одно", "fix: другое"], "auto"),
            "patch",
        )

    def test_breaking_change_means_major(self):
        self.assertEqual(
            release_version.decide_bump(["fix!: смена контракта"], "auto"),
            "major",
        )

    def test_scoped_feat_and_breaking_body(self):
        self.assertEqual(
            release_version.decide_bump(
                ["feat(api): новое", "_ref: BREAKING CHANGE в теле"], "auto"
            ),
            "major",
        )

    def test_explicit_bump_overrides_commits(self):
        self.assertEqual(
            release_version.decide_bump(["feat: новое"], "patch"), "patch"
        )

    def test_invalid_explicit_bump_is_rejected(self):
        with self.assertRaises(ValueError):
            release_version.decide_bump(["fix: одно"], "major!")


if __name__ == "__main__":
    unittest.main()
