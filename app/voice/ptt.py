"""Push-to-talk key handling: hold-to-talk or tap-to-talk."""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)


def _parse_key(name: str):
    from pynput import keyboard

    text = name.strip().lower()
    named = {
        "f1": keyboard.Key.f1, "f2": keyboard.Key.f2, "f3": keyboard.Key.f3,
        "f4": keyboard.Key.f4, "f5": keyboard.Key.f5, "f6": keyboard.Key.f6,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8, "f9": keyboard.Key.f9,
        "f10": keyboard.Key.f10, "f11": keyboard.Key.f11, "f12": keyboard.Key.f12,
        "space": keyboard.Key.space, "caps_lock": keyboard.Key.caps_lock,
        "ctrl": keyboard.Key.ctrl, "ctrl_l": keyboard.Key.ctrl_l,
        "ctrl_r": keyboard.Key.ctrl_r, "alt": keyboard.Key.alt,
        "alt_l": keyboard.Key.alt_l, "alt_r": keyboard.Key.alt_r,
        "shift": keyboard.Key.shift, "shift_l": keyboard.Key.shift_l,
        "shift_r": keyboard.Key.shift_r, "tab": keyboard.Key.tab,
        "insert": keyboard.Key.insert, "delete": keyboard.Key.delete,
        "home": keyboard.Key.home, "end": keyboard.Key.end,
        "pause": keyboard.Key.pause, "scroll_lock": keyboard.Key.scroll_lock,
    }
    if text in named:
        return named[text]
    if len(text) == 1:
        return keyboard.KeyCode.from_char(text)
    raise ValueError(f"unsupported push-to-talk key: {name!r}")


class PushToTalk:
    """Drives start/stop callbacks from a single key.

    mode="hold": press starts, release stops.
    mode="tap":  press toggles. Whether a press means start or stop is decided
                 by ``is_active``, so auto-stop (the word "over") stays in sync.
    """

    def __init__(
        self,
        key: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        mode: str = "tap",
        is_active: Callable[[], bool] | None = None,
    ) -> None:
        self.key = _parse_key(key)
        self.on_start = on_start
        self.on_stop = on_stop
        self.mode = mode if mode in ("tap", "hold") else "tap"
        self.is_active = is_active or (lambda: False)
        self._listener = None
        self._pressed = threading.Event()

    def start(self) -> None:
        from pynput import keyboard

        def on_press(key):  # noqa: ANN001
            if key != self.key or self._pressed.is_set():
                return
            self._pressed.set()
            try:
                if self.mode == "hold":
                    self.on_start()
                elif self.is_active():
                    self.on_stop()
                else:
                    self.on_start()
            except Exception:  # noqa: BLE001
                log.exception("push-to-talk key press handler failed")

        def on_release(key):  # noqa: ANN001
            if key != self.key:
                return
            self._pressed.clear()
            if self.mode == "hold":
                try:
                    self.on_stop()
                except Exception:  # noqa: BLE001
                    log.exception("push-to-talk key release handler failed")

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()
        log.info("push-to-talk ready (%s mode, %s)", self.mode, self.key)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
