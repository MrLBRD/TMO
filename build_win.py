from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    resources_dir = root / "resources"
    icon_path = resources_dir / "app.ico"
    app_name = "TMO"

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name",
        app_name,
    ]

    if resources_dir.exists():
        cmd += ["--add-data", f"{resources_dir};resources"]

    if icon_path.exists():
        cmd += ["--icon", str(icon_path)]

    cmd += ["main.py"]

    subprocess.check_call(cmd, cwd=str(root))


if __name__ == "__main__":
    main()
