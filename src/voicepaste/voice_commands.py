"""Offline phrase recognition with word timing for audio trimming."""

from __future__ import annotations

import json
from dataclasses import dataclass

from voicepaste.config import Config, model_dir


@dataclass(frozen=True)
class Phrase:
    """A recognized phrase and its position in the input stream."""

    text: str
    start: int
    end: int


class CommandRecognizer:
    """Recognize command phrases using a local streaming speech model."""

    def __init__(self, cfg: Config) -> None:
        from vosk import Model, SetLogLevel

        path = model_dir() / cfg.listener.command_model
        if not path.is_dir():
            raise RuntimeError("command model missing; run voicepaste models fetch-commands")
        SetLogLevel(-1)
        self.model = Model(str(path))
        self.sample_rate = cfg.record_sample_rate
        self.phrases = [cfg.listener.activation_phrase, cfg.listener.deactivation_phrase]
        if any(not phrase.strip() for phrase in self.phrases) or self.phrases[0] == self.phrases[1]:
            raise ValueError("activation and deactivation phrases must be distinct and nonempty")
        self.reset(0)

    def reset(self, offset: int) -> None:
        """Begin a fresh recognition timeline at an absolute sample offset."""
        from vosk import KaldiRecognizer

        self.recognizer = KaldiRecognizer(self.model, self.sample_rate, json.dumps([*self.phrases, "[unk]"]))
        self.recognizer.SetWords(True)
        self.recognizer.SetPartialWords(True)
        self.offset = offset
        self.last_command_end = offset

    def feed(self, pcm: bytes) -> list[Phrase]:
        """Return newly recognized commands, including stable partial words."""
        final = self.recognizer.AcceptWaveform(pcm)
        result = json.loads(self.recognizer.Result() if final else self.recognizer.PartialResult())
        words = result.get("result", result.get("partial_result", []))
        matches = []
        for index in range(len(words)):
            for phrase in self.phrases:
                tokens = phrase.lower().split()
                candidates = words[index : index + len(tokens)]
                if [word["word"] for word in candidates] != tokens:
                    continue
                start = self.offset + round(candidates[0]["start"] * self.sample_rate)
                end = self.offset + round(candidates[-1]["end"] * self.sample_rate)
                if end > self.last_command_end:
                    matches.append(Phrase(phrase, start, end))
                    self.last_command_end = end
        return matches
