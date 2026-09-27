"""Desktop notification helper."""

from __future__ import annotations

import shutil
import subprocess


def notify(message: str, title: str = "VoicePaste") -> bool:
    """Send a best-effort desktop notification."""

    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(
            ["notify-send", title, message],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
