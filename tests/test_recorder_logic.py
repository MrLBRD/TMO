"""Tests for core/recorder.py — logique QR sans caméra.

Le Recorder est instancié sans appeler start() : aucune caméra n'est ouverte.
On teste uniquement les méthodes de traitement de données pures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.recorder import Recorder


@pytest.fixture
def recorder(tmp_path: Path) -> Recorder:
    """Recorder sans caméra, utilisé uniquement pour les méthodes de logique."""
    return Recorder(output_dir=tmp_path)


# ---------------------------------------------------------------------------
# _extract_order_id_from_qr_value
# ---------------------------------------------------------------------------

class TestExtractOrderIdFromQrValue:
    def test_valid_qr_returns_id(self, recorder):
        assert recorder._extract_order_id_from_qr_value("tk-12345") == "12345"

    def test_uppercase_prefix_accepted(self, recorder):
        assert recorder._extract_order_id_from_qr_value("TK-12345") == "12345"

    def test_mixed_case_prefix_accepted(self, recorder):
        assert recorder._extract_order_id_from_qr_value("Tk-12345") == "12345"

    def test_min_length_id_valid(self, recorder):
        # 5 caractères = longueur minimale
        result = recorder._extract_order_id_from_qr_value("tk-12345")
        assert result == "12345"

    def test_max_length_id_valid(self, recorder):
        # 10 caractères = longueur maximale
        result = recorder._extract_order_id_from_qr_value("tk-1234567890")
        assert result == "1234567890"

    def test_id_too_short_returns_none(self, recorder):
        # "1234" = 4 chars < min 5
        assert recorder._extract_order_id_from_qr_value("tk-1234") is None

    def test_id_too_long_returns_none(self, recorder):
        # "12345678901" = 11 chars > max 10
        assert recorder._extract_order_id_from_qr_value("tk-12345678901") is None

    def test_no_prefix_returns_none(self, recorder):
        assert recorder._extract_order_id_from_qr_value("12345") is None

    def test_wrong_prefix_returns_none(self, recorder):
        assert recorder._extract_order_id_from_qr_value("qr-12345") is None

    def test_empty_string_returns_none(self, recorder):
        assert recorder._extract_order_id_from_qr_value("") is None

    def test_whitespace_only_returns_none(self, recorder):
        assert recorder._extract_order_id_from_qr_value("   ") is None

    def test_strips_surrounding_whitespace(self, recorder):
        assert recorder._extract_order_id_from_qr_value("  tk-12345  ") == "12345"

    def test_id_with_hyphen_valid(self, recorder):
        assert recorder._extract_order_id_from_qr_value("tk-12-34") == "12-34"

    def test_id_with_underscore_valid(self, recorder):
        assert recorder._extract_order_id_from_qr_value("tk-12_34") == "12_34"

    # --- sécurité : injection dans le QR ---

    def test_path_traversal_in_id_sanitized(self, recorder):
        # "../etc" → replace "/" → ".._etc" → regex ".." → "_" → "__etc" (5 chars)
        # La traversée est neutralisée : résultat sûr "__etc", pas None
        assert recorder._extract_order_id_from_qr_value("tk-../etc") == "__etc"

    def test_long_path_traversal_sanitized(self, recorder):
        # Si le résultat sanitisé est dans les longueurs valides, il ne doit pas contenir ".."
        result = recorder._extract_order_id_from_qr_value("tk-../etcc")
        if result is not None:
            assert ".." not in result
            assert "/" not in result

    def test_no_backslash_in_result(self, recorder):
        result = recorder._extract_order_id_from_qr_value("tk-12\\45")
        if result is not None:
            assert "\\" not in result


# ---------------------------------------------------------------------------
# État initial du Recorder (sans caméra)
# ---------------------------------------------------------------------------

class TestRecorderInitialState:
    def test_not_recording_on_init(self, recorder):
        assert recorder.is_recording is False

    def test_recording_order_id_none_on_init(self, recorder):
        assert recorder.recording_order_id is None

    def test_no_frame_on_init(self, recorder):
        assert recorder.get_latest_frame() is None

    def test_qr_error_count_zero_on_init(self, recorder):
        assert recorder._qr_error_count == 0
