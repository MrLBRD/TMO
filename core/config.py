from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys

from .storage import default_output_dir, project_root


@dataclass
class AppConfig:
    camera_index: int = 0
    camera_flip: str = "none"
    output_dir: str = ""
    retention_days: int = 45
    max_recording_minutes: int = 15
    site_url: str = ""
    scan_roi_percent: int = 90
    qr_brightness: int = 0
    qr_contrast: float = 1.0


def _config_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "TMO"
        return Path.home() / "AppData" / "Roaming" / "TMO"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TMO"

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "TMO"
    return Path.home() / ".config" / "TMO"


def config_path() -> Path:
    return _config_dir() / "config.json"


def log_path() -> Path:
    return _config_dir() / "tmo.log"


def resolve_output_dir(config: AppConfig) -> Path:
    raw = config.output_dir.strip()
    if not raw:
        return default_output_dir()

    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = project_root() / p
    return p


def _apply_env_overrides(cfg: AppConfig) -> AppConfig:
    camera_index = os.environ.get("TMO_CAMERA_INDEX")
    if camera_index is not None and camera_index.strip() != "":
        try:
            cfg.camera_index = int(camera_index)
        except ValueError:
            pass

    camera_flip = os.environ.get("TMO_CAMERA_FLIP")
    if camera_flip is not None and camera_flip.strip() != "":
        try:
            cfg.camera_flip = str(camera_flip).strip()
        except Exception:
            pass

    output_dir = os.environ.get("TMO_OUTPUT_DIR")
    if output_dir is not None and output_dir.strip() != "":
        cfg.output_dir = output_dir

    retention_days = os.environ.get("TMO_RETENTION_DAYS")
    if retention_days is not None and retention_days.strip() != "":
        try:
            cfg.retention_days = int(retention_days)
        except ValueError:
            pass

    max_recording_minutes = os.environ.get("TMO_MAX_RECORDING_MINUTES")
    if max_recording_minutes is not None and max_recording_minutes.strip() != "":
        try:
            cfg.max_recording_minutes = int(max_recording_minutes)
        except ValueError:
            pass

    site_url = os.environ.get("TMO_SITE_URL")
    if site_url is not None and site_url.strip() != "":
        cfg.site_url = site_url

    scan_roi_percent = os.environ.get("TMO_SCAN_ROI_PERCENT")
    if scan_roi_percent is not None and scan_roi_percent.strip() != "":
        try:
            cfg.scan_roi_percent = max(50, min(100, int(scan_roi_percent)))
        except ValueError:
            pass

    qr_brightness = os.environ.get("TMO_QR_BRIGHTNESS")
    if qr_brightness is not None and qr_brightness.strip() != "":
        try:
            cfg.qr_brightness = max(-100, min(100, int(qr_brightness)))
        except ValueError:
            pass

    qr_contrast = os.environ.get("TMO_QR_CONTRAST")
    if qr_contrast is not None and qr_contrast.strip() != "":
        try:
            cfg.qr_contrast = max(0.5, min(3.0, float(qr_contrast)))
        except ValueError:
            pass

    return cfg


def load_config() -> tuple[AppConfig, str | None]:
    cfg = AppConfig()
    path = config_path()
    error: str | None = None

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "camera_index" in data:
                    try:
                        cfg.camera_index = int(data["camera_index"])
                    except Exception:
                        pass
                if "camera_flip" in data:
                    try:
                        cfg.camera_flip = str(data["camera_flip"])
                    except Exception:
                        pass
                if "output_dir" in data:
                    try:
                        cfg.output_dir = str(data["output_dir"])
                    except Exception:
                        pass
                if "retention_days" in data:
                    try:
                        cfg.retention_days = int(data["retention_days"])
                    except Exception:
                        pass
                if "max_recording_minutes" in data:
                    try:
                        cfg.max_recording_minutes = int(data["max_recording_minutes"])
                    except Exception:
                        pass
                if "site_url" in data:
                    try:
                        cfg.site_url = str(data["site_url"])
                    except Exception:
                        pass
                if "scan_roi_percent" in data:
                    try:
                        cfg.scan_roi_percent = max(50, min(100, int(data["scan_roi_percent"])))
                    except Exception:
                        pass
                if "qr_brightness" in data:
                    try:
                        cfg.qr_brightness = max(-100, min(100, int(data["qr_brightness"])))
                    except Exception:
                        pass
                if "qr_contrast" in data:
                    try:
                        cfg.qr_contrast = max(0.5, min(3.0, float(data["qr_contrast"])))
                    except Exception:
                        pass
        except Exception as e:
            error = (
                f"Le fichier config.json est corrompu et a été ignoré.\n"
                f"La configuration a été réinitialisée aux valeurs par défaut.\n\n"
                f"Détail : {e}"
            )

    return _apply_env_overrides(cfg), error


def save_config(cfg: AppConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _version_file_path() -> Path:
    return _config_dir() / "last_version.txt"


def get_last_run_version() -> str | None:
    """Get the version from the last time the app was run."""
    path = _version_file_path()
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def set_last_run_version(version: str) -> None:
    """Store the current version for next run comparison."""
    path = _version_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(version, encoding="utf-8")
    except Exception:
        pass


def check_if_just_updated(current_version: str) -> bool:
    """Check if app was just updated (version changed since last run)."""
    last_version = get_last_run_version()
    if last_version is None:
        # First run ever
        return False
    return last_version != current_version
