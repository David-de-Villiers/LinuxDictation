"""Desktop notification helper."""

from __future__ import annotations

import shutil
import subprocess


def notify(message: str, title: str = "VoicePaste") -> bool:
    """Send a best-effort desktop notification."""

    if not shutil.which("notify-send"):
        return False
    try:
        result = subprocess.run(
            [
                "notify-send",
                "--app-name=VoicePaste",
                "--icon=audio-input-microphone",
                "--hint=string:desktop-entry:voicepaste",
                title,
                message,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
