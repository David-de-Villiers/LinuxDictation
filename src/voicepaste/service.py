"""Install the listener in the user's graphical login session."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from voicepaste.config import Config, model_dir
from voicepaste.desktop import install_dock_control
from voicepaste.models import require_local_model


def install_listener(cfg: Config) -> Path:
    """Write and enable a user service plus the existing shortcut helper."""
    require_local_model(cfg, cfg.shortcut.model_tier)
    if not (model_dir() / cfg.listener.command_model).is_dir():
        raise RuntimeError("run voicepaste models fetch-commands before installing the listener")
    executable = str(Path(sys.executable).absolute())
    escaped = executable.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    unit = "\n".join(
        [
            "[Unit]",
            "Description=VoicePaste local voice dictation",
            "PartOf=graphical-session.target",
            "PartOf=voicepaste-watch.service",
            "After=graphical-session.target",
            "",
            "[Service]",
            "Type=simple",
            f'ExecStart="{escaped}" -m voicepaste listen',
            "Restart=on-failure",
            "RestartSec=3",
            "SuccessExitStatus=130",
            "Environment=PYTHONUNBUFFERED=1",
            "",
            "[Install]",
            "WantedBy=graphical-session.target",
            "",
        ]
    )
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    target = config_home / "systemd" / "user" / "voicepaste-listener.service"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(unit)
    watcher = target.with_name("voicepaste-watch.service")
    watcher.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=VoicePaste microphone availability watcher",
                "PartOf=graphical-session.target",
                "After=graphical-session.target",
                "",
                "[Service]",
                "Type=simple",
                f'ExecStart="{escaped}" -m voicepaste watch',
                "Restart=on-failure",
                "RestartSec=3",
                "Environment=PYTHONUNBUFFERED=1",
                "",
                "[Install]",
                "WantedBy=graphical-session.target",
                "",
            ]
        )
    )
    helper = Path.home() / ".local" / "bin" / "voicepaste-dictate"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(f'#!/usr/bin/env sh\nexec {shlex.quote(executable)} -m voicepaste toggle "$@"\n')
    helper.chmod(0o755)
    variables = [
        name
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS")
        if name in os.environ
    ]
    if variables:
        subprocess.run(["systemctl", "--user", "import-environment", *variables], check=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "disable", "voicepaste-listener.service"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "voicepaste-watch.service"], check=True)
    install_dock_control()
    return target
