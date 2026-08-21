from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import re
import shutil
import sys

DEFAULT_RETENTION_DAYS = 45
# Bornes de longueur et table transporteur définies dans
# TicketPrinter/schema/ticket-qr-contract.md (repo TicketPrinter)
MIN_ORDER_ID_LEN = 5
MAX_ORDER_ID_LEN = 10
CARRIER_CODES = frozenset(
    {"DPD-R", "DPD-P", "DPD-D", "MONR-C", "MONR-D", "POFR-D", "RMAG", "OTHR"}
)


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


def sanitize_carrier_code(carrier_code: str) -> str:
    cleaned = carrier_code.strip().upper()
    return re.sub(r"[^A-Z0-9_-]+", "", cleaned)


def is_valid_carrier_code(carrier_code: str) -> bool:
    return sanitize_carrier_code(carrier_code) in CARRIER_CODES


def parse_qr_value(value: str) -> tuple[str, str | None] | None:
    """Parse une valeur scannée (QR ou Data Matrix) selon
    TicketPrinter/schema/ticket-qr-contract.md (repo TicketPrinter).

    - v1 : "Tk-{order_id}"
    - v2 : "TK2:{order_id}:{carrier_code}:{sku1}*{qty1},..." (bloc articles
      ignoré ici, non utilisé côté TMO)

    Retourne (order_id, carrier_code) ou None si le format/order_id est
    invalide. carrier_code vaut None en v1, ou si le code transporteur du v2
    n'est pas dans la table canonique.
    """
    value = str(value or "").strip()
    if not value:
        return None

    if value.upper().startswith("TK2:"):
        parts = value.split(":", 3)
        if len(parts) < 3:
            return None
        order_id = sanitize_order_id(parts[1])
        if not is_valid_order_id(order_id):
            return None
        carrier_code = sanitize_carrier_code(parts[2])
        if not is_valid_carrier_code(carrier_code):
            carrier_code = None
        return order_id, carrier_code

    prefix = "tk-"
    if not value.lower().startswith(prefix):
        return None

    candidate = sanitize_order_id(value[len(prefix) :])
    if not is_valid_order_id(candidate):
        return None

    return candidate, None


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
