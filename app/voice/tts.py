"""Text-to-speech through Piper, with a team-radio filter."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def clean_for_speech(text: str) -> str:
    """Strip anything that sounds wrong when read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_`#>]+", " ", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.M)
    replacements = {
        "km/h": "kilometres per hour",
        "kph": "kilometres per hour",
        "kg": "kilograms",
        "°C": " degrees celsius",
        "°": " degrees",
        "%": " percent",
        "&": " and ",
        "+/-": " plus or minus ",
        "~": " about ",
        "e.g.": "for example",
        "i.e.": "that is",
        "vs": "versus",
        "ERS": "E R S",
        "DRS": "D R S",
        "VSC": "virtual safety car",
        "SC": "safety car",
        "PB": "personal best",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class PiperVoice:
    def __init__(
        self,
        piper_exe: Path,
        voice_model: Path,
        speed: float = 1.0,
        volume: float = 1.0,
        radio_filter: bool = True,
    ) -> None:
        self.piper_exe = Path(piper_exe)
        self.voice_model = Path(voice_model)
        self.speed = speed
        self.volume = volume
        self.radio_filter = radio_filter
        self.sample_rate = self._detect_sample_rate()

    def _detect_sample_rate(self) -> int:
        meta = self.voice_model.with_suffix(".onnx.json")
        if meta.exists():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                return int(data["audio"]["sample_rate"])
            except Exception:  # noqa: BLE001
                pass
        return 22050

    def available(self) -> tuple[bool, str]:
        if not self.piper_exe.exists():
            return False, f"piper not found at {self.piper_exe}"
        if not self.voice_model.exists():
            return False, f"voice model not found at {self.voice_model}"
        return True, "ok"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        text = clean_for_speech(text)
        if not text:
            return np.zeros(0, dtype=np.int16), self.sample_rate
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)

        cmd = [
            str(self.piper_exe),
            "--model",
            str(self.voice_model),
            "--output_raw",
        ]
        if abs(self.speed - 1.0) > 0.01:
            cmd += ["--length_scale", f"{1.0 / self.speed:.3f}"]
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(
                f"piper failed ({proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace')[-400:]}"
            )
        audio = np.frombuffer(proc.stdout, dtype=np.int16).copy()
        return self.finish(audio, self.sample_rate), self.sample_rate

    # ------------------------------------------------------------------
    def finish(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Apply radio colouring and squelch click. Returns float32 mono."""
        if audio.size == 0:
            return np.zeros(0, dtype=np.float32)
        if audio.dtype == np.int16:
            data = audio.astype(np.float32) / 32768.0
        else:
            data = audio.astype(np.float32)
        if self.radio_filter:
            data = _bandpass(data, sample_rate)
            data = _saturate(data)
            data = _add_squelch(data, sample_rate)
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        if peak > 0:
            data = data * min(1.0, 0.95 * float(self.volume) / peak)
        return np.clip(data, -1.0, 1.0).astype(np.float32)


def _bandpass(data: np.ndarray, sample_rate: int) -> np.ndarray:
    try:
        from scipy.signal import butter, lfilter

        low = 320.0
        high = min(3200.0, sample_rate / 2 - 200.0)
        b, a = butter(4, [low, high], btype="band", fs=sample_rate)
        return lfilter(b, a, data).astype(np.float32)
    except Exception:  # noqa: BLE001 - scipy missing: still usable audio
        return data


def _saturate(data: np.ndarray) -> np.ndarray:
    return (np.tanh(data * 2.2) / np.tanh(2.2)).astype(np.float32)


def _add_squelch(data: np.ndarray, sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng()
    n = int(0.045 * sample_rate)
    click = rng.normal(0.0, 0.05, n).astype(np.float32)
    fade = np.linspace(1.0, 0.0, n, dtype=np.float32) ** 2
    click *= fade
    lead = np.zeros(int(0.02 * sample_rate), dtype=np.float32)
    tail = np.zeros(int(0.05 * sample_rate), dtype=np.float32)
    return np.concatenate([lead, click, data, tail])
