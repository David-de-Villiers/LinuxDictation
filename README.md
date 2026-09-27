# VoicePaste

VoicePaste is a local/offline Linux dictation CLI. It records microphone audio, transcribes it locally with `faster-whisper`, and inserts the resulting text into the currently focused application when the desktop permits it.

VoicePaste supports terminal dictation and a local background listener with voice activation and a desktop shortcut. Audio recognition and text cleanup run on your computer.

## Features

- Local speech-to-text after model download.
- CPU and CUDA transcription support through `faster-whisper`.
- X11 focused-window insertion using clipboard plus `xdotool`.
- Clipboard fallback and `paste-last`, with desktop notifications for errors.
- Local “start dictation” activation and “thank you” stopping.
- Ctrl+backtick toggling through the GNOME shortcut and graphical-login listener service.
- Unlimited recording duration while speaking, a five-second silence reminder, and automatic completion at ten seconds.
- Technical dictation glossary and faster-whisper initial prompt support.
- Diagnostics, recording test, transcription test, benchmark, quality test, and model comparison commands.

## Platform Support

Current first target:

- Ubuntu 24.04
- X11
- PipeWire/ALSA default microphone capture
- `xdotool` plus `xclip` or `xsel` for insertion
- NVIDIA CUDA when the local driver and CTranslate2 support it

Wayland support is limited. VoicePaste reports Wayland-related tool availability, but compositor restrictions can prevent focused insertion. Clipboard fallback is expected on many Wayland sessions.

## Privacy And Safety

- Audio is recorded and transcribed locally.
- Raw audio is written to temporary files and deleted by default.
- Transcripts are printed locally and saved as local `paste-last` state. The user service also writes its output to the local systemd journal.
- No cloud ASR, LLM cleanup, telemetry, or remote logging is used by VoicePaste.
- Downloading ASR models is the setup-time network step.
- Review model licences and trust properties separately before downloading models.
- Desktop insertion depends on your Linux session and installed tools.

## Requirements

System packages for Ubuntu/X11:

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev ffmpeg libportaudio2 portaudio19-dev libnotify-bin xdotool xclip xsel
```

Use a system Python virtual environment. Conda can expose an incompatible `libstdc++` to PortAudio/JACK on Ubuntu.

## Install

```bash
/usr/bin/python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
voicepaste models fetch --tier cpu
```

Run diagnostics:

```bash
voicepaste doctor
```

## Quick Start

Interactive terminal dictation:

```bash
voicepaste
```

Press Enter to start recording, press Enter again to stop, then VoicePaste transcribes and pastes.

Voice-activated dictation:

```bash
voicepaste models fetch-commands
voicepaste install-listener
```

Say “start dictation” to begin and “thank you” to finish. Bind Ctrl+backtick to `~/.local/bin/voicepaste-dictate` for keyboard control. The [voice activation section](#voice-activation-and-gnome-shortcut) describes silence reminders and service controls.

Copy without pasting:

```bash
voicepaste --copy-only
voicepaste --no-paste
```

Reuse the last transcript:

```bash
voicepaste paste-last
```

## Technical Dictation

VoicePaste uses two local, deterministic quality aids:

- `initial_prompt` is passed to faster-whisper to bias recognition toward technical terms such as Bayesian networks, conditional independence, d-separation, expected utility, and LaTeX.
- `[glossary.replacements]` runs after ASR to fix recurring terms without an LLM or network call.

Quality test:

```bash
voicepaste quality-test --seconds 10 --device cuda --model-tier small
```

Example glossary correction:

```text
raw_transcript=... de-separation and latex ...
final_transcript=... d-separation and LaTeX ...
```

Compare model tiers using one recording:

```bash
voicepaste compare-models --tiers fast,cpu --seconds 10 --device cuda
```

Model tier and device are separate:

- `--model-tier` selects the ASR model size/profile.
- `--device` selects where inference runs: `cpu`, `cuda`, or `auto`.
- `cpu` is retained as a backward-compatible tier alias for the original small CPU-safe model. Prefer `small` in new commands and configs.

For an RTX 3070 Ti Laptop GPU, start with:

```bash
voicepaste --device cuda --model-tier small
```

For higher accuracy when latency is acceptable:

```bash
voicepaste models fetch --tier accuracy
voicepaste --device cuda --model-tier accuracy
```

## Voice Activation and GNOME Shortcut

Say **“start dictation”** to begin recording. Say **“thank you”** or press **Ctrl+backtick** to stop and paste the transcript into the focused application. Ctrl+backtick also starts recording while idle. The listener returns to waiting for the activation phrase after each transcript.

Recording has no duration limit while you continue speaking. After more than five seconds of silence, a desktop popup says **“You are still recording”**. At ten seconds of silence, recording ends and the transcript is pasted automatically. The reminder appears once per silent stretch. Speaking again resets both timers. Command phrases are removed using their audio timestamps. Saying “thank you” within dictated speech also ends the recording.

Install dependencies and download the command model once:

```bash
python -m pip install -e .
voicepaste models fetch-commands
```

The listener uses [Vosk](https://alphacephei.com/vosk/models) for local command recognition and the configured Whisper model for final transcription. Both run offline after model download. The listener requires 16 kHz recording and uses `[shortcut].device`, `[shortcut].model_tier`, and `[shortcut].vad_threshold`. Calibrate the microphone threshold with `voicepaste calibrate-silence --write` if needed.

Run the listener in a terminal:

```bash
voicepaste listen
```

Or enable it for graphical login:

```bash
voicepaste install-listener
```

This installs and starts `voicepaste-listener.service` for your user and writes `~/.local/bin/voicepaste-dictate`. In GNOME Settings → Keyboard → Custom Shortcuts, bind **Ctrl+backtick** to that helper. Existing shortcuts targeting the helper automatically use the new toggle behavior. `voicepaste install-shortcut --dry-run` prints the equivalent command.

Useful controls:

```bash
voicepaste status
voicepaste toggle
voicepaste stop
systemctl --user stop voicepaste-listener.service
systemctl --user disable --now voicepaste-listener.service
```

`stop` finishes an active recording and leaves the listener available. Stopping the service discards an unfinished recording and releases the microphone. Shortcuts received during transcription leave that transcription running. An empty recording leaves the previous transcript and clipboard intact. Clipboard fallback remains available when focused insertion fails.

Idle audio stays in a short memory buffer. Active audio spools to an anonymous temporary file and is removed when the session finishes or the process exits. Final transcription splits audio at nearby pauses and uses overlapping context when speech continues across a chunk boundary, keeping audio memory bounded. Available temporary storage sets the practical capacity for long recordings.

The original `voicepaste --immediate --stop-on-silence` command remains available for one-shot recording; its silence and duration limits are separate from listener mode.

## Configuration

Config is stored at:

```text
~/.config/voicepaste/config.toml
```

Default shape:

```toml
backend = "faster-whisper"
model_tier = "cpu"
language = "en"
record_sample_rate = 16000
max_record_seconds = 120
delete_audio = true
initial_prompt = "Bayesian networks, conditional independence, d-separation, expected utility, LaTeX, probabilistic graphical models, posterior, prior, likelihood, inference."

[insertion]
prefer_clipboard_paste = true
restore_clipboard = false
paste_key = "ctrl+v"

[models]
fast = "Systran/faster-whisper-small.en"
small = "Systran/faster-whisper-small.en"
cpu = "Systran/faster-whisper-small.en"
accuracy = "Systran/faster-whisper-large-v3-turbo"

[glossary]
enabled = true

[glossary.replacements]
"de-separation" = "d-separation"
"D separation" = "d-separation"
"d separation" = "d-separation"
latex = "LaTeX"
"bayesian network" = "Bayesian network"
"bayesian networks" = "Bayesian networks"

[shortcut]
device = "cuda"
model_tier = "cpu"
immediate = true
stop_on_silence = true
silence_seconds = 1.2
max_seconds = 30
min_seconds = 1
vad_threshold = 0.01
pre_speech_padding_ms = 200
post_speech_padding_ms = 300

[listener]
activation_phrase = "start dictation"
deactivation_phrase = "thank you"
silence_reminder_seconds = 5
silence_stop_seconds = 10
command_model = "vosk-model-small-en-us-0.15"
```

Clipboard restore is off by default. If `restore_clipboard = true`, VoicePaste reads the current clipboard, pastes the transcript, then attempts to restore the previous clipboard content after paste.

## CUDA Notes

Keep `model_tier = "cpu"` or `model_tier = "small"` as the default until `voicepaste doctor` confirms CUDA works.

```bash
voicepaste transcribe-test --device cuda --tier cpu
voicepaste benchmark --device cuda --tier cpu
```

If CUDA is unavailable, use:

```bash
voicepaste --device cpu --model-tier cpu
```

## Troubleshooting

- Conda / `GLIBCXX`: if recording fails with a PortAudio/JACK error mentioning `GLIBCXX_3.4.32`, recreate `.venv` with `/usr/bin/python3`, deactivate Conda, and remove Miniconda/Anaconda paths from `LD_LIBRARY_PATH`.
- PortAudio/JACK: install `libportaudio2` and `portaudio19-dev`, then run `voicepaste record-test`.
- CUDA unavailable: run `voicepaste doctor`; if CUDA probes fail, use `--device cpu` until the NVIDIA driver and CTranslate2 CUDA support work.
- Wayland: focused insertion is compositor-dependent. Prefer clipboard fallback unless your compositor and tools support synthetic paste.
- X11 insertion: install `xdotool` and `xclip` or `xsel`.
- `xclip`: on X11, `xclip` intentionally remains alive as clipboard owner. VoicePaste starts it without waiting, so the CLI should not hang.
- Raw audio: temporary recordings are deleted by default. Test commands keep samples only when passed `--keep`.

## Development

```bash
/usr/bin/python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
python -m compileall src tests
pytest -q
```

Optional lint:

```bash
ruff check .
```

See [docs/architecture.md](docs/architecture.md) for the module boundaries and privacy invariants.

Hardware-facing commands:

```bash
voicepaste doctor
voicepaste record-test
voicepaste transcribe-test --seconds 5
voicepaste benchmark --seconds 8
voicepaste install-shortcut --dry-run
```

CI runs compilation and the existing automated checks. It does not require a microphone, GPU, display server, CUDA, desktop insertion tools, or downloaded ASR models.

## Current Limitations

- Linux/Ubuntu is the first target.
- X11 insertion is validated; Wayland focused insertion is limited.
- ASR quality depends on the downloaded model, microphone, room noise, and hardware.
- Voice control runs as a local background service; final transcripts are produced when recording stops.
- Desktop shortcuts use GNOME keybindings. A tray interface and live transcript display are future work.

## License

MIT. See [LICENSE](LICENSE).

## Voice Control Replay

Run the end-to-end replay with local Vosk and Whisper models installed, CUDA available, and the system `libespeak-ng.so.1` library:

```bash
.venv/bin/python tests/e2e/voice_control.py /tmp/voicepaste-e2e.json
```

The replay uses synthesized audio and an isolated control socket, records notification events, and captures transcripts without pasting into desktop applications. Its JSON artifact reports phrase activation, voice and shortcut stopping, a recording exceeding two minutes, continuous speech across transcription chunks, reminders, automatic stopping after ten seconds of silence, singleton protection, and shutdown cleanup. The latest passing [validation report](docs/validation/voice-control-e2e.json) contains the recognized text and timing evidence. Failure cases are listed in `tests/e2e/voice_control_failures.md`.
