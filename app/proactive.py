"""Rule-based proactive race engineer: speaks without being asked."""

from __future__ import annotations

import logging
import time
from typing import Callable

from .telemetry.state import RaceState

log = logging.getLogger(__name__)


class ProactiveEngine:
    """Watches telemetry and produces short radio calls on race events."""

    def __init__(self, state: RaceState, cooldown_s: float = 20.0, enabled: bool = True) -> None:
        self.state = state
        self.cooldown_s = cooldown_s
        self.enabled = enabled
        self._last_spoken = 0.0
        self._rule_last: dict[str, float] = {}
        self._last_lap = 0
        self._wear_bucket = 0
        self._fuel_warned_lap = -99
        self._sc_last = 0
        self._flag_last = 0
        self._rain_warned = False
        self._gap_warned_lap = -99
        self._damage_warned = False
        self._pit_stops: dict[int, int] = {}
        self._rules: list[tuple[str, Callable[[], str | None], float]] = [
            ("lap", self._lap_call, 10.0),
            ("wear", self._wear_call, 60.0),
            ("temp", self._temp_call, 90.0),
            ("fuel", self._fuel_call, 45.0),
            ("pit_window", self._pit_window_call, 120.0),
            ("safety_car", self._safety_car_call, 20.0),
            ("flag", self._flag_call, 20.0),
            ("weather", self._weather_call, 300.0),
            ("gap_behind", self._gap_behind_call, 60.0),
            ("rival_pit", self._rival_pit_call, 10.0),
            ("undercut", self._undercut_call, 90.0),
            ("damage", self._damage_call, 120.0),
            ("invalid_lap", self._invalid_lap_call, 10.0),
        ]

    # ------------------------------------------------------------------
    def poll(self) -> str | None:
        if not self.enabled:
            return None
        snap = self.state.snapshot()
        if not snap["connected"] or not snap["lap"]:
            return None
        if time.time() - self._last_spoken < self.cooldown_s:
            return None
        for name, rule, rule_cooldown in self._rules:
            last = self._rule_last.get(name, 0.0)
            if time.time() - last < rule_cooldown:
                continue
            try:
                message = rule()
            except Exception:  # noqa: BLE001
                log.exception("proactive rule %s failed", name)
                continue
            if message:
                self._rule_last[name] = time.time()
                self._last_spoken = time.time()
                return message
        return None

    # ------------------------------------------------------------------
    def _lap_call(self) -> str | None:
        s = self.state
        if self._last_lap == 0:
            self._last_lap = s.lap
            return None
        if s.lap <= self._last_lap or not s.last_lap_ms:
            self._last_lap = max(self._last_lap, s.lap)
            return None
        self._last_lap = s.lap
        laps = [r for r in s.lap_history if r.lap_number != s.lap]
        lap_time = s.last_lap_ms / 1000.0
        if s.lap_invalid:
            return None
        if len(laps) <= 1:
            return f"That's a {_time(lap_time)}."
        best = min(r.seconds for r in laps[:-1])
        delta = lap_time - best
        if delta <= -0.05:
            return f"That's a {_time(lap_time)}, personal best. Good lap."
        if delta >= 0.15:
            return f"That's a {_time(lap_time)}, {_delta(delta)} off your best."
        return None

    def _wear_call(self) -> str | None:
        s = self.state
        worst = max(s.tyre_wear) if s.tyre_wear else 0.0
        bucket = int(worst // 15)
        if bucket <= self._wear_bucket:
            return None
        self._wear_bucket = bucket
        if worst < 45:
            return None
        life = s.predicted_tyre_life()
        suffix = f", about {life:.0f} laps left." if life is not None else "."
        return f"Tyres are at {worst:.0f} percent wear{suffix}"

    def _temp_call(self) -> str | None:
        s = self.state
        if not s.tyre_surface_c:
            return None
        hottest = max(s.tyre_surface_c)
        coolest = min(s.tyre_surface_c)
        if hottest >= 118:
            return f"Tyres are overheating, {hottest} celsius on the surface. Back off the pressure."
        if s.track_temp_c > 30 and coolest < 70 and s.tyre_age_laps > 2:
            return "Tyres are running cold, push a little to get temperature in them."
        return None

    def _fuel_call(self) -> str | None:
        s = self.state
        surplus = s.fuel_surplus_laps()
        if surplus is None or surplus >= -0.05:
            return None
        if s.lap - self._fuel_warned_lap < 4:
            return None
        self._fuel_warned_lap = s.lap
        return (
            f"You are {abs(surplus):.1f} laps short on fuel. "
            "Lift and coast into the braking zones."
        )

    def _pit_window_call(self) -> str | None:
        s = self.state
        if not s.pit_window_ideal or s.pit_status:
            return None
        if s.lap == s.pit_window_ideal:
            return (
                f"Pit window is open, lap {s.pit_window_ideal} to {s.pit_window_latest}. "
                f"Rejoin predicted P{s.pit_rejoin_position}."
            )
        if s.lap == s.pit_window_latest - 1:
            return "Last lap of the pit window. We need to box next lap."
        return None

    def _safety_car_call(self) -> str | None:
        s = self.state
        if s.safety_car == self._sc_last:
            return None
        previous, self._sc_last = self._sc_last, s.safety_car
        if s.safety_car == 1:
            return "Safety car deployed. Stay off the kerbs, keep the tyres warm."
        if s.safety_car == 2:
            return "Virtual safety car. Delta positive, stay on it."
        if previous and not s.safety_car:
            return "Safety car in this lap, track goes green."
        return None

    def _flag_call(self) -> str | None:
        s = self.state
        if s.fia_flag == self._flag_last:
            return None
        previous, self._flag_last = self._flag_last, s.fia_flag
        if s.fia_flag == 3:
            return "Yellow flag ahead. Be ready to slow."
        if s.fia_flag == 4:
            return "Red flag. Slow down and prepare to stop."
        if s.fia_flag == 2:
            return "Blue flags. Let the leaders through."
        if s.fia_flag == 1 and previous in (2, 3, 4):
            return "Track is green again."
        return None

    def _weather_call(self) -> str | None:
        s = self.state
        if self._rain_warned or s.weather >= 3:
            return None
        for sample in s.forecast[:3]:
            if sample["minutes"] <= 15 and sample["rain_pct"] >= 50:
                self._rain_warned = True
                return (
                    f"Rain expected in about {sample['minutes']} minutes, "
                    f"{sample['rain_pct']} percent chance."
                )
        return None

    def _gap_behind_call(self) -> str | None:
        s = self.state
        if s.gap_behind_s is None or s.gap_behind_s > 1.0:
            return None
        if s.lap - self._gap_warned_lap < 4:
            return None
        self._gap_warned_lap = s.lap
        return f"Car behind is within {s.gap_behind_s:.1f} seconds. Defend the inside."

    def _rival_pit_call(self) -> str | None:
        s = self.state
        me = s.player
        message = None
        for car in s.cars:
            if car.index == me.index or not car.position:
                continue
            previous = self._pit_stops.get(car.index, car.pit_stops)
            self._pit_stops[car.index] = car.pit_stops
            if car.pit_stops > previous and message is None:
                gap = abs(car.position - me.position)
                if gap <= 2:
                    message = (
                        f"{car.name} has boxed. They are now on "
                        f"{car.compound_name} tyres."
                    )
        return message

    def _undercut_call(self) -> str | None:
        s = self.state
        me = s.player
        if not me.position:
            return None
        behind = s.rival(me.position + 1)
        if behind is None or s.gap_behind_s is None:
            return None
        if s.gap_behind_s <= 2.0 and behind.tyre_age_laps + 3 < me.tyre_age_laps:
            return (
                f"{behind.name} is on much fresher tyres, "
                f"{behind.tyre_age_laps} laps old. Undercut threat."
            )
        return None

    def _damage_call(self) -> str | None:
        s = self.state
        if self._damage_warned:
            return None
        if s.wing_damage >= 30:
            self._damage_warned = True
            return f"Front wing damage at {s.wing_damage} percent. Expect understeer."
        if s.floor_damage >= 30:
            self._damage_warned = True
            return "Floor damage. Watch the rear through high speed corners."
        return None

    def _invalid_lap_call(self) -> str | None:
        s = self.state
        if not s.lap_invalid or s.sector < 2:
            return None
        return "Lap time deleted, track limits."


def _time(seconds: float) -> str:
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    if minutes:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} {rest:04.1f}"
    return f"{rest:.1f}"


def _delta(seconds: float) -> str:
    return f"{abs(seconds):.1f} seconds"
