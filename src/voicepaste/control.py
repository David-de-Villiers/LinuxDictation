"""Private local control socket for the dictation listener."""

from __future__ import annotations

import fcntl
import json
import os
import socket
from collections.abc import Callable
from pathlib import Path

from voicepaste.config import state_dir


def socket_path() -> Path:
    """Locate this user's listener socket."""
    base = Path(os.environ["XDG_RUNTIME_DIR"]) if os.environ.get("XDG_RUNTIME_DIR") else state_dir()
    return base / "voicepaste-control" / "listener.sock"


def send_control(command: str) -> dict:
    """Send a command to the running listener and return its state."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        try:
            client.connect(str(socket_path()))
            client.sendall(command.encode() + b"\n")
            response = bytearray()
            while b"\n" not in response and len(response) < 4096:
                block = client.recv(4096)
                if not block:
                    break
                response.extend(block)
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise RuntimeError("voice listener is not running; start voicepaste listen") from exc
    result = json.loads(response)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


class ControlServer:
    """Own a singleton lock and a socket restricted to the current user."""

    def __enter__(self) -> ControlServer:
        self.path = socket_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = self.path.with_suffix(".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise RuntimeError("a voice listener is already running") from exc
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.path.unlink(missing_ok=True)
            self.server.bind(str(self.path))
            self.path.chmod(0o600)
            self.server.listen(8)
            self.server.setblocking(False)
        except BaseException:
            self.server.close()
            self.lock.close()
            raise
        return self

    def poll(self, handle: Callable[[str], dict]) -> None:
        """Process pending requests without waiting for a new connection."""
        while True:
            try:
                client, _ = self.server.accept()
            except BlockingIOError:
                return
            with client:
                client.settimeout(0.2)
                try:
                    command = client.recv(128).decode().strip()
                    response = handle(command)
                    client.sendall(json.dumps(response).encode() + b"\n")
                except (OSError, UnicodeError):
                    continue

    def __exit__(self, *exc: object) -> None:
        self.server.close()
        self.path.unlink(missing_ok=True)
        self.lock.close()
