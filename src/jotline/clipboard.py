"""Copy note text to the OS clipboard. OSC 52 is a fallback, not the Mac path."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def clipboard_command(platform: str | None = None) -> list[str] | None:
    host = sys.platform if platform is None else platform
    if host == "darwin":
        path = shutil.which("pbcopy")
        return [path] if path else None
    if host.startswith("linux"):
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        names: tuple[tuple[str, list[str]], ...]
        if wayland:
            names = (
                ("wl-copy", []),
                ("xclip", ["-selection", "clipboard"]),
                ("xsel", ["--clipboard", "--input"]),
            )
        else:
            names = (
                ("xclip", ["-selection", "clipboard"]),
                ("xsel", ["--clipboard", "--input"]),
                ("wl-copy", []),
            )
        for name, extra in names:
            path = shutil.which(name)
            if path:
                return [path, *extra]
    return None


def write_system_clipboard(text: str) -> bool:
    command = clipboard_command()
    if command is None:
        return False
    try:
        subprocess.run(
            command,
            input=text.encode("utf-8"),
            check=True,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True
