import tomllib
from pathlib import Path

from voicepaste.cli import _write_vad_threshold, build_parser, cmd_run, shortcut_script_text
from voicepaste.notify import notify
from voicepaste.transcribe import TranscriptionResult


def test_parser_accepts_immediate_silence_options():
    args = build_parser().parse_args(
        [
            "--immediate",
            "--stop-on-silence",
            "--silence-seconds",
            "1.4",
            "--max-seconds",
            "20",
            "--min-seconds",
            "2",
            "--vad-threshold",
            "0.02",
        ]
    )
    assert args.immediate is True
    assert args.stop_on_silence is True
    assert args.silence_seconds == 1.4
    assert args.max_seconds == 20
    assert args.min_seconds == 2
    assert args.vad_threshold == 0.02


def test_shortcut_script_generation():
    text = shortcut_script_text("/tmp/voicepaste --immediate --quiet")
    assert text.startswith("#!/usr/bin/env sh\n")
    assert "exec /tmp/voicepaste --immediate --quiet" in text
    assert '"$@"' in text


def test_calibration_writes_threshold_to_shortcut_table(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "voicepaste" / "config.toml"
    path.parent.mkdir()
    path.write_text('[models]\nfast = "local-fast-model"\nvad_threshold = 0.00999\n')

    written = _write_vad_threshold(0.01234)
    with written.open("rb") as config_file:
        raw = tomllib.load(config_file)

    assert raw["models"] == {"fast": "local-fast-model"}
    assert raw["shortcut"]["vad_threshold"] == 0.01234


def test_notification_failures_are_non_fatal(monkeypatch):
    monkeypatch.setattr("voicepaste.notify.shutil.which", lambda name: "/usr/bin/notify-send")

    def fail(*args, **kwargs):
        raise OSError("no display")

    monkeypatch.setattr("voicepaste.notify.subprocess.run", fail)
    assert notify("hello") is False


def test_terminal_workflow_still_uses_enter_recording(monkeypatch, tmp_path):
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"fake")
    calls = []
    monkeypatch.setattr("voicepaste.cli.audio.record_until_enter", lambda sample_rate, max_seconds: calls.append((sample_rate, max_seconds)) or audio_file)
    monkeypatch.setattr("voicepaste.cli.audio.validate_audio", lambda path: type("Stats", (), {"duration_seconds": 1.0})())
    monkeypatch.setattr("voicepaste.cli.transcribe_file", lambda *args, **kwargs: TranscriptionResult("hello", 0.1, "faster-whisper", Path("/model"), "cpu", "int8"))
    monkeypatch.setattr("voicepaste.cli._handle_transcript", lambda text, options: 0)
    args = build_parser().parse_args([])

    assert cmd_run(args) == 0
    assert calls == [(16000, 120)]


def test_immediate_workflow_uses_vad_recording(monkeypatch, tmp_path):
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"fake")
    calls = []
    notifications = []

    def fake_record(sample_rate, **kwargs):
        calls.append((sample_rate, kwargs))
        return type("Recording", (), {"path": audio_file, "reason": "silence", "duration_seconds": 2.0})()

    monkeypatch.setattr("voicepaste.cli.audio.record_immediate", fake_record)
    monkeypatch.setattr("voicepaste.cli.audio.validate_audio", lambda path: type("Stats", (), {"duration_seconds": 2.0})())
    monkeypatch.setattr("voicepaste.cli.transcribe_file", lambda *args, **kwargs: TranscriptionResult("hello", 0.1, "faster-whisper", Path("/model"), "cpu", "int8"))
    monkeypatch.setattr("voicepaste.cli._handle_transcript", lambda text, options: 0)
    monkeypatch.setattr("voicepaste.cli.notify", lambda message: notifications.append(message))
    args = build_parser().parse_args(["--immediate", "--stop-on-silence", "--max-seconds", "12", "--min-seconds", "1.5"])

    assert cmd_run(args) == 0
    assert calls[0][0] == 16000
    assert calls[0][1]["stop_on_silence"] is True
    assert calls[0][1]["max_seconds"] == 12.0
    assert calls[0][1]["min_seconds"] == 1.5
    assert notifications == []
