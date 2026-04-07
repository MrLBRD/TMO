"""Tests for core/config.py — sauvegarde/chargement de configuration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import AppConfig, load_config, save_config


# ---------------------------------------------------------------------------
# Roundtrip save → load
# ---------------------------------------------------------------------------

class TestConfigRoundtrip:
    def test_save_and_load_all_fields(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = AppConfig(
            camera_index=2,
            camera_flip="horizontal",
            output_dir="/some/path",
            retention_days=30,
            max_recording_minutes=20,
            site_url="https://example.com",
            scan_roi_percent=75,
            qr_brightness=15,
            qr_contrast=1.5,
        )
        with patch("core.config.config_path", return_value=config_file):
            saved_path = save_config(cfg)
            loaded, err = load_config()

        assert saved_path == config_file
        assert err is None
        assert loaded.camera_index == 2
        assert loaded.camera_flip == "horizontal"
        assert loaded.output_dir == "/some/path"
        assert loaded.retention_days == 30
        assert loaded.max_recording_minutes == 20
        assert loaded.site_url == "https://example.com"
        assert loaded.scan_roi_percent == 75
        assert loaded.qr_brightness == 15
        assert abs(loaded.qr_contrast - 1.5) < 0.01

    def test_save_creates_file(self, tmp_path):
        config_file = tmp_path / "subdir" / "config.json"
        with patch("core.config.config_path", return_value=config_file):
            save_config(AppConfig())
        assert config_file.exists()


# ---------------------------------------------------------------------------
# Valeurs par défaut
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    def test_defaults_when_no_file(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch("core.config.config_path", return_value=missing):
            cfg, err = load_config()
        assert err is None
        assert cfg.camera_index == 0
        assert cfg.camera_flip == "none"
        assert cfg.retention_days == 45
        assert cfg.max_recording_minutes == 15
        assert cfg.scan_roi_percent == 90
        assert cfg.qr_brightness == 0
        assert abs(cfg.qr_contrast - 1.0) < 0.01

    def test_corrupted_json_returns_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("{ not valid json !!!", encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, err = load_config()
        assert cfg.camera_index == 0
        assert cfg.retention_days == 45
        assert err is not None
        assert "corrompu" in err


# ---------------------------------------------------------------------------
# Clamping des valeurs hors bornes
# ---------------------------------------------------------------------------

class TestConfigClamping:
    def test_scan_roi_clamped_to_max(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"scan_roi_percent": 200}), encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.scan_roi_percent == 100

    def test_scan_roi_clamped_to_min(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"scan_roi_percent": 10}), encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.scan_roi_percent == 50

    def test_qr_contrast_clamped_to_max(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"qr_contrast": 99.9}), encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.qr_contrast == 3.0

    def test_qr_contrast_clamped_to_min(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"qr_contrast": 0.1}), encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.qr_contrast == 0.5

    def test_qr_brightness_clamped_to_max(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"qr_brightness": 500}), encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.qr_brightness == 100

    def test_qr_brightness_clamped_to_min(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"qr_brightness": -500}), encoding="utf-8")
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.qr_brightness == -100

    def test_unknown_fields_ignored(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"camera_index": 1, "unknown_field": "oops"}), encoding="utf-8"
        )
        with patch("core.config.config_path", return_value=config_file):
            cfg, _ = load_config()
        assert cfg.camera_index == 1
        assert not hasattr(cfg, "unknown_field")
