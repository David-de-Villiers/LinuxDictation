# Changelog

## Unreleased

- Add local “start dictation” activation and “thank you” stopping with Vosk phrase recognition.
- Make the Ctrl+backtick shortcut toggle unlimited recording through a singleton background listener.
- Show “You are still recording” after five seconds of silence, then stop and transcribe automatically at ten seconds.
- Add a graphical-session user service, bounded audio transcription, and a repeatable voice-control replay report.
- Preserve process exit codes when running `python -m voicepaste`.

## 0.1.0 - Initial Public Release

- Local/offline dictation CLI for Linux.
- Records microphone audio locally and transcribes with `faster-whisper`.
- Supports CPU and CUDA transcription when available.
- Inserts text into focused X11 applications via clipboard plus `xdotool`.
- Provides clipboard fallback, desktop notifications, and `paste-last`.
- Adds technical dictation glossary and initial prompt support.
- Adds GNOME shortcut-friendly immediate recording with RMS silence detection.
- Includes diagnostics, benchmark, record/transcribe test, quality-test, and compare-models commands.
