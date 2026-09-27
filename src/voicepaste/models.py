"""Local model path and download helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .config import Config, model_dir


def model_local_path(model_id: str, base_dir: Path | None = None) -> Path:
    """Map a model identifier to its local cache path."""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "--", model_id).strip("-")
    return (base_dir or model_dir()) / safe


def fetch_model(cfg: Config, tier: str) -> Path:
    """Download a configured model tier for offline use."""

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface-hub is not installed") from exc
    model_id = cfg.model_id_for_tier(tier)
    target = model_local_path(model_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_id, local_dir=target, local_dir_use_symlinks=False)
    return target


def require_local_model(cfg: Config, tier: str | None = None) -> Path:
    """Return a local model path or raise with setup guidance."""

    model_id = cfg.model_id_for_tier(tier)
    path = model_local_path(model_id)
    if not path.exists():
        raise RuntimeError(f"local model not found at {path}; run `voicepaste models fetch --tier {tier or cfg.model_tier}`")
    return path


def fetch_command_model(cfg: Config) -> Path:
    """Download the English command model once for offline listening."""
    import shutil
    import tempfile
    from urllib.request import urlopen
    from zipfile import ZipFile

    name = cfg.listener.command_model
    if name != "vosk-model-small-en-us-0.15":
        raise ValueError("install custom command models manually into the model directory")
    target = model_dir() / name
    if target.is_dir():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="command-model-") as temporary:
        archive = Path(temporary) / "model.zip"
        with urlopen(f"https://alphacephei.com/vosk/models/{name}.zip", timeout=60) as response:
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        with ZipFile(archive) as zipped:
            for member in zipped.namelist():
                if not member.startswith(name + "/") or ".." in Path(member).parts:
                    raise RuntimeError("unexpected path in command model archive")
            zipped.extractall(temporary)
        (Path(temporary) / name).rename(target)
    return target
