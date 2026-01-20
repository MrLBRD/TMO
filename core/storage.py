from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import re
import shutil
import sys

DEFAULT_RETENTION_DAYS = 45
MIN_ORDER_ID_LEN = 5
MAX_ORDER_ID_LEN = 10


def project_root() -> Path:
    try:
        if getattr(sys, "frozen", False) and getattr(sys, "executable", None):
            return Path(sys.executable).resolve().parent
    except Exception:
        pass

    return Path(__file__).resolve().parent.parent


def default_output_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "TMO" / "output"

    return project_root() / "output"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_order_id(order_id: str) -> str:
    cleaned = order_id.strip()
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", cleaned)
    return cleaned


def is_valid_order_id(order_id: str) -> bool:
    safe_id = sanitize_order_id(order_id)
    return MIN_ORDER_ID_LEN <= len(safe_id) <= MAX_ORDER_ID_LEN


def build_video_filename(order_id: str, on_date: date | None = None) -> str:
    safe_id = sanitize_order_id(order_id)
    return f"{safe_id}.mp4"


def build_video_path(
    order_id: str,
    output_dir: Path | None = None,
    on_date: date | None = None,
) -> Path:
    on_date = on_date or date.today()
    out = output_dir or default_output_dir()
    daily_dir = out / f"{on_date.year:04d}" / f"{on_date.month:02d}" / f"{on_date.day:02d}"
    base = daily_dir / build_video_filename(order_id, on_date=on_date)
    if not base.exists():
        return base

    safe_id = sanitize_order_id(order_id)
    for i in range(1, 10_000):
        candidate = daily_dir / f"{safe_id}_{i}.mp4"
        if not candidate.exists():
            return candidate

    return base


def clean_old_videos(
    output_dir: Path | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> list[Path]:
    out = output_dir or default_output_dir()
    if not out.exists():
        return []

    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted: list[Path] = []

    for path in out.rglob("*"):
        if not path.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                deleted.append(path)
            except OSError:
                continue

    return deleted


def disk_free_bytes(path: Path) -> int | None:
    try:
        usage = shutil.disk_usage(str(path))
    except Exception:
        try:
            usage = shutil.disk_usage(str(path.parent))
        except Exception:
            return None
    try:
        return int(usage.free)
    except Exception:
        return None


def format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    units = ["o", "Ko", "Mo", "Go", "To", "Po"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "o":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} o"
