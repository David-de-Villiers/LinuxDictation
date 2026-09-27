"""Continuous local listening, unlimited capture, and explicit recording controls."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Empty, Full, Queue
from typing import BinaryIO

import numpy as np

from voicepaste.config import Config
from voicepaste.control import ControlServer
from voicepaste.models import require_local_model
from voicepaste.notify import notify
from voicepaste.transcribe import RecordingTranscriber
from voicepaste.voice_commands import CommandRecognizer


@contextmanager
def microphone_frames(sample_rate: int) -> Iterator[Iterator[bytes | None]]:
    """Capture bounded audio blocks and report any input loss."""
    import sounddevice as sd

    queue: Queue[bytes] = Queue(maxsize=100)
    errors: list[str] = []

    def callback(data, count, timing, status):
        if status and not errors:
            errors.append(str(status))
        try:
            queue.put_nowait(bytes(data))
        except Full:
            if not errors:
                errors.append("audio processing fell behind")

    def frames():
        while True:
            if errors:
                raise RuntimeError(f"microphone input lost: {errors[0]}")
            try:
                yield queue.get(timeout=0.05)
            except Empty:
                yield None

    with sd.RawInputStream(
        samplerate=sample_rate, channels=1, dtype="int16", blocksize=sample_rate // 10, callback=callback
    ):
        yield frames()


class Listener:
    """Own capture state while transcription runs on a separate worker."""

    def __init__(
        self, cfg: Config, deliver: Callable[[str], object], announce: Callable[[str], object], event: Callable
    ) -> None:
        if cfg.record_sample_rate != 16000:
            raise ValueError("voice listener requires record_sample_rate = 16000")
        if cfg.listener.silence_reminder_seconds <= 0:
            raise ValueError("silence_reminder_seconds must be positive")
        if cfg.listener.silence_stop_seconds <= cfg.listener.silence_reminder_seconds:
            raise ValueError("silence_stop_seconds must exceed silence_reminder_seconds")
        require_local_model(cfg, cfg.shortcut.model_tier)
        self.cfg = cfg
        self.deliver = deliver
        self.announce = announce
        self.event = event
        self.commands = CommandRecognizer(cfg)
        self.transcriber = RecordingTranscriber(cfg)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voicepaste-transcribe")
        self.pending = None
        self.recording: BinaryIO | None = None
        self.position = 0
        self.start_position = 0
        self.ring = b""
        self.silent_samples = 0
        self.reminded = False
        self.running = True
        self.suspending = False
        self.deliver_paused = deliver

    @property
    def state(self) -> str:
        """Return the user-visible listener state."""
        if self.suspending:
            return "pausing"
        if self.recording is not None:
            return "recording"
        return "transcribing" if self.pending is not None else "idle"

    def start(self, position: int | None = None) -> None:
        """Start capture and retain speech following a delayed wake phrase."""
        if self.state != "idle":
            return
        self.recording = tempfile.TemporaryFile(prefix="voicepaste-recording-", mode="w+b")
        self.start_position = max(
            position if position is not None else self.position, self.position - len(self.ring) // 2
        )
        retained = (self.position - self.start_position) * 2
        if retained:
            self.recording.write(self.ring[-retained:])
        self.silent_samples = 0
        self.reminded = False
        self.event("recording", sample=self.start_position, trigger="voice" if position is not None else "shortcut")

    def stop(self, position: int | None = None, *, silence: bool = False) -> None:
        """Finish capture at the stop phrase or current shortcut position."""
        if self.recording is None:
            return
        recording = self.recording
        self.recording = None
        end = min(position if position is not None else self.position, self.position)
        samples = max(0, end - self.start_position)
        recording.truncate(samples * 2)
        details = {"seconds": samples / self.cfg.record_sample_rate}
        if silence:
            details["silence_seconds"] = self.silent_samples / self.cfg.record_sample_rate
        self.event(
            "stopped", trigger="silence" if silence else "voice" if position is not None else "shortcut", **details
        )
        self.commands.reset(self.position)
        self.ring = b""

        def transcribe():
            with recording:
                if samples < self.cfg.record_sample_rate // 5:
                    return ""
                return self.transcriber.transcribe(recording, samples)

        self.pending = self.worker.submit(transcribe)

    def control(self, command: str) -> dict:
        """Apply a shortcut, status request, or shutdown command."""
        if command == "toggle":
            if self.state == "recording":
                self.stop()
            elif self.state == "idle":
                self.commands.reset(self.position)
                self.start()
        elif command == "stop":
            self.stop()
        elif command == "shutdown":
            self.running = False
        elif command == "suspend":
            self.stop()
            self.suspending = True
            if self.pending is None:
                self.running = False
        elif command != "status":
            return {"error": f"unknown listener command: {command}"}
        return {"state": self.state}

    def finish_transcription(self) -> None:
        """Deliver completed text and recover after a failed transcription."""
        if self.pending is None or not self.pending.done():
            return
        try:
            text = self.pending.result()
            if text:
                if self.suspending:
                    self.deliver_paused(text)
                else:
                    self.deliver(text)
                self.event("transcript", text=text)
            else:
                self.event("empty")
        except Exception as exc:
            self.announce(f"VoicePaste error: {exc}")
            self.event("error", message=str(exc))
        finally:
            self.pending = None
            self.commands.reset(self.position)
            self.ring = b""
            self.event("idle")
            if self.suspending:
                self.running = False

    def feed(self, pcm: bytes) -> None:
        """Process one microphone block without imposing a duration limit."""
        samples = len(pcm) // 2
        self.position += samples
        if self.pending is not None:
            return
        self.ring = (self.ring + pcm)[-self.cfg.record_sample_rate * 20 :]
        if self.recording is not None:
            self.recording.write(pcm)
            values = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(values * values))) if values.size else 0.0
            if rms >= self.cfg.shortcut.vad_threshold:
                self.silent_samples = 0
                self.reminded = False
            else:
                self.silent_samples += samples
            if (
                not self.reminded
                and self.silent_samples > self.cfg.listener.silence_reminder_seconds * self.cfg.record_sample_rate
            ):
                self.reminded = True
                self.announce("You are still recording")
                self.event("silence-reminder", silence_seconds=self.silent_samples / self.cfg.record_sample_rate)
            if self.silent_samples >= self.cfg.listener.silence_stop_seconds * self.cfg.record_sample_rate:
                self.stop(silence=True)
                return
        for phrase in self.commands.feed(pcm):
            if phrase.text == self.cfg.listener.activation_phrase and self.state == "idle":
                self.start(phrase.end)
            elif phrase.text == self.cfg.listener.deactivation_phrase and self.state == "recording":
                self.stop(phrase.start)
                break

    def close(self) -> None:
        """Release microphone-session resources and temporary audio."""
        if self.recording is not None:
            self.recording.close()
        self.worker.shutdown(wait=True, cancel_futures=False)


def run_listener(
    cfg: Config,
    *,
    deliver: Callable[[str], object],
    deliver_paused: Callable[[str], object] | None = None,
    frames: Iterator[bytes | None] | None = None,
    announce: Callable[[str], object] = notify,
    event: Callable | None = None,
) -> None:
    """Run the local listener with microphone audio or an explicit replay source."""
    event = event or (lambda name, **details: None)
    with ControlServer() as server:
        listener = Listener(cfg, deliver, announce, event)
        listener.deliver_paused = deliver_paused or deliver
        try:

            def run(source):
                event("ready")
                for frame in source:
                    server.poll(listener.control)
                    if not listener.running:
                        break
                    listener.finish_transcription()
                    if frame:
                        listener.feed(frame)

            if frames is None:
                with microphone_frames(cfg.record_sample_rate) as source:
                    event("ready")
                    for frame in source:
                        server.poll(listener.control)
                        if not listener.running or listener.suspending:
                            break
                        listener.finish_transcription()
                        if frame:
                            listener.feed(frame)
                while listener.running and listener.suspending:
                    import time

                    server.poll(listener.control)
                    listener.finish_transcription()
                    time.sleep(0.05)
            else:
                run(frames)
        finally:
            listener.close()
