"""Choose the paste shortcut from the focused desktop context."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

TERMINAL_CLASSES = {
    "kitty",
    "gnome-terminal",
    "gnome-terminal-server",
    "org.gnome.terminal",
    "org.gnome.console",
    "kgx",
    "ptyxis",
    "org.gnome.ptyxis",
    "konsole",
    "alacritty",
    "terminator",
    "xfce4-terminal",
    "xterm",
    "uxterm",
    "urxvt",
    "rxvt",
    "tilix",
    "guake",
    "tilda",
    "wezterm",
    "org.wezfurlong.wezterm",
    "foot",
    "st",
    "sakura",
    "cool-retro-term",
    "ghostty",
    "com.mitchellh.ghostty",
}


def active_window() -> str | None:
    """Read the current X11 top-level window without changing focus."""
    try:
        return subprocess.check_output(
            ["xdotool", "getactivewindow"], text=True, stderr=subprocess.DEVNULL, timeout=1
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def terminal_focused(session: str, window: str | None = None) -> bool:
    """Identify native terminals or accessible embedded terminal controls."""
    pid = ""
    if session == "x11" and window:
        try:
            properties = subprocess.check_output(
                ["xprop", "-id", window, "WM_CLASS", "_NET_WM_PID"], text=True, stderr=subprocess.DEVNULL, timeout=1
            )
            classes = re.findall(r'"([^"\n]+)"', properties)
            if any(name.casefold() in TERMINAL_CLASSES for name in classes):
                return True
            match = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", properties)
            pid = match.group(1) if match else ""
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        result = subprocess.run(
            ["/usr/bin/python3", str(Path(__file__).with_name("focus_accessibility.py")), pid],
            capture_output=True,
            text=True,
            timeout=0.8,
        )
        return result.stdout.strip() == "terminal"
    except (OSError, subprocess.SubprocessError):
        return False
