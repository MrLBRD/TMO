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


# ---------------------------------------------------------------------------
# download_update — signature ed25519 du .sha256 (échec fermé)
# ---------------------------------------------------------------------------

import base64
import hashlib
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import core.updater as updater

_GH = "https://github.com/MrLBRD/TMO/releases/download/v9.9.9/"
_INSTALLER = b"MZ fake installer" * 1000


class _Resp:
    def __init__(self, content: bytes):
        self.content = content
        self.headers = {"content-length": str(len(content))}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


def _keypair():
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(pub).decode()


@pytest.fixture
def release(monkeypatch):
    key, pub = _keypair()
    monkeypatch.setattr(updater, "UPDATE_SIGNING_PUBLIC_KEY", pub)
    sha = f"{hashlib.sha256(_INSTALLER).hexdigest()}  TMO_Setup.exe".encode()
    files = {
        _GH + "TMO_Setup.exe": _INSTALLER,
        _GH + "TMO_Setup.exe.sha256": sha,
        _GH + "TMO_Setup.exe.sha256.sig": base64.b64encode(key.sign(sha)),
    }
    monkeypatch.setattr(updater.requests, "get", lambda url, **kw: _Resp(files[url]))
    return files


def _download():
    return updater.download_update(
        _GH + "TMO_Setup.exe",
        sha256_url=_GH + "TMO_Setup.exe.sha256",
        signature_url=_GH + "TMO_Setup.exe.sha256.sig",
    )


class TestDownloadUpdateSignature:
    def test_valid_signature_accepted_in_random_dir(self, release):
        ok, path = _download()
        assert ok, path
        assert open(path, "rb").read() == _INSTALLER
        assert os.path.basename(os.path.dirname(path)).startswith("tmo_update_")
        assert path != _download()[1]  # nouveau dossier à chaque téléchargement

    def test_wrong_signature_refused(self, release):
        other, _ = _keypair()
        release[_GH + "TMO_Setup.exe.sha256.sig"] = base64.b64encode(other.sign(release[_GH + "TMO_Setup.exe.sha256"]))
        ok, msg = _download()
        assert not ok and "Signature" in msg

    def test_missing_signature_refused(self, release):
        ok, _ = updater.download_update(_GH + "TMO_Setup.exe", sha256_url=_GH + "TMO_Setup.exe.sha256")
        assert not ok

    def test_empty_public_key_refused(self, release, monkeypatch):
        monkeypatch.setattr(updater, "UPDATE_SIGNING_PUBLIC_KEY", "")
        assert not _download()[0]

    def test_tampered_installer_refused_and_deleted(self, release, monkeypatch, tmp_path):
        release[_GH + "TMO_Setup.exe"] = _INSTALLER + b"x"
        (tmp_path / "d").mkdir()
        monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda prefix="": str(tmp_path / "d"))
        ok, msg = _download()
        assert not ok and "intégrité" in msg
        assert not (tmp_path / "d").exists()


class TestReleaseSigningScript:
    def test_sign_produces_verifiable_sig(self, monkeypatch, tmp_path):
        import release_signing

        key, pub = _keypair()
        monkeypatch.setattr(updater, "UPDATE_SIGNING_PUBLIC_KEY", pub)
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        sha = tmp_path / "TMO_Setup.exe.sha256"
        sha.write_bytes(b"abc  TMO_Setup.exe")
        out = release_signing.sign(sha, base64.b64encode(raw).decode())
        assert updater.verify_sha256_signature(sha.read_bytes(), out.read_bytes(), pub)

    def test_sign_refuses_key_not_matching_embedded(self, monkeypatch, tmp_path):
        import release_signing

        key, _ = _keypair()
        _, other_pub = _keypair()
        monkeypatch.setattr(updater, "UPDATE_SIGNING_PUBLIC_KEY", other_pub)
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        sha = tmp_path / "x.sha256"
        sha.write_bytes(b"abc")
        with pytest.raises(SystemExit):
            release_signing.sign(sha, base64.b64encode(raw).decode())
