from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_status(
    api_url: str | None,
    order_id: str,
    status: str,
    site_url: str | None = None,
    api_key: str | None = None,
    timestamp: str | None = None,
    timeout_seconds: float = 2.0,
) -> tuple[bool, str]:
    url = api_url.strip() if api_url and api_url.strip() else ""
    if not url:
        base = site_url.strip() if site_url and site_url.strip() else ""
        if base:
            url = base.rstrip("/") + "/api/poll"
    if not url:
        return True, "api_disabled"

    payload: dict[str, Any] = {
        "order_id": order_id,
        "timestamp": timestamp or utc_timestamp(),
        "status": status,
    }

    headers: dict[str, str] = {}
    if api_key and api_key.strip():
        headers["X-API-Key"] = api_key.strip()
 
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
        resp.raise_for_status()
        return True, str(resp.status_code)
    except Exception as exc:
        return False, str(exc)
