from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: Path) -> None:
    """Configure root logging to a rotating file handler.

    Max file size: 1 MB, 3 backups kept. No console output (GUI app).
    Never called more than once — subsequent calls are no-ops.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    log_file.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_file,
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    )

    root.setLevel(logging.INFO)
    root.addHandler(handler)
