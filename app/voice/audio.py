"""Microphone capture and speaker playback."""

from __future__ import annotations

import logging
import queue
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

try:
    import sounddevice as sd
except Exception as exc:  # noqa: BLE001 - reported at runtime with guidance
    sd = None
    _SD_IMPORT_ERROR = exc
else:
    _SD_IMPORT_ERROR = None


def _require_sounddevice() -> None:
    if sd is None:
        raise RuntimeError(
            "sounddevice is not available. Run: pip install sounddevice\n"
            f"Original error: {_SD_IMPORT_ERROR}"
        )


def list_devices() -> str:
    _require_sounddevice()
    lines = ["INPUT DEVICES"]
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            lines.append(
                f"  [{idx}] {dev['name']}  ({dev['max_input_channels']} ch, "
                f"default sr {int(dev['default_samplerate'])})"
            )
    lines.append("")
    lines.append("OUTPUT DEVICES")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            lines.append(
                f"  [{idx}] {dev['name']}  ({dev['max_output_channels']} ch, "
                f"default sr {int(dev['default_samplerate'])})"
            )
    return "\n".join(lines)


def resolve_device(value: Any, kind: str) -> Any:
    """Accept a device index, a unique name substring, or None for default."""
    _require_sounddevice()
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).lower()
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    matches = [
        idx
        for idx, dev in enumerate(sd.query_devices())
        if dev[channel_key] > 0 and text in dev["name"].lower()
    ]
    if not matches:
        raise ValueError(f"no {kind} device matching {value!r}; run --devices to list them")
    if len(matches) > 1:
        names = ", ".join(f"[{i}] {sd.query_devices(i)['name']}" for i in matches)
        raise ValueError(f"ambiguous {kind} device {value!r}: {names}")
    return matches[0]


class Recorder:
    """Records mono float32 audio until stopped."""

    def __init__(self, device: Any = None, sample_rate: int = 16000) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None
        self._recording = False

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        _require_sounddevice()
        if self._recording:
            return
        self._queue = queue.Queue()

        def callback(indata, _frames, _time, status):  # noqa: ANN001
            if status:
                log.debug("input status: %s", status)
            self._queue.put(indata[:, 0].copy())

        def open_stream(rate: int):
            return sd.InputStream(
                samplerate=rate,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=callback,
                blocksize=1024,
            )

        try:
            stream = open_stream(self.sample_rate)
        except Exception:  # noqa: BLE001 - many devices refuse 16 kHz
            info = sd.query_devices(self.device, "input") if self.device is not None else sd.query_devices(kind="input")
            fallback = int(info["default_samplerate"])
            log.info("input does not accept %s Hz, using %s Hz", self.sample_rate, fallback)
            self.sample_rate = fallback
            stream = open_stream(fallback)
        stream.start()
        self._stream = stream
        self._recording = True

    def stop(self) -> np.ndarray:
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        chunks = []
        while True:
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def cancel(self) -> None:
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def play(samples: np.ndarray, sample_rate: int, device: Any = None, blocking: bool = True) -> None:
    _require_sounddevice()
    if samples.size == 0:
        return
    data = samples.astype(np.float32, copy=False)
    if data.ndim == 1:
        data = data[:, None]
    sd.play(data, sample_rate, device=device, blocking=blocking)


def stop_playback() -> None:
    if sd is not None:
        sd.stop()
