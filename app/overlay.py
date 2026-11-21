"""Always-on-top telemetry overlay for race-engineer-ai.

Run standalone with ``python -m app.overlay``; the engineer launches it
automatically when ``overlay.enabled`` is true.

It reads a JSON snapshot that the engineer writes four times a second, so it
needs no UDP port of its own and cannot disturb telemetry. Rendering uses
pygame (a small dependency) because Tkinter is missing from some Windows
Python installs.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import os
import time
from pathlib import Path

from .config import load_config

BG = (11, 13, 16)
PANEL = (24, 28, 34)
TEXT = (230, 233, 239)
DIM = (138, 147, 160)
ACCENT = (77, 163, 255)
GOOD = (55, 214, 122)
WARN = (255, 176, 32)
BAD = (255, 77, 79)

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002
SW_HIDE = 0
SW_SHOW = 5


def _state_path(cfg) -> Path:
    path = Path(cfg.get("overlay.state_file", ".temp/live_state.json"))
    return path if path.is_absolute() else cfg.path.parent / path


class Overlay:
    def __init__(self, cfg) -> None:
        try:
            import pygame
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "pygame is required for the overlay. Run: pip install pygame-ce"
            ) from exc
        self.pg = pygame
        self.cfg = cfg
        self.path = _state_path(cfg)
        self.scale = max(0.6, min(2.0, float(cfg.get("overlay.scale", 1.0))))
        self.width = int(380 * self.scale)
        self.height = int(250 * self.scale)

        x = int(cfg.get("overlay.x", 40))
        y = int(cfg.get("overlay.y", 40))
        os.environ.setdefault("SDL_VIDEO_WINDOW_POS", f"{x},{y}")
        os.environ.setdefault("SDL_VIDEO_CENTERED", "0")

        pygame.init()
        pygame.display.set_caption("race-engineer overlay")
        self.screen = pygame.display.set_mode(
            (self.width, self.height), pygame.NOFRAME
        )
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Consolas", max(10, int(15 * self.scale)))
        self.small = pygame.font.SysFont("Consolas", max(8, int(12 * self.scale)))
        self.big = pygame.font.SysFont(
            "Consolas", max(12, int(19 * self.scale)), bold=True
        )

        info = pygame.display.get_wm_info()
        self.hwnd = info.get("window")
        self.user32 = ctypes.windll.user32 if self.hwnd else None
        self.visible = True
        self._drag_offset = None
        if self.user32:
            # SDL's position hint is ignored in some multi-monitor layouts,
            # so place the window explicitly.
            self.user32.MoveWindow(self.hwnd, x, y, self.width, self.height, True)
            self._make_topmost()
            self._set_alpha(float(cfg.get("overlay.opacity", 0.88)))

        self._start_hotkey()
        self._last_snapshot: dict | None = None
        self._last_state_at = 0.0

    # ------------------------------------------------------------------
    def _make_topmost(self) -> None:
        self.user32.SetWindowPos(
            self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def _set_alpha(self, opacity: float) -> None:
        try:
            get_long = getattr(self.user32, "GetWindowLongPtrW", self.user32.GetWindowLongW)
            set_long = getattr(self.user32, "SetWindowLongPtrW", self.user32.SetWindowLongW)
            style = get_long(self.hwnd, GWL_EXSTYLE)
            set_long(self.hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            self.user32.SetLayeredWindowAttributes(
                self.hwnd, 0, int(max(0.3, min(1.0, opacity)) * 255), LWA_ALPHA
            )
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    def _start_hotkey(self) -> None:
        key_name = str(self.cfg.get("overlay.toggle_key", "f10"))
        try:
            from pynput import keyboard
        except Exception:  # noqa: BLE001
            return

        def on_press(key):
            token = getattr(key, "name", None) or getattr(key, "char", None)
            if token and str(token).lower() == key_name.lower():
                self._toggle()

        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()

    def _toggle(self) -> None:
        if not self.user32 or not self.hwnd:
            return
        self.visible = not self.visible
        self.user32.ShowWindow(self.hwnd, SW_SHOW if self.visible else SW_HIDE)
        if self.visible:
            self._make_topmost()

    # ------------------------------------------------------------------
    def _read(self) -> dict | None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return None

    def _fresh(self) -> bool:
        try:
            return (time.time() - self.path.stat().st_mtime) < 3.0
        except OSError:
            return False

    # ------------------------------------------------------------------
    def _text(self, surface, text: str, x: int, y: int, font=None, colour=TEXT) -> int:
        if not text:
            return y
        rendered = (font or self.font).render(text, True, colour)
        surface.blit(rendered, (x, y))
        return y + rendered.get_height() + int(2 * self.scale)

    def _bar(self, surface, y, pct: float, colour) -> None:
        x = int(8 * self.scale)
        width = self.width - 2 * x
        height = max(5, int(7 * self.scale))
        self.pg.draw.rect(surface, PANEL, (x, y, width, height))
        filled = int(width * max(0.0, min(100.0, pct)) / 100.0)
        if filled:
            self.pg.draw.rect(surface, colour, (x, y, filled, height))

    def _render(self, snap: dict | None, fresh: bool) -> None:
        s = self.screen
        s.fill(BG)

        if snap is None or not fresh:
            self._text(s, "waiting for engineer data...", int(10 * self.scale),
                       int(10 * self.scale), self.big, WARN)
            self._text(s, "run: run.cmd", int(10 * self.scale), int(38 * self.scale),
                       self.small, DIM)
            return

        pad = int(8 * self.scale)
        y = pad
        lap = snap.get("lap") or 0
        total = snap.get("total_laps") or "?"
        pos = snap.get("position") or "?"
        gap = snap.get("gap_ahead_s")
        gap_text = f"+{gap:.1f}" if gap is not None else "LEADER"
        y = self._text(s, f"LAP {lap}/{total}   P{pos}   {gap_text}", pad, y, self.big)
        y = self._text(
            s,
            f"{snap.get('speed_kph', 0):3d} km/h   GEAR {snap.get('gear', 0)}"
            + ("   DRS" if snap.get("drs") else ""),
            pad, y,
        )

        fuel = snap.get("fuel_kg") or 0.0
        surplus = snap.get("fuel_surplus_laps")
        if surplus is None:
            tail = ""
            colour = TEXT
        elif surplus >= 0:
            tail = f"   +{surplus:.1f} laps"
            colour = TEXT
        else:
            tail = f"   {surplus:.1f} laps SHORT"
            colour = BAD
        y = self._text(s, f"FUEL {fuel:.1f} kg{tail}", pad, y, colour=colour)

        tyre = snap.get("tyre") or {}
        wear = tyre.get("wear_pct") or {}
        max_wear = max(wear.values()) if wear else 0.0
        life = tyre.get("predicted_life_laps")
        life_text = f"   life ~{life:.0f}" if life is not None else ""
        y = self._text(
            s,
            f"{str(tyre.get('compound', '?')).upper()} {tyre.get('age_laps', 0)} laps"
            f"   wear {max_wear:.0f}%{life_text}",
            pad, y,
        )
        wear_colour = GOOD if max_wear < 40 else WARN if max_wear < 70 else BAD
        self._bar(s, y, max_wear, wear_colour)
        y += int(12 * self.scale)

        systems = snap.get("systems") or {}
        ers = systems.get("ers_pct") or 0.0
        y = self._text(
            s,
            f"ERS {ers:.0f}%   {str(systems.get('ers_mode', '')).upper()}"
            f"   MIX {str(systems.get('fuel_mix', '')).upper()}",
            pad, y,
        )
        self._bar(s, y, ers, ACCENT)
        y += int(12 * self.scale)

        gb = snap.get("gap_behind_s")
        trend = snap.get("gap_trend_s") or 0.0
        arrow = "^" if trend > 0.05 else "v" if trend < -0.05 else "="
        gap_line = f"GAP {arrow} {abs(trend):.1f}"
        if gb is not None:
            gap_line += f"   BEHIND {gb:.1f}"
        y = self._text(s, gap_line, pad, y)

        recent = snap.get("recent_laps") or []
        if recent:
            y = self._text(
                s,
                "   ".join(_short_time(r["time_s"]) for r in recent[-3:]),
                pad, y, self.small, DIM,
            )

        ideal = snap.get("pit_window_ideal_lap") or 0
        latest = snap.get("pit_window_latest_lap") or 0
        if ideal:
            y = self._text(s, f"PIT WINDOW  L{ideal}-{latest}", pad, y, colour=ACCENT)

        flag = str(snap.get("flag") or "none").upper()
        sc = snap.get("safety_car") or "none"
        status = "GREEN" if flag in ("GREEN", "NONE", "UNKNOWN") else flag
        if sc != "none":
            status += f"   {str(sc).upper()}"
        if not snap.get("connected", True):
            status = "NO TELEMETRY"
        self._text(s, status, pad, self.height - int(20 * self.scale), self.small,
                   DIM if status == "GREEN" else BAD)

    # ------------------------------------------------------------------
    def _handle_events(self) -> bool:
        pg = self.pg
        for event in pg.event.get():
            if event.type == pg.QUIT:
                return False
            if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
                return False
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                if self.user32 and self.hwnd:
                    rect = ctypes.wintypes.RECT()
                    self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
                    mx, my = pg.mouse.get_pos()
                    self._drag_offset = (mx, my, rect.left, rect.top)
            elif event.type == pg.MOUSEBUTTONUP and event.button == 1:
                self._drag_offset = None
            elif event.type == pg.MOUSEMOTION and self._drag_offset:
                if self.user32 and self.hwnd:
                    mx0, my0, wx, wy = self._drag_offset
                    mx, my = pg.mouse.get_pos()
                    self.user32.MoveWindow(
                        self.hwnd, wx + (mx - mx0), wy + (my - my0),
                        self.width, self.height, True,
                    )
        return True

    def run(self) -> None:
        pg = self.pg
        running = True
        while running:
            running = self._handle_events()
            if not running:
                break
            snap = self._read()
            self._render(snap, self._fresh())
            pg.display.flip()
            pg.event.pump()
            self.clock.tick(10)
        pg.quit()


def _short_time(seconds) -> str:
    if not seconds:
        return "-"
    minutes, rest = divmod(float(seconds), 60)
    if minutes:
        return f"{int(minutes)}:{rest:04.1f}"
    return f"{rest:.1f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="race-engineer-ai overlay")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    Overlay(cfg).run()


if __name__ == "__main__":
    main()
