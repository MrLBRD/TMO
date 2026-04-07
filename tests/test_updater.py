"""Tests for core/updater.py — parsing de version et logique de mise à jour."""

from __future__ import annotations

import pytest

from core.updater import is_newer_version, parse_version


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------

class TestParseVersion:
    def test_simple_version(self):
        assert parse_version("1.0.0") == (1, 0, 0)

    def test_version_with_v_prefix_lowercase(self):
        assert parse_version("v1.2.3") == (1, 2, 3)

    def test_version_with_v_prefix_uppercase(self):
        assert parse_version("V2.0.1") == (2, 0, 1)

    def test_two_part_version(self):
        assert parse_version("1.5") == (1, 5)

    def test_single_number(self):
        assert parse_version("3") == (3,)

    def test_empty_string_returns_zero(self):
        assert parse_version("") == (0,)

    def test_non_numeric_string_returns_zero(self):
        assert parse_version("abc") == (0,)

    def test_version_comparison_ordering(self):
        assert parse_version("1.0.0") < parse_version("1.0.1")
        assert parse_version("1.0.1") > parse_version("1.0.0")
        assert parse_version("1.0.0") == parse_version("1.0.0")


# ---------------------------------------------------------------------------
# is_newer_version
# ---------------------------------------------------------------------------

class TestIsNewerVersion:
    def test_patch_bump_is_newer(self):
        assert is_newer_version("1.0.0", "1.0.1") is True

    def test_minor_bump_is_newer(self):
        assert is_newer_version("1.0.0", "1.1.0") is True

    def test_major_bump_is_newer(self):
        assert is_newer_version("1.0.0", "2.0.0") is True

    def test_same_version_is_not_newer(self):
        assert is_newer_version("1.0.0", "1.0.0") is False

    def test_older_is_not_newer(self):
        assert is_newer_version("1.0.1", "1.0.0") is False

    def test_older_minor_is_not_newer(self):
        assert is_newer_version("1.1.0", "1.0.9") is False

    def test_v_prefix_ignored(self):
        assert is_newer_version("v1.0.0", "v1.0.1") is True

    def test_current_app_version(self):
        # v1.1.1 → pas de mise à jour vers v1.1.1
        assert is_newer_version("1.1.1", "1.1.1") is False
        # v1.1.1 → mise à jour vers v1.2.0
        assert is_newer_version("1.1.1", "1.2.0") is True
