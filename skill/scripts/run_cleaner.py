#!/usr/bin/env python3
"""Stable launcher for the bundled MemeR-AI desktop and CLI executables."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
APP_DIR = SKILL_DIR / "assets" / "app"
GUI_EXE = APP_DIR / "MemeR-AI图文视频印记数据清理.exe"
CLI_EXE = APP_DIR / "MemeR-AI图文视频印记数据清理-CLI.exe"
SOURCE = SKILL_DIR / "scripts" / "media_metadata_cleaner.py"


def main() -> int:
    args = sys.argv[1:]
    if args == ["--gui"]:
        if os.name != "nt" or not GUI_EXE.exists():
            print(f"GUI executable unavailable: {GUI_EXE}", file=sys.stderr)
            return 2
        subprocess.Popen([str(GUI_EXE)], cwd=str(APP_DIR))
        print("GUI_STARTED")
        return 0

    if os.name == "nt" and CLI_EXE.exists():
        command = [str(CLI_EXE), *args]
    else:
        command = [sys.executable, str(SOURCE), *args]
    return subprocess.run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
