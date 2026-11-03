"""Signature ed25519 du TMO_Setup.exe.sha256 publié dans les releases.

    python release_signing.py keygen
        Affiche une clé privée (à coller dans le secret GitHub TMO_SIGNING_KEY,
        jamais dans le dépôt) et la clé publique (à mettre dans
        UPDATE_SIGNING_PUBLIC_KEY, core/updater.py).

    python release_signing.py sign dist/TMO_Setup.exe.sha256
        CI : lit la clé privée dans TMO_SIGNING_KEY, écrit <fichier>.sig
        (signature base64) puis la vérifie avec la clé publique embarquée.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def keygen() -> None:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    print("Clé privée (secret GitHub TMO_SIGNING_KEY) :")
    print(base64.b64encode(raw).decode("ascii"))
    print("Clé publique (UPDATE_SIGNING_PUBLIC_KEY dans core/updater.py) :")
    print(_public_b64(key))


def sign(sha256_path: Path, private_key_b64: str) -> Path:
    from core.updater import UPDATE_SIGNING_PUBLIC_KEY, verify_sha256_signature

    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64.strip(), validate=True))
    if _public_b64(key) != UPDATE_SIGNING_PUBLIC_KEY:
        raise SystemExit("TMO_SIGNING_KEY ne correspond pas à UPDATE_SIGNING_PUBLIC_KEY (core/updater.py)")
    data = sha256_path.read_bytes()
    sig = base64.b64encode(key.sign(data))
    if not verify_sha256_signature(data, sig, UPDATE_SIGNING_PUBLIC_KEY):
        raise SystemExit("signature produite invalide")
    out = sha256_path.with_name(sha256_path.name + ".sig")
    out.write_bytes(sig)
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["keygen"]:
        keygen()
    elif len(sys.argv) == 3 and sys.argv[1] == "sign":
        secret = os.environ.get("TMO_SIGNING_KEY", "")
        if not secret:
            raise SystemExit("TMO_SIGNING_KEY absent")
        print(sign(Path(sys.argv[2]), secret))
    else:
        raise SystemExit(__doc__)
