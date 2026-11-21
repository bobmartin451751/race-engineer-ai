"""End-of-utterance detection: the word "over" and trailing silence."""

from __future__ import annotations

import re

import numpy as np

DEFAULT_OVER_WORDS = ("over", "over and out")


def _build_pattern(words) -> re.Pattern:
    alternatives = "|".join(
        re.escape(word).replace(r"\ ", r"\s+")
        for word in sorted(words, key=len, reverse=True)
    )
    # Whole-word match, only at the end of the transcript. "oversteer" and
    # "overcut" cannot match because the word boundary fails.
    return re.compile(
        rf"(?:^|[\s,.;:!?-])({alternatives})[\s.!?,]*$", re.IGNORECASE
    )


def ends_with_over(text: str, words=None) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    pattern = _build_pattern(words or DEFAULT_OVER_WORDS)
    return pattern.search(cleaned) is not None


def strip_over(text: str, words=None) -> str:
    """Remove a trailing 'over' / 'over and out' from a transcript."""
    cleaned = (text or "").strip()
    pattern = _build_pattern(words or DEFAULT_OVER_WORDS)
    match = pattern.search(cleaned)
    if not match:
        return cleaned
    return cleaned[: match.start()].strip(" ,.;:-")


class SilenceTracker:
    """Reports when the driver has stopped speaking for long enough."""

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_s: float = 1.2,
        speech_rms: float = 0.012,
        min_speech_s: float = 0.35,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_s = silence_s
        self.speech_rms = speech_rms
        self.min_speech_s = min_speech_s
        self._speech_samples = 0
        self._silent_samples = 0
        self._started = False

    @property
    def heard_speech(self) -> bool:
        return self._started

    def update(self, chunk: np.ndarray) -> bool:
        """Feed a chunk; return True when the utterance should end."""
        if chunk is None or chunk.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
        if rms >= self.speech_rms:
            self._started = True
            self._speech_samples += chunk.size
            self._silent_samples = 0
            return False
        if not self._started:
            return False
        self._silent_samples += chunk.size
        enough_speech = self._speech_samples >= self.min_speech_s * self.sample_rate
        return enough_speech and (self._silent_samples >= self.silence_s * self.sample_rate)
