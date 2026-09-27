"""Focused-window insertion using clipboard plus synthetic paste."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from . import clipboard
from .config import InsertionConfig
from .focus import active_window, terminal_focused


@dataclass(frozen=True)
class InsertResult:
    """Result of attempting to copy and paste text."""

    inserted: bool
    copied: bool
    message: str


def session_type() -> str:
    """Return the active desktop session type inferred from environment."""

    return os.environ.get("XDG_SESSION_TYPE", "").lower() or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11")


def insertion_capability() -> dict[str, object]:
    """Report whether focused paste appears available for this session."""

    stype = session_type()
    tools = {
        "xdotool": bool(shutil.which("xdotool")),
        "wtype": bool(shutil.which("wtype")),
        "ydotool": bool(shutil.which("ydotool")),
        "xclip": bool(shutil.which("xclip")),
        "xsel": bool(shutil.which("xsel")),
        "wl-copy": bool(shutil.which("wl-copy")),
    }
    can_paste = False
    reason = ""
    if stype == "x11":
        can_paste = tools["xdotool"] and (tools["xclip"] or tools["xsel"])
        reason = "X11 clipboard paste available" if can_paste else "install xdotool and xclip or xsel"
    elif stype == "wayland":
        can_paste = tools["wtype"] and tools["wl-copy"]
        reason = "Wayland wtype paste available" if can_paste else "Wayland compositor may block insertion; use clipboard fallback"
    else:
        reason = "unknown desktop session"
    return {"session": stype, "tools": tools, "can_paste": can_paste, "reason": reason}


def _simulate_paste(stype: str, paste_key: str) -> tuple[bool, str]:
    try:
        if stype == "x11" and shutil.which("xdotool"):
            subprocess.run(["xdotool", "key", "--clearmodifiers", paste_key], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return True, f"pasted with xdotool ({paste_key})"
        if stype == "wayland" and shutil.which("wtype"):
            keys = paste_key.lower().split("+")
            if keys in (["ctrl", "v"], ["ctrl", "shift", "v"]):
                modifiers = keys[:-1]
                command = ["wtype"]
                for modifier in modifiers:
                    command.extend(["-M", modifier])
                command.append("v")
                for modifier in reversed(modifiers):
                    command.extend(["-m", modifier])
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                return True, f"pasted with wtype ({paste_key})"
            return False, f"unsupported Wayland paste key: {paste_key}"
        return False, "no paste simulation tool found"
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, f"paste simulation failed: {exc}"


def insert_or_copy(text: str, cfg: InsertionConfig | None = None) -> InsertResult:
    """Copy text to the clipboard and attempt focused-window paste."""

    cfg = cfg or InsertionConfig()
    stype = session_type()
    window = active_window() if stype == "x11" else None
    paste_key = cfg.terminal_paste_key if terminal_focused(stype, window) else cfg.paste_key
    previous_clipboard: str | None = None
    if cfg.restore_clipboard:
        ok, previous = clipboard.read_text(stype)
        if ok:
            previous_clipboard = previous
    copied, copy_msg = clipboard.copy_text(text, stype)
    if not copied:
        return InsertResult(False, False, copy_msg)
    if window and active_window() != window:
        return InsertResult(False, True, "focus changed; transcript copied")
    paste_ok, paste_msg = _simulate_paste(stype, paste_key)
    if paste_ok:
        time.sleep(0.05)
        if previous_clipboard is not None:
            clipboard.copy_text(previous_clipboard, stype)
        return InsertResult(True, True, paste_msg)
    return InsertResult(False, True, paste_msg)
