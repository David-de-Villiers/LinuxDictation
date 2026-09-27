"""Local faster-whisper transcription backend."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .config import Config
from .models import require_local_model


@dataclass(frozen=True)
class TranscriptionResult:
    """Result metadata for one local transcription run."""

    text: str
    duration_seconds: float
    backend: str
    model_path: Path
    device: str
    compute_type: str


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return bool(ctranslate2.get_supported_compute_types("cuda"))
    except Exception:
        return False


def select_device_and_compute(device: str = "auto", prefer_gpu: bool = True) -> tuple[str, str]:
    """Choose the CTranslate2 device and compute type for ASR."""

    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"unsupported device: {device}")
    if device == "cpu":
        return "cpu", "int8"
    if device == "cuda":
        if not _cuda_available():
            raise RuntimeError("CUDA requested but CTranslate2 cannot use CUDA")
        return "cuda", "float16"
    if prefer_gpu and _cuda_available():
        return "cuda", "float16"
    return "cpu", "int8"


def transcribe_file(
    path: Path,
    cfg: Config,
    tier: str | None = None,
    prefer_gpu: bool = True,
    device: str = "auto",
    language: str | None = None,
    initial_prompt: str | None = None,
) -> TranscriptionResult:
    """Transcribe a local audio file with a locally cached faster-whisper model.

    Args:
        path: Local audio file to transcribe.
        cfg: Loaded VoicePaste configuration.
        tier: Optional model tier override.
        prefer_gpu: Whether `auto` may choose CUDA.
        device: `auto`, `cpu`, or `cuda`.
        language: Optional language override.
        initial_prompt: Optional faster-whisper prompt override. If omitted,
            the configured prompt is used.

    Returns:
        TranscriptionResult containing text and backend metadata.
    """

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed") from exc
    model_path = require_local_model(cfg, tier)
    selected_device, compute_type = select_device_and_compute(device, prefer_gpu)
    started = time.monotonic()
    model = WhisperModel(str(model_path), device=selected_device, compute_type=compute_type)
    prompt = cfg.initial_prompt if initial_prompt is None else initial_prompt
    segments, _info = model.transcribe(
        str(path),
        language=language or cfg.language,
        vad_filter=True,
        initial_prompt=prompt or None,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return TranscriptionResult(
        text=text,
        duration_seconds=time.monotonic() - started,
        backend=cfg.backend,
        model_path=model_path,
        device=selected_device,
        compute_type=compute_type,
    )


class RecordingTranscriber:
    """Reuse a local model and transcribe long PCM recordings in bounded chunks."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.model = None

    def _silence_boundary(self, recording: BinaryIO, target: int, samples: int) -> tuple[int, bool]:
        import numpy as np

        rate = self.cfg.record_sample_rate
        if target >= samples:
            return samples, True
        start = max(0, target - 4 * rate)
        end = min(samples, target + 4 * rate)
        recording.seek(start * 2)
        data = np.frombuffer(recording.read((end - start) * 2), dtype="<i2").astype(np.float32) / 32768
        block = rate // 10
        framed = data[:len(data) // block * block].reshape(-1, block)
        quiet = np.sqrt(np.mean(framed * framed, axis=1)) < 0.001
        edges = np.diff(np.concatenate(([False], quiet, [False])).astype(np.int8))
        candidates = [
            start + (left + right) * block // 2
            for left, right in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True)
            if right - left >= 3
        ]
        if candidates:
            return int(min(candidates, key=lambda position: abs(position - target))), True
        return target, False

    def transcribe(self, recording: BinaryIO, samples: int) -> str:
        """Read mono 16-bit PCM, with overlapping context at chunk boundaries."""
        import numpy as np
        from faster_whisper import WhisperModel

        cfg = self.cfg
        if self.model is None:
            device, compute = select_device_and_compute(cfg.shortcut.device)
            self.model = WhisperModel(
                str(require_local_model(cfg, cfg.shortcut.model_tier)), device=device, compute_type=compute
            )
        rate = cfg.record_sample_rate
        stride = 20 * rate
        overlap = 2 * rate
        text = []
        core_start = 0
        starts_in_silence = True
        while core_start < samples:
            core_end, ends_in_silence = self._silence_boundary(recording, core_start + stride, samples)
            start = core_start if starts_in_silence else max(0, core_start - overlap)
            end = core_end if ends_in_silence else min(samples, core_end + overlap)
            recording.seek(start * 2)
            data = np.frombuffer(recording.read((end - start) * 2), dtype="<i2").astype(np.float32) / 32768
            if not data.size or np.max(np.abs(data)) < 0.001:
                core_start = core_end
                starts_in_silence = ends_in_silence
                continue
            segments, _ = self.model.transcribe(
                data, language=cfg.language, vad_filter=True, word_timestamps=True,
                initial_prompt=cfg.initial_prompt or None,
            )
            for segment in segments:
                for word in segment.words or []:
                    midpoint = start + (word.start + word.end) * rate / 2
                    if (starts_in_silence or core_start <= midpoint) and (ends_in_silence or midpoint < core_end):
                        text.append(word.word)
            core_start = core_end
            starts_in_silence = ends_in_silence
        return "".join(text).strip()
