"""Command-line interface for VoicePaste.

This module wires the user-facing commands to the smaller VoicePaste modules
that handle audio capture, transcription, insertion, clipboard fallback,
notifications, configuration, and local model management.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__, audio, clipboard
from .config import load_config, write_default_config
from .diagnostics import collect_diagnostics, format_checks
from .insert import insert_or_copy
from .models import fetch_model
from .notify import notify
from .postprocess import cleanup_text, final_transcript
from .state import read_last_transcript, save_last_transcript
from .transcribe import transcribe_file


@dataclass(frozen=True)
class RuntimeOptions:
    """Runtime overrides shared by dictation and transcript handling commands."""

    paste: bool = True
    quiet: bool = False
    verbose: bool = False
    notify_errors: bool = False
    language: str | None = None
    model_tier: str | None = None
    device: str = "auto"


def _runtime_options(args: argparse.Namespace) -> RuntimeOptions:
    """Build behavior flags from parsed CLI arguments."""

    no_paste = bool(getattr(args, "no_paste", False))
    copy_only = bool(getattr(args, "copy_only", False))
    return RuntimeOptions(
        paste=not (no_paste or copy_only),
        quiet=bool(getattr(args, "quiet", False)),
        verbose=bool(getattr(args, "verbose", False)),
        notify_errors=bool(getattr(args, "immediate", False)),
        language=getattr(args, "language", None),
        model_tier=getattr(args, "model_tier", None) or getattr(args, "tier", None),
        device=getattr(args, "device", "auto"),
    )


def _handle_transcript(text: str, options: RuntimeOptions | None = None) -> int:
    """Normalize, persist, print, and deliver a transcript.

    Args:
        text: Raw transcription text from the ASR backend.
        options: Runtime delivery options. Defaults to normal paste behavior.

    Returns:
        Process exit status.
    """

    options = options or RuntimeOptions()
    cfg = load_config()
    text = final_transcript(text, cfg)
    save_last_transcript(text)
    if not options.quiet:
        print(text)
    if options.paste:
        result = insert_or_copy(text, cfg.insertion)
        if result.inserted:
            print(f"[voicepaste] inserted ({result.message})", file=sys.stderr)
        elif result.copied:
            print(f"[voicepaste] copied fallback ({result.message})", file=sys.stderr)
        else:
            print(f"[voicepaste] fallback without clipboard ({result.message})", file=sys.stderr)
            if options.notify_errors:
                notify(f"Could not paste or copy: {result.message}")
        return 0
    from .insert import session_type

    copied, message = clipboard.copy_text(text, session_type())
    if copied:
        print(f"[voicepaste] copied ({message}); paste skipped", file=sys.stderr)
    else:
        print(f"[voicepaste] clipboard unavailable ({message}); paste skipped", file=sys.stderr)
        if options.notify_errors:
            notify(f"Could not copy transcription: {message}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Print diagnostics for local hardware, desktop, audio, and ASR support."""

    write_default_config()
    cfg = load_config()
    print(format_checks(collect_diagnostics(cfg)))
    return 0


def cmd_record_test(args: argparse.Namespace) -> int:
    """Record a short local sample and validate that capture produced audio."""

    cfg = load_config()
    path = audio.record_fixed(args.seconds, cfg.record_sample_rate)
    try:
        stats = audio.validate_audio(path)
        print(f"Recorded {stats.duration_seconds:.2f}s, rms={stats.rms:.6f}, sample_rate={stats.sample_rate}, path={path}")
        if args.play:
            import subprocess

            subprocess.run(["aplay", str(path)], check=False)
        return 0
    finally:
        if not args.keep and path.exists():
            path.unlink()


def cmd_transcribe_test(args: argparse.Namespace) -> int:
    """Transcribe a temporary or user-provided test recording."""

    cfg = load_config()
    options = _runtime_options(args)
    path = Path(args.file) if args.file else audio.record_fixed(args.seconds, cfg.record_sample_rate)
    owned = args.file is None
    try:
        audio.validate_audio(path, min_rms=0.0)
        result = transcribe_file(path, cfg, tier=options.model_tier, device=options.device, language=options.language)
        print(final_transcript(result.text, cfg))
        print(
            f"[voicepaste] backend={result.backend} device={result.device} compute={result.compute_type} "
            f"elapsed={result.duration_seconds:.2f}s model={result.model_path}",
            file=sys.stderr,
        )
        return 0
    finally:
        if owned and not args.keep and path.exists():
            path.unlink()


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Measure local transcription speed for a recorded or provided sample."""

    cfg = load_config()
    options = _runtime_options(args)
    path = Path(args.file) if args.file else audio.record_fixed(args.seconds, cfg.record_sample_rate)
    owned = args.file is None
    try:
        stats = audio.inspect_wav(path)
        result = transcribe_file(path, cfg, tier=options.model_tier, device=options.device, language=options.language)
        rtf = result.duration_seconds / stats.duration_seconds if stats.duration_seconds else 0.0
        print(f"audio_seconds={stats.duration_seconds:.2f}")
        print(f"transcribe_seconds={result.duration_seconds:.2f}")
        print(f"realtime_factor={rtf:.2f}")
        print(f"backend={result.backend}")
        print(f"device={result.device}")
        print(f"compute_type={result.compute_type}")
        print(f"model={result.model_path}")
        return 0
    finally:
        if owned and not args.keep and path.exists():
            path.unlink()


def cmd_quality_test(args: argparse.Namespace) -> int:
    """Show raw and normalized transcripts for a single local sample."""

    cfg = load_config()
    options = _runtime_options(args)
    path = Path(args.file) if getattr(args, "file", None) else audio.record_fixed(args.seconds, cfg.record_sample_rate)
    owned = getattr(args, "file", None) is None
    try:
        stats = audio.validate_audio(path, min_rms=0.0)
        result = transcribe_file(path, cfg, tier=options.model_tier, device=options.device, language=options.language)
        final = final_transcript(result.text, cfg)
        print(f"audio_seconds={stats.duration_seconds:.2f}")
        print(f"raw_transcript={cleanup_text(result.text)}")
        print(f"final_transcript={final}")
        print(f"elapsed_seconds={result.duration_seconds:.2f}")
        print(f"device={result.device}")
        print(f"compute_type={result.compute_type}")
        print(f"model={result.model_path}")
        return 0
    finally:
        if owned and not args.keep and path.exists():
            path.unlink()


def _parse_tiers(value: str) -> list[str]:
    """Parse and validate a comma-separated model tier list."""

    tiers = [tier.strip() for tier in value.split(",") if tier.strip()]
    valid = {"fast", "small", "cpu", "accuracy"}
    unknown = [tier for tier in tiers if tier not in valid]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown tier(s): {', '.join(unknown)}")
    if not tiers:
        raise argparse.ArgumentTypeError("at least one tier is required")
    return tiers


def cmd_compare_models(args: argparse.Namespace) -> int:
    """Transcribe one sample with multiple model tiers for quality comparison."""

    cfg = load_config()
    options = _runtime_options(args)
    tiers = _parse_tiers(args.tiers)
    path = Path(args.file) if getattr(args, "file", None) else audio.record_fixed(args.seconds, cfg.record_sample_rate)
    owned = getattr(args, "file", None) is None
    try:
        stats = audio.validate_audio(path, min_rms=0.0)
        print(f"audio={path}")
        print(f"audio_seconds={stats.duration_seconds:.2f}")
        for tier in tiers:
            result = transcribe_file(path, cfg, tier=tier, device=options.device, language=options.language)
            final = final_transcript(result.text, cfg)
            rtf = result.duration_seconds / stats.duration_seconds if stats.duration_seconds else 0.0
            print(f"tier={tier}")
            print(f"raw_transcript={cleanup_text(result.text)}")
            print(f"final_transcript={final}")
            print(f"elapsed_seconds={result.duration_seconds:.2f}")
            print(f"realtime_factor={rtf:.2f}")
            print(f"device={result.device}")
            print(f"compute_type={result.compute_type}")
            print(f"model={result.model_path}")
        return 0
    finally:
        if owned and not args.keep and path.exists():
            path.unlink()


def cmd_paste_last(args: argparse.Namespace) -> int:
    """Paste or copy the most recently saved transcript."""

    text = read_last_transcript()
    if not text:
        print("No last transcript found.", file=sys.stderr)
        return 1
    return _handle_transcript(text, _runtime_options(args))


def cmd_models_fetch(args: argparse.Namespace) -> int:
    """Download the selected model tier into local model storage."""

    cfg = load_config()
    path = fetch_model(cfg, args.tier)
    print(path)
    return 0


def _shortcut_value(value, default):
    """Return a CLI override when provided, otherwise use the shortcut default."""

    return default if value is None else value


def cmd_run(args: argparse.Namespace) -> int:
    """Run the default dictation flow.

    The terminal workflow records until Enter is pressed. The shortcut workflow
    starts immediately and can stop on silence or a maximum duration.
    """

    cfg = load_config()
    options = _runtime_options(args)
    if getattr(args, "immediate", False):
        shortcut = cfg.shortcut
        model_tier = options.model_tier or shortcut.model_tier
        device = options.device if options.device != "auto" else shortcut.device
        options = RuntimeOptions(
            paste=options.paste,
            quiet=options.quiet,
            verbose=options.verbose,
            notify_errors=True,
            language=options.language,
            model_tier=model_tier,
            device=device,
        )
        silence_seconds = _shortcut_value(args.silence_seconds, shortcut.silence_seconds)
        max_seconds = _shortcut_value(args.max_seconds, shortcut.max_seconds)
        min_seconds = _shortcut_value(args.min_seconds, shortcut.min_seconds)
        vad_threshold = _shortcut_value(args.vad_threshold, shortcut.vad_threshold)
        stop_on_silence = bool(getattr(args, "stop_on_silence", False) or shortcut.stop_on_silence)
        recording = audio.record_immediate(
            cfg.record_sample_rate,
            stop_on_silence=stop_on_silence,
            silence_seconds=float(silence_seconds),
            max_seconds=float(max_seconds),
            min_seconds=float(min_seconds),
            vad_threshold=float(vad_threshold),
        )
        path = recording.path
        if options.verbose:
            stop_message = f"stopped: {recording.reason} after {recording.duration_seconds:.2f}s"
            print(f"[voicepaste] {stop_message}", file=sys.stderr)
    else:
        path = audio.record_until_enter(cfg.record_sample_rate, cfg.max_record_seconds)
    try:
        stats = audio.validate_audio(path)
        print(f"[voicepaste] captured {stats.duration_seconds:.2f}s; transcribing...", file=sys.stderr)
        result = transcribe_file(path, cfg, tier=options.model_tier, device=options.device, language=options.language)
        return _handle_transcript(result.text, options)
    finally:
        if cfg.delete_audio and path.exists():
            path.unlink()


def recommended_shortcut_command() -> str:
    """Build the recommended command for a GNOME custom keyboard shortcut."""

    import shlex

    return f"{shlex.quote(sys.executable)} -m voicepaste toggle"


def cmd_listen(args: argparse.Namespace) -> int:
    """Listen locally for activation phrases and shortcut controls."""
    import signal

    from .listener import run_listener

    def terminate(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, terminate)
    options = RuntimeOptions(paste=not args.copy_only, notify_errors=True)

    def event(name, **details):
        print(f"[voicepaste] {name}", file=sys.stderr, flush=True)

    try:
        run_listener(load_config(), deliver=lambda text: _handle_transcript(text, options), event=event)
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


def cmd_control(args: argparse.Namespace) -> int:
    """Control the listener from a desktop shortcut or terminal."""
    import json

    from .control import send_control

    print(json.dumps(send_control(args.command)))
    return 0


def cmd_fetch_commands(args: argparse.Namespace) -> int:
    """Install the local voice-command recognition model."""
    from .models import fetch_command_model

    print(fetch_command_model(load_config()))
    return 0


def cmd_install_listener(args: argparse.Namespace) -> int:
    """Enable voice activation at graphical login and update the shortcut helper."""
    from .service import install_listener

    print(install_listener(load_config()))
    return 0


def shortcut_script_text(command: str | None = None) -> str:
    """Render the shell wrapper used by ``install-shortcut --write-script``."""

    command = command or recommended_shortcut_command()
    return "#!/usr/bin/env sh\nexec " + command + ' "$@"\n'


def cmd_install_shortcut(args: argparse.Namespace) -> int:
    """Print shortcut setup instructions and optionally write a helper script."""

    command = recommended_shortcut_command()
    print("Recommended GNOME custom shortcut command:")
    print(command)
    print()
    print("GNOME setup:")
    print("1. Open Settings -> Keyboard -> View and Customize Shortcuts -> Custom Shortcuts.")
    print("2. Add a shortcut named VoicePaste Dictate.")
    print("3. Bind it to the command above, or use ~/.local/bin/voicepaste-dictate after --write-script.")
    if args.write_script:
        target = Path.home() / ".local" / "bin" / "voicepaste-dictate"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shortcut_script_text(command), encoding="utf-8")
        target.chmod(0o755)
        print()
        print(f"Wrote {target}")
    return 0


def _write_vad_threshold(value: float) -> Path:
    """Persist a calibrated VAD threshold in the user config file."""

    path = write_default_config()
    lines = path.read_text(encoding="utf-8").splitlines()
    line = f"vad_threshold = {value:.5f}"

    section = ""
    cleaned_lines = []
    for item in lines:
        stripped = item.strip()
        if stripped.startswith("["):
            section = stripped
        if stripped.startswith("vad_threshold =") and section != "[shortcut]":
            continue
        cleaned_lines.append(item)
    lines = cleaned_lines

    shortcut_start = next((index for index, item in enumerate(lines) if item.strip() == "[shortcut]"), None)
    if shortcut_start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.extend(("[shortcut]", line))
    else:
        shortcut_end = next(
            (
                index
                for index in range(shortcut_start + 1, len(lines))
                if lines[index].lstrip().startswith("[")
            ),
            len(lines),
        )
        threshold_index = next(
            (
                index
                for index in range(shortcut_start + 1, shortcut_end)
                if lines[index].strip().startswith("vad_threshold =")
            ),
            None,
        )
        if threshold_index is None:
            insertion_index = shortcut_end
            while insertion_index > shortcut_start + 1 and not lines[insertion_index - 1].strip():
                insertion_index -= 1
            lines.insert(insertion_index, line)
        else:
            lines[threshold_index] = line

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_calibrate_silence(args: argparse.Namespace) -> int:
    """Measure ambient noise and suggest a silence-detection threshold."""

    cfg = load_config()
    rms, threshold, path = audio.calibrate_noise(args.seconds, cfg.record_sample_rate)
    try:
        print(f"ambient_rms={rms:.6f}")
        print(f"suggested_vad_threshold={threshold:.5f}")
        print("Config:")
        print(f"[shortcut]\nvad_threshold = {threshold:.5f}")
        if args.write:
            written = _write_vad_threshold(threshold)
            print(f"wrote={written}")
        return 0
    finally:
        if not args.keep and path.exists():
            path.unlink()


def build_parser() -> argparse.ArgumentParser:
    """Create the VoicePaste argument parser and register subcommands."""

    tier_choices = ["fast", "small", "cpu", "accuracy"]
    parser = argparse.ArgumentParser(prog="voicepaste")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--no-paste", action="store_true", help="copy and print transcript without simulating paste")
    parser.add_argument("--copy-only", action="store_true", help="copy and print transcript without simulating paste")
    parser.add_argument("--quiet", action="store_true", help="do not print the final transcript")
    parser.add_argument("--language", default=None, help="transcription language override, for example en")
    parser.add_argument("--model-tier", choices=tier_choices, help="model tier override")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="transcription device override")
    parser.add_argument("--immediate", action="store_true", help="start recording immediately without terminal prompts")
    parser.add_argument("--stop-on-silence", action="store_true", help="stop immediate recording after sustained silence")
    parser.add_argument("--silence-seconds", type=float, default=None, help="silence duration before stopping immediate recording")
    parser.add_argument("--max-seconds", type=float, default=None, help="maximum immediate recording duration")
    parser.add_argument("--min-seconds", type=float, default=None, help="minimum immediate recording duration before silence stop")
    parser.add_argument("--vad-threshold", type=float, default=None, help="RMS threshold below which audio is treated as silence")
    parser.add_argument("--verbose", action="store_true", help="print extra recording stop details")
    sub = parser.add_subparsers(dest="command")

    listen = sub.add_parser("listen", help="listen for start dictation and thank you, with unlimited recording")
    listen.add_argument("--copy-only", action="store_true", help="copy transcripts without simulating paste")
    listen.set_defaults(func=cmd_listen)
    install_listener = sub.add_parser("install-listener", help="enable the listener at login and update the shortcut helper")
    install_listener.set_defaults(func=cmd_install_listener)
    for name in ("toggle", "stop", "status", "shutdown"):
        control = sub.add_parser(name, help=f"send {name} to the running voice listener")
        control.set_defaults(func=cmd_control)

    doctor = sub.add_parser("doctor", help="report local hardware, desktop, audio, and ASR capability")
    doctor.set_defaults(func=cmd_doctor)

    record = sub.add_parser("record-test", help="record and validate a short local sample")
    record.add_argument("--seconds", type=float, default=3.0)
    record.add_argument("--keep", action="store_true")
    record.add_argument("--play", action="store_true")
    record.set_defaults(func=cmd_record_test)

    transcribe = sub.add_parser("transcribe-test", help="record or transcribe a local test sample")
    transcribe.add_argument("--file", help="existing local audio file to transcribe instead of recording")
    transcribe.add_argument("--seconds", type=float, default=4.0, help="recording duration when --file is not used")
    transcribe.add_argument("--tier", choices=tier_choices, help="model tier override")
    transcribe.add_argument("--language", default=None, help="language override, for example en")
    transcribe.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="transcription device")
    transcribe.add_argument("--keep", action="store_true", help="keep temporary recording")
    transcribe.set_defaults(func=cmd_transcribe_test)

    bench = sub.add_parser("benchmark", help="measure local transcription speed")
    bench.add_argument("--file", help="existing local audio file to benchmark instead of recording")
    bench.add_argument("--seconds", type=float, default=8.0, help="recording duration when --file is not used")
    bench.add_argument("--tier", choices=tier_choices, help="model tier override")
    bench.add_argument("--language", default=None, help="language override, for example en")
    bench.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="transcription device")
    bench.add_argument("--keep", action="store_true", help="keep temporary recording")
    bench.set_defaults(func=cmd_benchmark)

    quality = sub.add_parser("quality-test", help="record once, show raw and glossary-corrected transcript")
    quality.add_argument("--file", help="existing local audio file to test instead of recording")
    quality.add_argument("--seconds", type=float, default=8.0, help="recording duration when --file is not used")
    quality.add_argument("--model-tier", choices=tier_choices, help="model tier override")
    quality.add_argument("--language", default=None, help="language override, for example en")
    quality.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="transcription device")
    quality.add_argument("--keep", action="store_true", help="keep temporary recording")
    quality.set_defaults(func=cmd_quality_test)

    compare = sub.add_parser("compare-models", help="record once and compare multiple model tiers")
    compare.add_argument("--file", help="existing local audio file to reuse instead of recording")
    compare.add_argument("--tiers", default="fast,cpu", help="comma-separated model tiers, for example fast,cpu,accuracy")
    compare.add_argument("--seconds", type=float, default=10.0, help="recording duration when --file is not used")
    compare.add_argument("--language", default=None, help="language override, for example en")
    compare.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="transcription device")
    compare.add_argument("--keep", action="store_true", help="keep temporary recording")
    compare.set_defaults(func=cmd_compare_models)

    calibrate = sub.add_parser("calibrate-silence", help="record ambient noise and suggest a VAD threshold")
    calibrate.add_argument("--seconds", type=float, default=3.0)
    calibrate.add_argument("--write", action="store_true", help="write suggested threshold to config")
    calibrate.add_argument("--keep", action="store_true")
    calibrate.set_defaults(func=cmd_calibrate_silence)

    shortcut = sub.add_parser("install-shortcut", help="print or install GNOME shortcut helper")
    shortcut.add_argument("--dry-run", action="store_true", help="print instructions without writing files")
    shortcut.add_argument("--write-script", action="store_true", help="write ~/.local/bin/voicepaste-dictate")
    shortcut.set_defaults(func=cmd_install_shortcut)

    paste_last = sub.add_parser("paste-last", help="paste or copy the last transcript")
    paste_last.add_argument("--no-paste", action="store_true", help="copy and print without simulating paste")
    paste_last.add_argument("--copy-only", action="store_true", help="copy and print without simulating paste")
    paste_last.add_argument("--quiet", action="store_true", help="do not print the final transcript")
    paste_last.set_defaults(func=cmd_paste_last)

    models = sub.add_parser("models")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    commands = models_sub.add_parser("fetch-commands", help="download the local voice-command model")
    commands.set_defaults(func=cmd_fetch_commands)
    fetch = models_sub.add_parser("fetch", help="download a model for offline use")
    fetch.add_argument("--tier", required=True, choices=tier_choices, help="model tier to download for offline use")
    fetch.set_defaults(func=cmd_models_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the VoicePaste CLI.

    Args:
        argv: Optional argument list for tests. When omitted, ``argparse`` reads
            from ``sys.argv``.

    Returns:
        Process exit status.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if not hasattr(args, "func"):
            return cmd_run(args)
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        if "args" in locals() and (getattr(args, "immediate", False) or args.command in {"listen", "toggle", "stop"}):
            notify(f"VoicePaste error: {exc}")
        print(f"voicepaste: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
