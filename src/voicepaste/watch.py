"""Keep dictation stopped while other apps use the microphone."""

from __future__ import annotations

import fcntl
import json
import signal
import subprocess
import time

from voicepaste.capture_monitor import pause_reason
from voicepaste.config import Config, state_dir
from voicepaste.control import send_control

LISTENER_UNIT = "voicepaste-listener.service"
WATCH_UNIT = "voicepaste-watch.service"


def enabled() -> bool:
    """Read the persistent manual listening preference."""
    return not (state_dir() / "listening-disabled").exists()


def set_enabled(value: bool | None) -> bool:
    """Set or toggle listening without overriding automatic microphone pauses."""
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "listening-preference.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = not enabled() if value is None else value
        target = directory / "listening-disabled"
        if value:
            target.unlink(missing_ok=True)
        else:
            target.touch(mode=0o600)
    return value


def watcher_status() -> dict:
    """Read the watcher's latest state for status while the listener is stopped."""
    try:
        return json.loads((state_dir() / "watch-status.json").read_text())
    except (OSError, ValueError):
        return {"state": "stopped", "enabled": enabled(), "reason": "Listener is stopped"}


def listener_service() -> tuple[str, int]:
    """Read the listener service's current state and process ID."""
    result = subprocess.run(
        ["systemctl", "--user", "show", LISTENER_UNIT, "-p", "ActiveState", "-p", "MainPID"],
        capture_output=True,
        text=True,
        check=True,
        timeout=3,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return values.get("ActiveState", "inactive"), int(values.get("MainPID", "0"))


def run_watcher(cfg: Config) -> None:
    """Start and suspend the listener according to microphone and manual state."""
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "watch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("a microphone watcher is already running") from exc
        running = True

        def terminate(signum, frame):
            nonlocal running
            running = False

        previous = signal.signal(signal.SIGTERM, terminate)
        clear_since = None
        suspended_pid = None
        last_status = None
        try:
            while running:
                service_state, pid = listener_service()
                manual = enabled()
                reason = pause_reason(cfg, pid) if manual else "Disabled manually"
                if reason:
                    clear_since = None
                    state = "paused" if manual else "disabled"
                    if pid and suspended_pid != pid:
                        try:
                            send_control("suspend")
                            suspended_pid = pid
                        except (RuntimeError, OSError, ValueError):
                            # wait for startup to expose its control socket
                            pass
                else:
                    clear_since = clear_since or time.monotonic()
                    state = "listening" if service_state == "active" else "starting"
                    if service_state in {"inactive", "failed"} and time.monotonic() - clear_since >= 1:
                        subprocess.run(["systemctl", "--user", "start", LISTENER_UNIT], check=True, timeout=10)
                        suspended_pid = None
                status = {"state": state, "enabled": manual, "reason": reason}
                if status != last_status:
                    temporary = directory / "watch-status.tmp"
                    temporary.write_text(json.dumps(status) + "\n")
                    temporary.replace(directory / "watch-status.json")
                    print(json.dumps(status), flush=True)
                    last_status = status
                time.sleep(0.5)
        finally:
            signal.signal(signal.SIGTERM, previous)
            (directory / "watch-status.json").unlink(missing_ok=True)
