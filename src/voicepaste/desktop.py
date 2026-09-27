"""Install a small dock launcher with listening controls."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


def install_dock_control() -> Path:
    """Write a desktop launcher and append it to GNOME's existing favorites."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    target = data_home / "applications" / "voicepaste.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    executable = (
        sys.executable.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    command = f'"{executable}" -m voicepaste '
    target.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=VoicePaste",
                "Comment=Enable or disable voice dictation",
                "Icon=audio-input-microphone",
                "Exec=" + command + "listening-toggle",
                "Terminal=false",
                "StartupNotify=false",
                "Categories=Utility;AudioVideo;",
                "Actions=Enable;Disable;Status;",
                "",
                "[Desktop Action Enable]",
                "Name=Enable listening",
                "Exec=" + command + "listening-enable",
                "",
                "[Desktop Action Disable]",
                "Name=Disable listening",
                "Exec=" + command + "listening-disable",
                "",
                "[Desktop Action Status]",
                "Name=Listening status",
                "Exec=" + command + "listening-status",
                "",
            ]
        )
    )
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.shell", "favorite-apps"],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        favorites = ast.literal_eval(result.stdout.removeprefix("@as "))
        if target.name not in favorites:
            favorites.append(target.name)
            subprocess.run(
                ["gsettings", "set", "org.gnome.shell", "favorite-apps", repr(favorites)], check=True, timeout=3
            )
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError):
        print(f"Dock pinning unavailable; add {target.name} to your desktop favorites manually", file=sys.stderr)
    return target
