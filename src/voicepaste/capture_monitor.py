"""Identify microphone consumers and applications that suspend dictation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from voicepaste.config import Config


def microphone_consumers(excluded_pid: int = 0) -> list[str]:
    """Read PipeWire capture links, excluding playback and the listener itself."""
    result = subprocess.run(["pw-dump"], capture_output=True, text=True, check=True, timeout=2)
    objects = json.loads(result.stdout)
    nodes = {obj["id"]: obj.get("info", {}) for obj in objects if obj["type"].endswith(":Node")}
    clients = {obj["id"]: obj.get("info", {}).get("props", {}) for obj in objects if obj["type"].endswith(":Client")}
    capture_targets = set()
    for obj in objects:
        if not obj["type"].endswith(":Link"):
            continue
        link = obj.get("info", {})
        source = nodes.get(link.get("output-node-id"), {}).get("props", {})
        if source.get("media.class") in {"Audio/Source", "Audio/Source/Virtual"} and link.get("state") in {
            "active",
            "paused",
        }:
            capture_targets.add(link.get("input-node-id"))
    consumers = set()
    for node_id in capture_targets:
        info = nodes.get(node_id, {})
        props = info.get("props", {})
        if props.get("media.class") != "Stream/Input/Audio":
            continue
        owner = {**clients.get(props.get("client.id"), {}), **props}
        if str(owner.get("application.process.id", "")) == str(excluded_pid):
            continue
        consumers.add(str(owner.get("application.name") or owner.get("node.name") or "another audio app"))
    return sorted(consumers)


def blocking_apps(names: list[str]) -> list[str]:
    """Find configured same-user processes, including OBS without mic sources."""
    matches = set()
    wanted = {name.casefold() for name in names}
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            name = (process / "comm").read_text().strip()
            if name.casefold() in wanted:
                matches.add(name)
        except (OSError, UnicodeError):
            continue
    return sorted(matches)


def pause_reason(cfg: Config, listener_pid: int) -> str:
    """Return why listening should pause, or an empty string when available."""
    apps = blocking_apps(cfg.listener.pause_processes)
    if apps:
        return "Open application: " + ", ".join(apps)
    if cfg.listener.pause_on_capture:
        try:
            consumers = microphone_consumers(listener_pid)
        except (OSError, ValueError, subprocess.SubprocessError):
            return "Microphone monitoring unavailable (pw-dump)"
        if consumers:
            return "Microphone in use: " + ", ".join(consumers)
    return ""
