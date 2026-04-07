"""Tests for core/storage.py — sanitisation, validation, chemins vidéo, formatage."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.storage import (
    MAX_ORDER_ID_LEN,
    MIN_ORDER_ID_LEN,
    build_video_path,
    format_bytes,
    is_valid_order_id,
    sanitize_order_id,
)


# ---------------------------------------------------------------------------
# sanitize_order_id
# ---------------------------------------------------------------------------

class TestSanitizeOrderId:
    def test_normal_id_unchanged(self):
        assert sanitize_order_id("12345") == "12345"

    def test_strips_leading_trailing_whitespace(self):
        assert sanitize_order_id("  12345  ") == "12345"

    def test_replaces_forward_slash(self):
        assert sanitize_order_id("123/45") == "123_45"

    def test_replaces_backslash(self):
        assert sanitize_order_id("123\\45") == "123_45"

    def test_removes_consecutive_special_chars_as_single_underscore(self):
        # "!@#" est une séquence invalide → remplacée par un seul "_"
        assert sanitize_order_id("123!@#45") == "123_45"

    def test_preserves_hyphens(self):
        assert sanitize_order_id("abc-12") == "abc-12"

    def test_preserves_underscores(self):
        assert sanitize_order_id("abc_12") == "abc_12"

    def test_preserves_mixed_case(self):
        assert sanitize_order_id("AbCdE") == "AbCdE"

    def test_empty_string(self):
        assert sanitize_order_id("") == ""

    # --- sécurité : path traversal ---

    def test_path_traversal_dotdot_slash(self):
        result = sanitize_order_id("../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_path_traversal_dotdot_backslash(self):
        result = sanitize_order_id("..\\windows\\system32")
        assert ".." not in result
        assert "\\" not in result

    def test_path_traversal_absolute_unix(self):
        result = sanitize_order_id("/etc/passwd")
        assert "/" not in result

    def test_path_traversal_absolute_windows(self):
        result = sanitize_order_id("C:\\Windows\\System32")
        assert "\\" not in result
        assert ":" not in result

    def test_null_byte_removed(self):
        result = sanitize_order_id("123\x0045")
        assert "\x00" not in result


# ---------------------------------------------------------------------------
# is_valid_order_id
# ---------------------------------------------------------------------------

class TestIsValidOrderId:
    def test_min_length_valid(self):
        assert is_valid_order_id("a" * MIN_ORDER_ID_LEN) is True

    def test_max_length_valid(self):
        assert is_valid_order_id("a" * MAX_ORDER_ID_LEN) is True

    def test_too_short(self):
        assert is_valid_order_id("a" * (MIN_ORDER_ID_LEN - 1)) is False

    def test_too_long(self):
        assert is_valid_order_id("a" * (MAX_ORDER_ID_LEN + 1)) is False

    def test_empty_string_invalid(self):
        assert is_valid_order_id("") is False

    def test_whitespace_only_invalid(self):
        assert is_valid_order_id("     ") is False

    def test_path_traversal_sanitized_to_valid_length(self):
        # "../etc" → replace "/" → ".._etc" → regex ".." → "_" → "__etc" (5 chars = valid)
        # La traversée est neutralisée par sanitize, pas rejetée au niveau longueur
        assert is_valid_order_id("../etc") is True

    def test_typical_woocommerce_id(self):
        assert is_valid_order_id("12345") is True
        assert is_valid_order_id("99999") is True
        assert is_valid_order_id("123456789") is True


# ---------------------------------------------------------------------------
# build_video_path
# ---------------------------------------------------------------------------

class TestBuildVideoPath:
    def test_returns_mp4_extension(self, tmp_path):
        path = build_video_path("12345", output_dir=tmp_path, on_date=date(2026, 4, 7))
        assert path.suffix == ".mp4"

    def test_order_id_in_filename(self, tmp_path):
        path = build_video_path("12345", output_dir=tmp_path, on_date=date(2026, 4, 7))
        assert "12345" in path.name

    def test_date_in_path(self, tmp_path):
        path = build_video_path("12345", output_dir=tmp_path, on_date=date(2026, 4, 7))
        assert "2026" in str(path)
        assert "04" in str(path)
        assert "07" in str(path)

    def test_uses_provided_output_dir(self, tmp_path):
        path = build_video_path("12345", output_dir=tmp_path, on_date=date(2026, 4, 7))
        assert str(tmp_path) in str(path)

    def test_sanitizes_order_id_in_path(self, tmp_path):
        path = build_video_path("../etc", output_dir=tmp_path, on_date=date(2026, 4, 7))
        assert ".." not in path.name
        assert "/" not in path.name

    def test_unique_suffix_when_file_exists(self, tmp_path):
        on_date = date(2026, 4, 7)
        first = build_video_path("12345", output_dir=tmp_path, on_date=on_date)
        first.parent.mkdir(parents=True, exist_ok=True)
        first.touch()
        second = build_video_path("12345", output_dir=tmp_path, on_date=on_date)
        assert first != second
        assert "_1.mp4" in second.name


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------

class TestFormatBytes:
    def test_zero_bytes(self):
        assert format_bytes(0) == "0 o"

    def test_bytes_below_kilo(self):
        assert format_bytes(512) == "512 o"
        assert format_bytes(1023) == "1023 o"

    def test_one_kilobyte(self):
        assert format_bytes(1024) == "1.0 Ko"

    def test_one_and_half_kilobyte(self):
        assert format_bytes(1536) == "1.5 Ko"

    def test_one_megabyte(self):
        assert format_bytes(1024 * 1024) == "1.0 Mo"

    def test_one_gigabyte(self):
        assert format_bytes(1024 ** 3) == "1.0 Go"

    def test_ten_gigabytes(self):
        assert format_bytes(10 * 1024 ** 3) == "10.0 Go"
