"""Verify shared notification identity on the actual desktop notification bus."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from voicepaste.notify import notify


def main() -> None:
    """Send two identified notifications and record their shared desktop source."""
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/voicepaste-notification-e2e.json")
    rule = "type='method_call',interface='org.freedesktop.Notifications',member='Notify',arg0='VoicePaste'"
    monitor = subprocess.Popen(
        ["dbus-monitor", "--session", rule], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    messages = ["VoicePaste notifications are now grouped here.", "Listening controls use the same VoicePaste group."]
    report = {"outcome": "failed"}
    try:
        time.sleep(0.3)
        assert notify(messages[0])
        assert notify(messages[1], title="Listening controls")
        time.sleep(0.3)
        monitor.terminate()
        output, _ = monitor.communicate(timeout=5)
        calls = [part for part in output.split("method call ") if "member=Notify" in part]
        assert len(calls) >= 2, output
        for call in calls:
            assert 'string "VoicePaste"' in call, call
            assert 'string "desktop-entry"' in call and 'string "voicepaste"' in call, call
        application = (
            subprocess.check_output(
                [
                    "gsettings",
                    "get",
                    "org.gnome.desktop.notifications.application:/org/gnome/desktop/notifications/application/voicepaste/",
                    "application-id",
                ],
                text=True,
            )
            .strip()
            .strip("'")
        )
        assert application == "voicepaste.desktop", application
        report = {
            "outcome": "passed",
            "application": "VoicePaste",
            "desktop_entry": "voicepaste",
            "gnome_application_id": application,
            "notification_count": len(calls),
            "messages": messages,
        }
    finally:
        if monitor.poll() is None:
            monitor.terminate()
            monitor.communicate(timeout=5)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(target)


if __name__ == "__main__":
    main()
