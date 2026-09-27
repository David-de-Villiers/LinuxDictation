"""Verify terminal and Neovim clipboard paste in disposable Kitty windows."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from voicepaste.clipboard import copy_text, read_text
from voicepaste.insert import insert_or_copy


def main() -> None:
    """Read actual terminal input and editor buffers after simulated paste."""
    original_focus = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
    clipboard_ok, previous = read_text("x11")
    report = {"outcome": "failed", "checks": []}
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/voicepaste-terminal-e2e.json")
    processes = []
    with tempfile.TemporaryDirectory(prefix="voicepaste-paste-") as directory:
        root = Path(directory)

        def window(title, command, terminal=True):
            process = subprocess.Popen(
                ["kitty", "--title", title, *command] if terminal else command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ["xdotool", "search", "--name", "^" + title + "$"], text=True, capture_output=True
                )
                if result.returncode == 0:
                    wid = result.stdout.splitlines()[-1]
                    subprocess.run(["xdotool", "windowactivate", "--sync", wid], check=True)
                    time.sleep(0.5)
                    return wid
                time.sleep(0.1)
            raise AssertionError(f"window missing: {title}")

        def query(server, expression):
            return subprocess.check_output(
                ["nvim", "--server", str(server), "--remote-expr", expression], text=True, timeout=5
            ).strip()

        try:
            terminal_output = root / "terminal.txt"
            program = (
                "import os,tty,termios; tty.setraw(0); data=os.read(0,4096); open("
                + repr(str(terminal_output))
                + ", 'wb').write(data); import time; time.sleep(30)"
            )
            window("VoicePaste terminal verification", [sys.executable, "-c", program])
            result = insert_or_copy("terminal paste probe")
            assert result.inserted, result
            deadline = time.monotonic() + 5
            while not terminal_output.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            received = terminal_output.read_text()
            assert received == "terminal paste probe", repr(received)
            report["checks"].append(
                {"case": "terminal paste without Enter", "received": received, "delivery": result.message}
            )
            editor_output = root / "editor.json"
            window(
                "VoicePaste text field verification",
                ["/usr/bin/python3", str(Path(__file__).with_name("gtk_paste_target.py")), str(editor_output)],
                terminal=False,
            )
            result = insert_or_copy("ordinary text field probe")
            assert result.inserted, result
            deadline = time.monotonic() + 5
            while not editor_output.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            editor = json.loads(editor_output.read_text())
            assert editor["text"] == "ordinary text field probe", editor
            assert any(key["key"].lower() == "v" and key["ctrl"] and not key["shift"] for key in editor["keys"]), editor
            report["checks"].append(
                {"case": "ordinary text field uses Ctrl+V", "received": editor["text"], "keys": editor["keys"]}
            )
            for clean in (True, False):
                server = root / ("clean.sock" if clean else "lazyvim.sock")
                buffer = root / ("clean.md" if clean else "lazyvim.md")
                window(
                    "VoicePaste Neovim verification " + str(clean),
                    ["nvim", *(["--clean"] if clean else []), "--listen", str(server), str(buffer)],
                )
                deadline = time.monotonic() + 30
                while not server.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                if not clean:
                    loaded = query(server, "luaeval(\"package.loaded['lazyvim.config'] ~= nil\")")
                    assert loaded == "true" or loaded == "1", loaded
                for mode in ("normal", "insert"):
                    query(server, 'execute("stopinsert")')
                    query(server, 'nvim_buf_set_lines(0,0,-1,v:true,[""])')
                    if mode == "insert":
                        query(server, 'execute("startinsert")')
                    payload = "Dictated text: café, quotes ' and \".\nSecond line stays literal."
                    result = insert_or_copy(payload)
                    assert result.inserted, result
                    time.sleep(0.2)
                    lines = json.loads(query(server, "json_encode(nvim_buf_get_lines(0,0,-1,v:true))"))
                    assert "\n".join(lines) == payload, lines
                    report["checks"].append(
                        {
                            "case": ("Neovim" if clean else "LazyVim") + " " + mode,
                            "lines": lines,
                            "delivery": result.message,
                        }
                    )
            report["outcome"] = "passed"
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(10)
            if clipboard_ok:
                copy_text(previous, "x11")
            subprocess.run(["xdotool", "windowactivate", original_focus], check=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n")
            print(target)


if __name__ == "__main__":
    main()
