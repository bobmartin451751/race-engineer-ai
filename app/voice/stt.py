"""Speech-to-text with faster-whisper."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(
        self,
        model: str = "small.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 1,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            ) from exc

        attempts = [(self.device, self.compute_type, False)]
        if self.device != "cpu":
            attempts.append(("cpu", "int8", False))
        # A transient Hugging Face hiccup must not break speech recognition
        # when the model is already cached locally.
        attempts.append((attempts[-1][0], attempts[-1][1], True))

        last_error: Exception | None = None
        for device, compute_type, local_only in attempts:
            try:
                log.info(
                    "loading whisper %s on %s (%s%s)",
                    self.model_name, device, compute_type,
                    ", cache only" if local_only else "",
                )
                model = WhisperModel(
                    self.model_name,
                    device=device,
                    compute_type=compute_type,
                    local_files_only=local_only,
                )
                self.device = device
                self.compute_type = compute_type
                self._model = model
                return model
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log.warning("whisper load failed on %s/%s: %s", device, compute_type, exc)
        raise RuntimeError(f"could not load whisper model: {last_error}")

    def warm_up(self) -> None:
        self._load()

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if audio.size == 0:
            return ""
        audio = audio.astype(np.float32, copy=False).flatten()
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak < 0.004:
            return ""
        if sample_rate != 16000:
            audio = _resample(audio, sample_rate, 16000)
        # Normalise quiet headset mics without clipping loud ones.
        if peak < 0.25:
            audio = audio * (0.6 / peak)
        model = self._load()
        segments, _info = model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return " ".join(text.split())


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return audio
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(src, dst)
        return resample_poly(audio, dst // g, src // g).astype(np.float32)
    except Exception:  # noqa: BLE001
        idx = np.linspace(0, audio.size - 1, int(audio.size * dst / src))
        return np.interp(idx, np.arange(audio.size), audio).astype(np.float32)
