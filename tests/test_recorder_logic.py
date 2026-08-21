"""Tests for core/recorder.py — logique QR sans caméra.

Le Recorder est instancié sans appeler start() : aucune caméra n'est ouverte.
On teste uniquement les méthodes de traitement de données pures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.recorder import Recorder
from core.storage import parse_qr_value


@pytest.fixture
def recorder(tmp_path: Path) -> Recorder:
    """Recorder sans caméra, utilisé uniquement pour les méthodes de logique."""
    return Recorder(output_dir=tmp_path)


# ---------------------------------------------------------------------------
# parse_qr_value — v1 "Tk-{id}" et v2 "TK2:{id}:{carrier}:{items}"
# (TicketPrinter/schema/ticket-qr-contract.md, repo TicketPrinter)
# ---------------------------------------------------------------------------

class TestParseQrValueV1:
    def test_valid_qr_returns_id(self):
        assert parse_qr_value("tk-12345") == ("12345", None)

    def test_uppercase_prefix_accepted(self):
        assert parse_qr_value("TK-12345") == ("12345", None)

    def test_mixed_case_prefix_accepted(self):
        assert parse_qr_value("Tk-12345") == ("12345", None)

    def test_min_length_id_valid(self):
        # 5 caractères = longueur minimale
        assert parse_qr_value("tk-12345") == ("12345", None)

    def test_max_length_id_valid(self):
        # 10 caractères = longueur maximale
        assert parse_qr_value("tk-1234567890") == ("1234567890", None)

    def test_id_too_short_returns_none(self):
        # "1234" = 4 chars < min 5
        assert parse_qr_value("tk-1234") is None

    def test_id_too_long_returns_none(self):
        # "12345678901" = 11 chars > max 10
        assert parse_qr_value("tk-12345678901") is None

    def test_no_prefix_returns_none(self):
        assert parse_qr_value("12345") is None

    def test_wrong_prefix_returns_none(self):
        assert parse_qr_value("qr-12345") is None

    def test_empty_string_returns_none(self):
        assert parse_qr_value("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_qr_value("   ") is None

    def test_strips_surrounding_whitespace(self):
        assert parse_qr_value("  tk-12345  ") == ("12345", None)

    def test_id_with_hyphen_valid(self):
        assert parse_qr_value("tk-12-34") == ("12-34", None)

    def test_id_with_underscore_valid(self):
        assert parse_qr_value("tk-12_34") == ("12_34", None)

    # --- sécurité : injection dans le QR ---

    def test_path_traversal_in_id_sanitized(self):
        # "../etc" → replace "/" → ".._etc" → regex ".." → "_" → "__etc" (5 chars)
        # La traversée est neutralisée : résultat sûr "__etc", pas None
        assert parse_qr_value("tk-../etc") == ("__etc", None)

    def test_long_path_traversal_sanitized(self):
        # Si le résultat sanitisé est dans les longueurs valides, il ne doit pas contenir ".."
        result = parse_qr_value("tk-../etcc")
        if result is not None:
            order_id, _carrier_code = result
            assert ".." not in order_id
            assert "/" not in order_id

    def test_no_backslash_in_result(self):
        result = parse_qr_value("tk-12\\45")
        if result is not None:
            order_id, _carrier_code = result
            assert "\\" not in order_id


class TestParseQrValueV2:
    def test_valid_v2_returns_id_and_carrier(self):
        assert parse_qr_value("TK2:482913:MONR-C:SKUA1*2,SKUB7*1") == ("482913", "MONR-C")

    def test_lowercase_marker_accepted(self):
        assert parse_qr_value("tk2:482913:MONR-C:SKUA1*2") == ("482913", "MONR-C")

    def test_no_items_block_still_valid(self):
        assert parse_qr_value("TK2:482913:RMAG:") == ("482913", "RMAG")

    def test_missing_carrier_field_returns_none(self):
        assert parse_qr_value("TK2:482913") is None

    def test_unknown_carrier_code_falls_back_to_none(self):
        # Code transporteur inconnu (dérive du contrat côté producteur) :
        # l'enregistrement démarre quand même, sans carrier_code.
        assert parse_qr_value("TK2:482913:XXXX:SKUA1*2") == ("482913", None)

    def test_invalid_order_id_returns_none(self):
        assert parse_qr_value("TK2:12:MONR-C:SKUA1*2") is None

    def test_carrier_code_lowercase_normalized(self):
        assert parse_qr_value("TK2:482913:monr-c:SKUA1*2") == ("482913", "MONR-C")

    def test_all_canonical_carrier_codes_accepted(self):
        for code in ("DPD-R", "DPD-P", "DPD-D", "MONR-C", "MONR-D", "POFR-D", "RMAG", "OTHR"):
            assert parse_qr_value(f"TK2:482913:{code}:SKUA1*1") == ("482913", code)


# ---------------------------------------------------------------------------
# État initial du Recorder (sans caméra)
# ---------------------------------------------------------------------------

class TestRecorderInitialState:
    def test_not_recording_on_init(self, recorder):
        assert recorder.is_recording is False

    def test_recording_order_id_none_on_init(self, recorder):
        assert recorder.recording_order_id is None

    def test_no_frame_on_init(self, recorder):
        assert recorder.get_latest_raw_frame() is None

    def test_qr_error_count_zero_on_init(self, recorder):
        assert recorder._qr_error_count == 0


# ---------------------------------------------------------------------------
# Cadence vidéo : le MP4 doit durer aussi longtemps que la scène filmée
# ---------------------------------------------------------------------------

class _FakeWriter:
    """VideoWriter minimal : compte les frames écrites."""

    def __init__(self) -> None:
        self.count = 0

    def write(self, frame) -> None:
        self.count += 1

    def release(self) -> None:
        pass


def _played_seconds(recorder: Recorder, real_fps: float, target_fps: float, duration: float) -> float:
    """Alimente _writer_loop avec un flux à `real_fps` et retourne la durée lue."""
    import queue

    import numpy as np

    writer = _FakeWriter()
    q: queue.Queue = queue.Queue()
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    t0 = 1_000_000.0
    for i in range(int(real_fps * duration)):
        q.put((frame.copy(), t0 + i / real_fps))
    q.put(None)

    recorder._writer_loop(
        writer,
        q,
        {"drop_tail": False, "tail_buffer_frames": 0, "target_fps": float(target_fps)},
    )
    return writer.count / target_fps


class TestWriterCadence:
    def test_effective_fps_prefers_measured(self, recorder):
        recorder._fps = 30.0
        recorder._measured_fps = 11.5
        assert recorder._effective_fps() == pytest.approx(11.5)

    def test_effective_fps_falls_back_to_declared(self, recorder):
        recorder._fps = 25.0
        recorder._measured_fps = None
        assert recorder._effective_fps() == pytest.approx(25.0)

    def test_effective_fps_clamped(self, recorder):
        recorder._measured_fps = 0.2
        assert recorder._effective_fps() == pytest.approx(5.0)
        recorder._measured_fps = 500.0
        assert recorder._effective_fps() == pytest.approx(60.0)

    def test_duration_matches_when_fps_correct(self, recorder):
        assert _played_seconds(recorder, 10.0, 10.0, 20.0) == pytest.approx(20.0, abs=0.2)

    def test_slow_camera_is_not_fast_forwarded(self, recorder):
        # Le bug historique : caméra à 10 fps écrite dans un conteneur 30 fps
        # donnait une vidéo 3x accélérée. Les frames doivent être dupliquées.
        assert _played_seconds(recorder, 10.0, 30.0, 20.0) == pytest.approx(20.0, abs=0.2)

    def test_fast_camera_is_not_slowed_down(self, recorder):
        assert _played_seconds(recorder, 30.0, 12.5, 20.0) == pytest.approx(20.0, abs=0.2)

    def test_measured_fps_from_frame_times(self, recorder):
        t0 = 1_000_000.0
        for i in range(30):
            recorder._record_frame_time(t0 + i / 15.0)
        assert recorder.measured_fps == pytest.approx(15.0, abs=0.1)

    def test_measured_fps_needs_enough_samples(self, recorder):
        recorder._record_frame_time(1_000_000.0)
        recorder._record_frame_time(1_000_000.1)
        assert recorder.measured_fps is None
