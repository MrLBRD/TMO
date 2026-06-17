from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent

    # Source de vérité unique : TMO.spec (collecte numpy/cv2, hiddenimports,
    # excludes, console=False…). On délègue au spec pour éviter toute dérive
    # entre ce script et la CI (.github/workflows/build-windows.yml).
    cmd = [sys.executable, "-m", "PyInstaller", "TMO.spec", "--noconfirm"]
    subprocess.check_call(cmd, cwd=str(root))


if __name__ == "__main__":
    main()
