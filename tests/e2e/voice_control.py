"""Replay local speech through the real listener and save a JSON report."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Queue

import numpy as np

from voicepaste.config import Config
from voicepaste.control import socket_path
from voicepaste.listener import run_listener


def synthesize(text: str) -> bytes:
    """Generate repeatable speech with the system's local eSpeak library."""
    library = ctypes.CDLL("libespeak-ng.so.1")
    rate = library.espeak_Initialize(2, 0, None, 0)
    chunks = []
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

    @callback_type
    def callback(samples, count, events):
        if count:
            chunks.append(np.ctypeslib.as_array(samples, shape=(count,)).copy())
        return 0

    library.espeak_SetSynthCallback(callback)
    library.espeak_SetVoiceByName(b"en-us")
    library.espeak_SetParameter(1, 145, 0)
    data = text.encode() + b"\0"
    library.espeak_Synth(data, len(data), 0, 1, 0, 0, None, None)
    library.espeak_Synchronize()
    samples = np.concatenate(chunks)
    resampled = np.interp(np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples)
    return resampled.astype("<i2").tobytes()


def main() -> None:
    """Exercise voice commands, reminders, long capture, and socket controls."""
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/voicepaste-e2e.json")
    events = []
    transcripts = []
    notifications = []
    failures = []
    audio: Queue[bytes | None] = Queue(maxsize=8)
    cfg = Config()

    def event(name, **details):
        events.append({"event": name, **details})

    def source():
        while True:
            yield audio.get()

    def wait_for(predicate, label, timeout=40):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if failures:
                raise RuntimeError(failures)
            time.sleep(0.02)
        raise AssertionError(f"timeout: {label}; events={events}")

    def feed(data):
        for offset in range(0, len(data), 3200):
            audio.put(data[offset : offset + 3200], timeout=30)

    def silence(seconds):
        feed(bytes(int(seconds * 32000)))

    def control(action):
        result = subprocess.run(
            [sys.executable, "-m", "voicepaste", action], text=True, capture_output=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def control_pair():
        clients = [socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) for _ in range(2)]
        try:
            for client in clients:
                client.settimeout(5)
                client.connect(str(socket_path()))
                client.sendall(b"toggle\n")
            return [json.loads(client.recv(4096)) for client in clients]
        finally:
            for client in clients:
                client.close()

    def listen():
        try:
            run_listener(cfg, frames=source(), deliver=transcripts.append, announce=notifications.append, event=event)
        except BaseException as exc:
            failures.append(repr(exc))

    with tempfile.TemporaryDirectory(prefix="voicepaste-e2e-") as runtime:
        os.environ["XDG_RUNTIME_DIR"] = runtime
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
        # keep the iterator responsive while commands are pending
        ticking = threading.Event()

        def tick():
            while not ticking.wait(0.05):
                if audio.empty():
                    audio.put(None)

        ticker = threading.Thread(target=tick, daemon=True)
        ticker.start()
        try:
            wait_for(lambda: any(e["event"] == "ready" for e in events), "listener ready")
            feed(synthesize("The weather is pleasant today."))
            silence(2)
            wait_for(lambda: audio.empty(), "idle audio consumed")
            assert control("status")["state"] == "idle"
            assert control("stop")["state"] == "idle"
            duplicate = subprocess.run(
                [sys.executable, "-m", "voicepaste", "listen"], capture_output=True, text=True, timeout=10
            )
            assert duplicate.returncode != 0
            assert control("status")["state"] == "idle"
            feed(synthesize("Start dictation. The blue notebook is on the table."))
            silence(2)
            wait_for(lambda: any(e["event"] == "recording" for e in events), "voice activation")
            assert not notifications
            silence(4)
            wait_for(lambda: len(notifications) == 1, "five second reminder")
            continued_speech = [
                "Please close the kitchen window before leaving.",
                "Put the spare keys beside the front door.",
                "Remember to charge the battery before the trip.",
                "Bring the printed schedule to the morning meeting.",
                "Our team will discuss the budget after lunch.",
                "The garden needs water every morning in summer.",
                "I left the umbrella beside the wooden chair.",
                "The train arrives at the station before sunset.",
                "We should buy fresh bread on the way home.",
                "There is a clean towel in the bathroom.",
                "The children are reading stories in the library.",
                "Please place the empty bottles in the basket.",
                "My bicycle needs a new chain this weekend.",
                "The restaurant serves warm soup in the evening.",
                "Our neighbor has planted flowers beside the fence.",
                "The camera is ready for the family portrait.",
                "This recipe requires flour and a little butter.",
                "The museum opens early on Saturday mornings.",
                "We can watch the sunrise from the balcony.",
                "Please leave the package beside the staircase.",
                "The orchestra will perform in the concert hall.",
                "I need a comfortable pillow for the journey.",
                "A small fountain stands in the central square.",
                "The final chapter explains the experiment clearly.",
            ]
            for sentence in continued_speech:
                feed(synthesize(sentence))
                silence(3)
            wait_for(lambda: audio.empty(), "long recording consumed")
            assert control("status")["state"] == "recording"
            assert notifications == ["You are still recording"]
            feed(synthesize("Please bring it tomorrow."))
            silence(6)
            wait_for(lambda: len(notifications) == 2, "reminder reset")
            feed(synthesize("Thank you."))
            silence(2)
            wait_for(lambda: len(transcripts) == 1, "voice stop transcript", timeout=90)
            assert next(e["seconds"] for e in events if e["event"] == "stopped") > 120
            first = transcripts[0].lower()
            assert "blue notebook" in first and "tomorrow" in first, first
            for word in ("window", "budget", "library", "camera", "balcony", "experiment"):
                assert word in first, first
            assert "remember to charge the battery" in first, first
            assert "there is a clean towel" in first, first
            assert "start dictation" not in first and "thank you" not in first, first
            wait_for(lambda: control("status")["state"] == "idle", "idle after delivery")
            assert control("toggle")["state"] == "recording"
            feed(synthesize("The shortcut can finish this recording."))
            silence(1)
            wait_for(lambda: audio.empty(), "shortcut audio consumed")
            assert [result["state"] for result in control_pair()] == ["transcribing", "transcribing"]
            wait_for(lambda: len(transcripts) == 2, "shortcut stop transcript", timeout=90)
            assert "shortcut" in transcripts[1].lower(), transcripts[1]
            wait_for(lambda: control("status")["state"] == "idle", "second session idle")
            feed(
                synthesize(
                    "Start dictation. "
                    "The first parcel contains a red notebook for the morning meeting. "
                    "The second parcel contains a green folder for the afternoon meeting. "
                    "The third parcel contains a blue pencil for the evening meeting. "
                    "The fourth parcel contains a yellow envelope for the weekly meeting. "
                    "The fifth parcel contains a silver ruler for the monthly meeting. "
                    "The sixth parcel contains a purple marker for the final meeting. Thank you."
                )
            )
            silence(2)
            wait_for(lambda: len(transcripts) == 3, "continuous speech across transcription chunks", timeout=90)
            third = transcripts[2].lower()
            for color in ("red", "green", "blue", "yellow", "silver", "purple"):
                assert third.count(color) == 1, third
            assert "start dictation" not in third and "thank you" not in third, third
            wait_for(lambda: control("status")["state"] == "idle", "third session idle")
            control("toggle")
            feed(synthesize("The silence timeout should finish this recording."))
            silence(4)
            wait_for(lambda: audio.empty(), "short pause consumed")
            assert control("status")["state"] == "recording"
            assert len(notifications) == 2
            silence(1.2)
            wait_for(lambda: len(notifications) == 3, "timeout session reminder")
            assert control("status")["state"] == "recording"
            silence(5.1)
            wait_for(lambda: len(transcripts) == 4, "ten second silence stop", timeout=90)
            assert "silence timeout" in transcripts[3].lower(), transcripts[3]
            stopped = [e for e in events if e["event"] == "stopped"][-1]
            assert stopped["trigger"] == "silence" and 10 <= stopped["silence_seconds"] <= 10.1, stopped
            wait_for(lambda: control("status")["state"] == "idle", "silence session idle")
            control("toggle")
            control("stop")
            wait_for(lambda: control("status")["state"] == "idle", "empty session idle")
            assert len(transcripts) == 4
            control("shutdown")
            thread.join(10)
            assert not thread.is_alive()
            assert not list(Path(runtime).rglob("*.sock"))
            assert not failures
            outcome = "passed"
        except BaseException:
            outcome = "failed"
            raise
        finally:
            ticking.set()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "outcome": outcome,
                        "events": events,
                        "notifications": notifications,
                        "transcripts": transcripts,
                        "failures": failures,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(report_path)


if __name__ == "__main__":
    main()
