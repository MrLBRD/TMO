"""Auto-update functionality using GitHub releases."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from urllib.parse import urlparse

log = logging.getLogger(__name__)

GITHUB_REPO = "MrLBRD/TMO"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
INSTALLER_ASSET_NAME = "TMO_Setup.exe"
SHA256_ASSET_NAME = INSTALLER_ASSET_NAME + ".sha256"
SIGNATURE_ASSET_NAME = SHA256_ASSET_NAME + ".sig"

# Clé publique ed25519 (32 octets, base64) qui signe TMO_Setup.exe.sha256.
# La clé privée n'existe que dans le secret GitHub TMO_SIGNING_KEY ; la CI
# refuse de builder si la signature produite ne se vérifie pas avec cette clé.
# Générer la paire : python release_signing.py keygen (voir release_signing.py).
UPDATE_SIGNING_PUBLIC_KEY = "hpSa+vBbrm14ZgNGBc1S7PGHTcJ2suBqbrdFgYik2C4="

# Hosts autorisés pour le téléchargement de l'installateur et de son SHA256.
# Defense-in-depth : même si la réponse de l'API GitHub était manipulée, on
# refuse toute URL ne pointant pas vers l'infrastructure GitHub (HTTPS only).
_ALLOWED_UPDATE_HOSTS = frozenset(
    {"github.com", "api.github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)


# Plafond de taille de l'installateur (l'EXE actuel fait ~100 Mo).
MAX_INSTALLER_BYTES = 512 * 1024 * 1024

# Hash vérifié (signature + SHA256) de chaque installateur téléchargé, par chemin :
# run_installer() refuse tout fichier absent de ce registre ou modifié depuis.
_verified_installers: dict[str, str] = {}


def _is_allowed_update_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in _ALLOWED_UPDATE_HOSTS
    except Exception:
        return False


def _get(url: str, **kwargs) -> requests.Response:
    """GET qui refuse la réponse si une redirection a quitté les hôtes GitHub autorisés."""
    response = requests.get(url, **kwargs)
    for hop in (*response.history, response):
        if not _is_allowed_update_url(hop.url):
            response.close()
            log.error("update_redirect_blocked url_host=%s", urlparse(hop.url or "").hostname)
            raise ValueError("redirection hors GitHub refusée")
    return response


@dataclass
class UpdateInfo:
    """Information about an available update."""

    available: bool
    current_version: str
    latest_version: str | None = None
    download_url: str | None = None
    sha256_url: str | None = None
    signature_url: str | None = None
    release_notes: str | None = None
    error: str | None = None


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse version string like '1.0.0' into tuple (1, 0, 0) for comparison."""
    # Remove 'v' prefix if present
    version_str = version_str.lstrip("vV")
    # Extract numbers from version string
    numbers = re.findall(r"\d+", version_str)
    return tuple(int(n) for n in numbers) if numbers else (0,)


def is_newer_version(current: str, latest: str) -> bool:
    """Check if latest version is newer than current version."""
    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)
    return latest_tuple > current_tuple


def check_for_updates(current_version: str, timeout: float = 5.0) -> UpdateInfo:
    """
    Check GitHub releases for a newer version.

    Args:
        current_version: Current app version (e.g., "1.0.0")
        timeout: Request timeout in seconds

    Returns:
        UpdateInfo with update details or error
    """
    try:
        response = _get(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=timeout,
        )

        if response.status_code == 404:
            return UpdateInfo(
                available=False,
                current_version=current_version,
                error="Aucune release trouvée sur GitHub",
            )

        response.raise_for_status()
        data = response.json()

        latest_version = data.get("tag_name", "").lstrip("vV")
        if not latest_version:
            return UpdateInfo(
                available=False,
                current_version=current_version,
                error="Version non trouvée dans la release",
            )

        # Find the installer, SHA256 and signature assets
        download_url = None
        sha256_url = None
        signature_url = None
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if name == INSTALLER_ASSET_NAME.lower():
                download_url = asset.get("browser_download_url")
            elif name == SHA256_ASSET_NAME.lower():
                sha256_url = asset.get("browser_download_url")
            elif name == SIGNATURE_ASSET_NAME.lower():
                signature_url = asset.get("browser_download_url")

        # Check if update is available
        update_available = is_newer_version(current_version, latest_version)

        log.info(
            "update_check current=%s latest=%s available=%s",
            current_version, latest_version, update_available,
        )
        return UpdateInfo(
            available=update_available,
            current_version=current_version,
            latest_version=latest_version,
            download_url=download_url,
            sha256_url=sha256_url,
            signature_url=signature_url,
            release_notes=data.get("body"),
        )

    except requests.exceptions.Timeout:
        log.warning("update_check_failed error=timeout")
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error="Délai d'attente dépassé",
        )
    except requests.exceptions.ConnectionError:
        log.warning("update_check_failed error=connection_error")
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error="Impossible de se connecter à GitHub",
        )
    except requests.exceptions.RequestException as e:
        log.warning("update_check_failed error=%s", e)
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error=f"Erreur réseau: {e}",
        )
    except Exception as e:
        log.error("update_check_error error=%s", e)
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error=f"Erreur: {e}",
        )


def prepare_update(current_version: str) -> tuple[str | None, str]:
    """Vérifie GitHub puis télécharge et vérifie la nouvelle version (thread de fond).

    Returns:
        (chemin de l'installateur vérifié, message) si une mise à jour est prête ;
        (None, message court) en cas d'échec ; (None, "") si l'app est à jour.
    """
    info = check_for_updates(current_version)
    if info.error:
        return None, f"Mise à jour : {info.error}"
    if not info.available:
        return None, ""
    ok, result = download_update(
        info.download_url or "", sha256_url=info.sha256_url, signature_url=info.signature_url
    )
    if not ok:
        return None, f"Mise à jour v{info.latest_version} non installée : {result}"
    return result, f"Mise à jour v{info.latest_version} prête : installée à la fermeture"


def verify_sha256_signature(sha256_bytes: bytes, signature_b64: bytes, public_key_b64: str) -> bool:
    """True si signature_b64 est une signature ed25519 valide de sha256_bytes."""
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(base64.b64decode(signature_b64.strip(), validate=True), sha256_bytes)
        return True
    except (InvalidSignature, ValueError, binascii.Error):
        return False


def _fetch_small(url: str, timeout: float = 10.0, max_bytes: int = 4096) -> bytes:
    response = _get(url, timeout=timeout)
    response.raise_for_status()
    if len(response.content) > max_bytes:
        raise ValueError("fichier trop volumineux")
    return response.content


def download_update(
    download_url: str,
    progress_callback: Callable[[int, int], None] | None = None,
    timeout: float = 60.0,
    sha256_url: str | None = None,
    signature_url: str | None = None,
) -> tuple[bool, str]:
    """
    Download the update installer, after checking the signed SHA256.

    Le .sha256 doit porter une signature ed25519 valide (clé embarquée) et
    l'installateur doit correspondre à ce hash ; sinon rien n'est conservé.

    Returns:
        Tuple of (success, path_or_error_message)
    """
    for url in (download_url, sha256_url, signature_url):
        if not _is_allowed_update_url(url):
            log.error("update_download_blocked_url url_host=%s", urlparse(url or "").hostname)
            return False, "Mise à jour refusée : fichier de vérification absent ou hors GitHub"

    try:
        sha256_bytes = _fetch_small(sha256_url)  # type: ignore[arg-type]
        signature = _fetch_small(signature_url)  # type: ignore[arg-type]
    except Exception as e:
        log.error("update_verification_fetch_failed error=%s", e)
        return False, f"Impossible de récupérer les fichiers de vérification : {e}"

    if not verify_sha256_signature(sha256_bytes, signature, UPDATE_SIGNING_PUBLIC_KEY):
        log.error("update_signature_invalid")
        return False, "Signature de la mise à jour invalide — installation refusée"

    try:
        expected_hash = sha256_bytes.decode("ascii").strip().split()[0].lower()
    except Exception:
        return False, "Fichier de hash illisible"

    # Dossier à nom aléatoire (mkdtemp) : pas de nom prévisible dans %TEMP%.
    temp_dir = tempfile.mkdtemp(prefix="tmo_update_")
    installer_path = os.path.join(temp_dir, INSTALLER_ASSET_NAME)

    def _discard() -> None:
        try:
            os.unlink(installer_path)
        except OSError:
            pass
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass

    try:
        response = _get(download_url, stream=True, timeout=timeout)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        if total_size > MAX_INSTALLER_BYTES:
            raise ValueError("installateur trop volumineux")

        # Hash calculé pendant l'écriture : on ne relit pas le fichier sur disque.
        digest = hashlib.sha256()
        downloaded = 0
        with open(installer_path, "xb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_INSTALLER_BYTES:
                        raise ValueError("installateur trop volumineux")
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        actual_hash = digest.hexdigest()
        if actual_hash != expected_hash:
            log.error("update_integrity_failed expected=%s actual=%s", expected_hash, actual_hash)
            _discard()
            return False, "Vérification d'intégrité échouée — installateur potentiellement altéré"

        log.info("update_download_complete path=%s bytes=%d", installer_path, downloaded)
        _verified_installers[installer_path] = expected_hash
        return True, installer_path

    except requests.exceptions.Timeout:
        log.warning("update_download_failed error=timeout")
        _discard()
        return False, "Délai d'attente dépassé lors du téléchargement"
    except requests.exceptions.ConnectionError:
        log.warning("update_download_failed error=connection_error")
        _discard()
        return False, "Connexion perdue pendant le téléchargement"
    except requests.exceptions.RequestException as e:
        log.warning("update_download_failed error=%s", e)
        _discard()
        return False, f"Erreur de téléchargement: {e}"
    except OSError as e:
        log.error("update_download_write_error error=%s", e)
        _discard()
        return False, f"Erreur d'écriture: {e}"
    except Exception as e:
        log.error("update_download_error error=%s", e)
        _discard()
        return False, f"Erreur: {e}"


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_installer(installer_path: str, silent: bool = False) -> tuple[bool, str]:
    """
    Lance l'installateur téléchargé par download_update(), après avoir revérifié son hash.

    L'installateur peut attendre des heures dans %TEMP% (installation à la
    fermeture) : on refuse un fichier inconnu ou modifié depuis la vérification.
    silent : installation sans assistant (/SILENT), l'UAC reste demandé.

    Returns:
        Tuple of (success, error_message_if_failed)
    """
    expected = _verified_installers.get(installer_path)
    try:
        if expected is None or _file_sha256(installer_path) != expected:
            log.error("update_installer_unverified")
            return False, "Installateur non vérifié — installation refusée"
    except OSError:
        return False, "Fichier d'installation non trouvé"

    args = [installer_path, "/SILENT"] if silent else [installer_path]
    try:
        if os.name == "nt":
            subprocess.Popen(
                args,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            subprocess.Popen(["open", installer_path])
        return True, ""

    except Exception as e:
        return False, f"Impossible de lancer l'installateur: {e}"
