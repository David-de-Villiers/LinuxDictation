"""Verify real microphone handoff and installed dock controls."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

PYTHON = sys.executable


def cli(command: str) -> dict:
    result = subprocess.run([PYTHON, "-m", "voicepaste", command], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def wait_state(expected: str, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = cli("status")
        if state["state"] == expected:
            return state
        time.sleep(0.2)
    raise AssertionError(f"expected {expected}, got {state}")


def capture() -> subprocess.Popen:
    return subprocess.Popen(
        ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    """Run against the installed user services and restore listening afterwards."""
    report = {"outcome": "failed", "checks": []}
    processes = []
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/voicepaste-desktop-e2e.json")
    assert cli("status")["state"] == "idle", "run when dictation is idle"
    try:
        with tempfile.TemporaryDirectory(prefix="voicepaste-playback-") as temporary:
            audio = Path(temporary) / "silence.wav"
            with wave.open(str(audio), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(bytes(16000 * 2 * 4))
            playback = subprocess.Popen(["pw-play", str(audio)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(playback)
            time.sleep(1)
            assert cli("status")["state"] == "idle"
            playback.terminate()
            playback.wait(5)
            report["checks"].append({"case": "playback and own microphone do not pause listening", "passed": True})
        first = capture()
        processes.append(first)
        paused = wait_state("paused")
        assert "pw-record" in paused["reason"], paused
        time.sleep(0.5)
        pid = subprocess.check_output(
            ["systemctl", "--user", "show", "voicepaste-listener.service", "-p", "MainPID", "--value"], text=True
        ).strip()
        assert pid == "0", pid
        report["checks"].append({"case": "competing capture stops listener", "status": paused, "listener_pid": pid})
        second = capture()
        processes.append(second)
        time.sleep(1)
        first.terminate()
        first.wait(5)
        assert wait_state("paused")["state"] == "paused"
        report["checks"].append({"case": "second recorder keeps listener paused", "passed": True})
        cli("listening-disable")
        second.terminate()
        second.wait(5)
        time.sleep(2)
        assert wait_state("disabled")["state"] == "disabled"
        subprocess.run(["systemctl", "--user", "restart", "voicepaste-watch.service"], check=True)
        assert wait_state("disabled")["state"] == "disabled"
        report["checks"].append(
            {"case": "manual disable persists after recorder exit and watcher restart", "passed": True}
        )
        cli("listening-enable")
        wait_state("idle")
        report["checks"].append({"case": "manual enable resumes", "passed": True})
        third = capture()
        processes.append(third)
        wait_state("paused")
        third.terminate()
        third.wait(5)
        wait_state("idle")
        report["checks"].append({"case": "automatic resume after capture closes", "passed": True})
        desktop = Path.home() / ".local/share/applications/voicepaste.desktop"
        subprocess.run(["gio", "launch", str(desktop)], check=True, stdout=subprocess.DEVNULL)
        wait_state("disabled")
        subprocess.run(["gio", "launch", str(desktop)], check=True, stdout=subprocess.DEVNULL)
        wait_state("idle")
        report["checks"].append({"case": "dock primary action toggles listening", "passed": True})
        launch_action = "from gi.repository import Gio; import sys; Gio.DesktopAppInfo.new_from_filename(sys.argv[1]).launch_action(sys.argv[2], None)"
        for action, expected in (("Disable", "disabled"), ("Enable", "idle"), ("Status", "idle")):
            subprocess.run(["/usr/bin/python3", "-c", launch_action, str(desktop), action], check=True, capture_output=True)
            wait_state(expected)
        report["checks"].append({"case": "dock enable, disable, and status actions", "passed": True})
        if subprocess.run(["pgrep", "-x", "obs"], stdout=subprocess.DEVNULL).returncode == 1:
            with tempfile.TemporaryDirectory(prefix="voicepaste-obs-") as config:
                import os

                obs = subprocess.Popen(
                    ["obs", "--minimize-to-tray", "--disable-updater"],
                    env={**os.environ, "XDG_CONFIG_HOME": config},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(obs)
                paused = wait_state("paused")
                assert "OBS" in paused["reason"] or "obs" in paused["reason"], paused
                obs.terminate()
                obs.wait(15)
                wait_state("idle")
                report["checks"].append({"case": "OBS open pauses and OBS close resumes", "passed": True})
        report["outcome"] = "passed"
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(15)
        cli("listening-enable")
        wait_state("idle")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(target)


if __name__ == "__main__":
    main()
