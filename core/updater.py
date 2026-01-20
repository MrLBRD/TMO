"""Auto-update functionality using GitHub releases."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable

import requests

GITHUB_REPO = "MrLBRD/TMO"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
INSTALLER_ASSET_NAME = "TMO_Setup.exe"


@dataclass
class UpdateInfo:
    """Information about an available update."""

    available: bool
    current_version: str
    latest_version: str | None = None
    download_url: str | None = None
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
        response = requests.get(
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

        # Find the installer asset
        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").lower() == INSTALLER_ASSET_NAME.lower():
                download_url = asset.get("browser_download_url")
                break

        # Check if update is available
        update_available = is_newer_version(current_version, latest_version)

        return UpdateInfo(
            available=update_available,
            current_version=current_version,
            latest_version=latest_version,
            download_url=download_url,
            release_notes=data.get("body"),
        )

    except requests.exceptions.Timeout:
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error="Délai d'attente dépassé",
        )
    except requests.exceptions.ConnectionError:
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error="Impossible de se connecter à GitHub",
        )
    except requests.exceptions.RequestException as e:
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error=f"Erreur réseau: {e}",
        )
    except Exception as e:
        return UpdateInfo(
            available=False,
            current_version=current_version,
            error=f"Erreur: {e}",
        )


def download_update(
    download_url: str,
    progress_callback: Callable[[int, int], None] | None = None,
    timeout: float = 60.0,
) -> tuple[bool, str]:
    """
    Download the update installer.

    Args:
        download_url: URL to download the installer
        progress_callback: Optional callback(bytes_downloaded, total_bytes)
        timeout: Request timeout in seconds

    Returns:
        Tuple of (success, path_or_error_message)
    """
    try:
        response = requests.get(download_url, stream=True, timeout=timeout)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        # Create temp file for installer
        temp_dir = tempfile.gettempdir()
        installer_path = os.path.join(temp_dir, "TMO_Setup_Update.exe")

        downloaded = 0
        with open(installer_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        return True, installer_path

    except requests.exceptions.Timeout:
        return False, "Délai d'attente dépassé lors du téléchargement"
    except requests.exceptions.ConnectionError:
        return False, "Connexion perdue pendant le téléchargement"
    except requests.exceptions.RequestException as e:
        return False, f"Erreur de téléchargement: {e}"
    except OSError as e:
        return False, f"Erreur d'écriture: {e}"
    except Exception as e:
        return False, f"Erreur: {e}"


def run_installer(installer_path: str) -> tuple[bool, str]:
    """
    Run the downloaded installer and exit the application.

    Args:
        installer_path: Path to the downloaded installer

    Returns:
        Tuple of (success, error_message_if_failed)
    """
    if not os.path.exists(installer_path):
        return False, "Fichier d'installation non trouvé"

    try:
        # Launch installer
        if os.name == "nt":
            # Windows: use subprocess to launch installer
            subprocess.Popen(
                [installer_path],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            # Non-Windows: try to open with default handler
            subprocess.Popen(["open", installer_path])

        return True, ""

    except Exception as e:
        return False, f"Impossible de lancer l'installateur: {e}"


def check_for_updates_async(
    current_version: str,
    callback: Callable[[UpdateInfo], None],
) -> None:
    """
    Check for updates in a background thread.

    Args:
        current_version: Current app version
        callback: Function to call with UpdateInfo result
    """

    def _work() -> None:
        result = check_for_updates(current_version)
        callback(result)

    thread = threading.Thread(target=_work, name="tmo_update_check", daemon=True)
    thread.start()
