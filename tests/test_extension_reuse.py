"""Réutilisation de l'onglet commande par l'extension Chrome (chrome_extension/reuse.js)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_extension_reuse_js():
    result = subprocess.run(
        ["node", "--test", "tests/extension_reuse.test.js"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_reuse_js_livre_avec_background():
    """background.js charge reuse.js : les deux doivent rester livrés ensemble."""
    assert 'importScripts("reuse.js")' in (ROOT / "chrome_extension/background.js").read_text(encoding="utf-8")
    assert (ROOT / "chrome_extension/reuse.js").is_file()
