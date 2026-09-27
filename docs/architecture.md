# VoicePaste Architecture

VoicePaste is intentionally split into small modules so recording, transcription, desktop insertion, and CLI concerns can evolve independently.

## Runtime Flow

1. `voicepaste.cli` parses options and chooses the interactive recorder, one-shot immediate recorder, or continuous voice listener.
2. `voicepaste.audio` records local microphone audio to a temporary WAV file.
3. `voicepaste.transcribe` loads a locally cached faster-whisper model and transcribes the WAV file.
4. `voicepaste.postprocess` normalizes whitespace and applies deterministic glossary replacements.
5. `voicepaste.state` stores the final transcript as local `paste-last` state.
6. `voicepaste.insert` copies text to the clipboard and attempts focused-window paste.
7. `voicepaste.clipboard` handles X11/Wayland clipboard tools.
8. `voicepaste.notify` sends best-effort desktop notifications.

## Continuous Listener

`voicepaste listen` owns one microphone stream and one private Unix control socket. `voice_commands.py` uses a cached Vosk model to recognize “start dictation” and “thank you” with sample timestamps. `listener.py` retains a short rolling buffer to recover speech following delayed activation, spools active PCM into an anonymous temporary file, and trims the stop phrase before transcription. Capture has no duration cap. After more than five seconds of silence it emits one reminder; at ten seconds it stops and transcribes automatically. Speech resets both timers.

`control.py` holds a process lock for the socket lifetime. GNOME launches `voicepaste toggle` on Ctrl+backtick; active recording stops, idle listening starts capture, and transcription continues through repeated shortcut requests. A worker uses a reusable Whisper model to transcribe chunks split at pauses, with overlapping context for continuous speech. The capture loop continues handling controls during transcription. `service.py` installs a user service tied to the graphical login session.

## Module Boundaries

- `audio.py`: microphone capture, WAV writing, WAV inspection, silence calibration.
- `vad.py`: pure RMS-based silence detection that can be unit tested with synthetic arrays.
- `transcribe.py`: local ASR backend selection and faster-whisper invocation.
- `models.py`: model cache paths and setup-time model download.
- `postprocess.py`: transcript cleanup and glossary replacements.
- `insert.py`: desktop session detection and paste simulation.
- `clipboard.py`: command-line clipboard integration.
- `diagnostics.py`: environment and dependency checks for `voicepaste doctor`.
- `config.py`: XDG paths, defaults, and typed config dataclasses.
- `cli.py`: command-line interface and orchestration.

## Privacy Invariants

- Audio and transcription are local after model download.
- Raw audio is written only to temporary files and deleted by default.
- `paste-last` state stores only the final transcript locally.
- No cloud ASR, telemetry, remote correction, or hosted logging is called by the app.

## Testing Strategy

The existing checks cover configuration, formatting, and one-shot behavior. Voice control is verified by `tests/e2e/voice_control.py`, which replays local synthesized speech through actual Vosk and Whisper models and exercises the Unix socket from CLI subprocesses. The repeatable JSON artifact contains detected events, reminders, and transcripts. Desktop installation and microphone capture are checked separately in the user session.
