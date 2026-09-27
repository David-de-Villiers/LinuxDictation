"""Configuration models and XDG path helpers for VoicePaste."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "voicepaste"


def config_path() -> Path:
    """Return the XDG config file path for VoicePaste."""

    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME / "config.toml"


def data_dir() -> Path:
    """Return the XDG data directory used for downloaded models."""

    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


def state_dir() -> Path:
    """Return the XDG state directory used for last transcript state."""

    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / APP_NAME


def model_dir() -> Path:
    """Return the local model cache directory."""

    return data_dir() / "models"


@dataclass(frozen=True)
class InsertionConfig:
    """Desktop insertion behavior."""

    prefer_clipboard_paste: bool = True
    restore_clipboard: bool = False
    paste_key: str = "ctrl+v"
    terminal_paste_key: str = "ctrl+shift+v"


@dataclass(frozen=True)
class ModelConfig:
    """Model identifiers for supported quality tiers."""

    fast: str = "Systran/faster-whisper-small.en"
    small: str = "Systran/faster-whisper-small.en"
    cpu: str = "Systran/faster-whisper-small.en"
    accuracy: str = "Systran/faster-whisper-large-v3-turbo"


@dataclass(frozen=True)
class GlossaryConfig:
    """Deterministic post-transcription phrase replacements."""

    enabled: bool = True
    replacements: dict[str, str] = field(
        default_factory=lambda: {
            "de-separation": "d-separation",
            "D separation": "d-separation",
            "d separation": "d-separation",
            "latex": "LaTeX",
            "bayesian network": "Bayesian network",
            "bayesian networks": "Bayesian networks",
        }
    )


@dataclass(frozen=True)
class ShortcutConfig:
    """Defaults used by non-interactive shortcut mode."""

    device: str = "cuda"
    model_tier: str = "cpu"
    immediate: bool = True
    stop_on_silence: bool = True
    silence_seconds: float = 1.2
    max_seconds: float = 30.0
    min_seconds: float = 1.0
    vad_threshold: float = 0.01
    pre_speech_padding_ms: int = 200
    post_speech_padding_ms: int = 300


@dataclass(frozen=True)
class ListenerConfig:
    """Voice activation and recording reminder settings."""

    activation_phrase: str = "start dictation"
    deactivation_phrase: str = "thank you"
    silence_reminder_seconds: float = 5.0
    silence_stop_seconds: float = 10.0
    command_model: str = "vosk-model-small-en-us-0.15"
    pause_on_capture: bool = True
    pause_processes: list[str] = field(default_factory=lambda: ["obs", "obs-studio"])


@dataclass(frozen=True)
class Config:
    """Top-level VoicePaste configuration."""

    backend: str = "faster-whisper"
    model_tier: str = "cpu"
    language: str = "en"
    record_sample_rate: int = 16000
    max_record_seconds: int = 120
    delete_audio: bool = True
    initial_prompt: str = (
        "Bayesian networks, conditional independence, d-separation, expected utility, "
        "LaTeX, probabilistic graphical models, posterior, prior, likelihood, inference."
    )
    insertion: InsertionConfig = field(default_factory=InsertionConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    shortcut: ShortcutConfig = field(default_factory=ShortcutConfig)
    listener: ListenerConfig = field(default_factory=ListenerConfig)

    def normalize_model_tier(self, tier: str | None = None) -> str:
        """Validate and normalize a model tier name."""

        selected = tier or self.model_tier
        if selected == "cpu":
            return "cpu"
        if selected not in {"fast", "small", "accuracy"}:
            raise ValueError(f"unknown model tier: {selected}")
        return selected

    def model_id_for_tier(self, tier: str | None = None) -> str:
        """Return the configured model identifier for a tier."""

        selected = self.normalize_model_tier(tier)
        return getattr(self.models, selected)


def _merge_table(defaults: dict, overrides: dict) -> dict:
    merged = defaults.copy()
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_table(merged[key], value)
        else:
            merged[key] = value
    return merged


def _recover_misplaced_vad_threshold(raw: dict) -> None:
    """Move thresholds written outside ``[shortcut]`` by older releases."""

    shortcut = raw.setdefault("shortcut", {})
    threshold = raw.pop("vad_threshold", None)
    for table_name in ("insertion", "models", "glossary"):
        table = raw.get(table_name)
        if isinstance(table, dict):
            threshold = table.pop("vad_threshold", threshold)

    replacements = raw.get("glossary", {}).get("replacements")
    if isinstance(replacements, dict):
        threshold = replacements.pop("vad_threshold", threshold)

    if "vad_threshold" not in shortcut and threshold is not None:
        shortcut["vad_threshold"] = threshold


def default_config_dict() -> dict:
    """Return the default TOML-compatible configuration mapping."""

    return {
        "backend": "faster-whisper",
        "model_tier": "cpu",
        "language": "en",
        "record_sample_rate": 16000,
        "max_record_seconds": 120,
        "delete_audio": True,
        "initial_prompt": (
            "Bayesian networks, conditional independence, d-separation, expected utility, "
            "LaTeX, probabilistic graphical models, posterior, prior, likelihood, inference."
        ),
        "insertion": {
            "prefer_clipboard_paste": True,
            "restore_clipboard": False,
            "paste_key": "ctrl+v",
        },
        "models": {
            "fast": "Systran/faster-whisper-small.en",
            "small": "Systran/faster-whisper-small.en",
            "cpu": "Systran/faster-whisper-small.en",
            "accuracy": "Systran/faster-whisper-large-v3-turbo",
        },
        "glossary": {
            "enabled": True,
            "replacements": {
                "de-separation": "d-separation",
                "D separation": "d-separation",
                "d separation": "d-separation",
                "latex": "LaTeX",
                "bayesian network": "Bayesian network",
                "bayesian networks": "Bayesian networks",
            },
        },
        "shortcut": {
            "device": "cuda",
            "model_tier": "cpu",
            "immediate": True,
            "stop_on_silence": True,
            "silence_seconds": 1.2,
            "max_seconds": 30.0,
            "min_seconds": 1.0,
            "vad_threshold": 0.01,
            "pre_speech_padding_ms": 200,
            "post_speech_padding_ms": 300,
        },
    }


def load_config(path: Path | None = None) -> Config:
    """Load configuration, merging partial user config with defaults."""

    path = path or config_path()
    raw = default_config_dict()
    if path.exists():
        with path.open("rb") as fh:
            overrides = tomllib.load(fh)
        _recover_misplaced_vad_threshold(overrides)
        raw = _merge_table(raw, overrides)
    return Config(
        backend=str(raw["backend"]),
        model_tier=str(raw["model_tier"]),
        language=str(raw["language"]),
        record_sample_rate=int(raw["record_sample_rate"]),
        max_record_seconds=int(raw["max_record_seconds"]),
        delete_audio=bool(raw["delete_audio"]),
        initial_prompt=str(raw.get("initial_prompt", "")),
        insertion=InsertionConfig(**raw["insertion"]),
        models=ModelConfig(**raw["models"]),
        glossary=GlossaryConfig(**raw["glossary"]),
        shortcut=ShortcutConfig(**raw["shortcut"]),
        listener=ListenerConfig(**raw.get("listener", {})),
    )


def write_default_config(path: Path | None = None) -> Path:
    """Create the default config file if it does not already exist."""

    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            '\n'.join(
                [
                    'backend = "faster-whisper"',
                    'model_tier = "cpu"',
                    'language = "en"',
                    'record_sample_rate = 16000',
                    'max_record_seconds = 120',
                    'delete_audio = true',
                    'initial_prompt = "Bayesian networks, conditional independence, d-separation, expected utility, LaTeX, probabilistic graphical models, posterior, prior, likelihood, inference."',
                    "",
                    "[insertion]",
                    "prefer_clipboard_paste = true",
                    "restore_clipboard = false",
                    'paste_key = "ctrl+v"',
                    'terminal_paste_key = "ctrl+shift+v"',
                    "",
                    "[models]",
                    'fast = "Systran/faster-whisper-small.en"',
                    'small = "Systran/faster-whisper-small.en"',
                    'cpu = "Systran/faster-whisper-small.en"',
                    'accuracy = "Systran/faster-whisper-large-v3-turbo"',
                    "",
                    "[glossary]",
                    "enabled = true",
                    "",
                    "[glossary.replacements]",
                    '"de-separation" = "d-separation"',
                    '"D separation" = "d-separation"',
                    '"d separation" = "d-separation"',
                    'latex = "LaTeX"',
                    '"bayesian network" = "Bayesian network"',
                    '"bayesian networks" = "Bayesian networks"',
                    "",
                    "[shortcut]",
                    'device = "cuda"',
                    'model_tier = "cpu"',
                    "immediate = true",
                    "stop_on_silence = true",
                    "silence_seconds = 1.2",
                    "max_seconds = 30",
                    "min_seconds = 1",
                    "vad_threshold = 0.01",
                    "pre_speech_padding_ms = 200",
                    "post_speech_padding_ms = 300",
                    "",
                    "[listener]",
                    'activation_phrase = "start dictation"',
                    'deactivation_phrase = "thank you"',
                    "silence_reminder_seconds = 5",
                    "silence_stop_seconds = 10",
                    'command_model = "vosk-model-small-en-us-0.15"',
                    'pause_on_capture = true',
                    'pause_processes = ["obs", "obs-studio"]',
                    "",
                ]
            )
        )
    return path
