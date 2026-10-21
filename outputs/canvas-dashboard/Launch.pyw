"""Launch the local Canvas dashboard without opening a console window."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765/"
HEALTH = URL + "api/health"


def healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as response:
            return json.loads(response.read()).get("ok") is True
    except Exception:
        return False


def show_error(message: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Canvas 学习看板", 0x10)
    except Exception:
        pass


if not healthy():
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe") if interpreter.name.lower() == "python.exe" else interpreter
    if not pythonw.is_file():
        pythonw = interpreter
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [str(pythonw), str(ROOT / "app.py")], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags,
        )
    except Exception:
        show_error("无法启动本地看板。请确认已安装 Python，并在 Codex 中完成 Canvas 连接。")
        raise SystemExit(1)
    for _ in range(40):
        if healthy():
            break
        time.sleep(0.5)
    else:
        show_error("看板服务没有启动成功。请检查 Python 和 Canvas 连接后重试。")
        raise SystemExit(1)

webbrowser.open(URL, new=2)
