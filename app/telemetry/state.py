"""Live race state assembled from F1 24 UDP packets.

The state is updated from the network thread and read from the voice threads,
so every public accessor takes the internal lock.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import packets as p

TRACKS = {
    0: "Melbourne",
    1: "Shanghai",
    2: "Sakhir",
    3: "Barcelona",
    4: "Monaco",
    5: "Montreal",
    6: "Silverstone",
    7: "Hockenheim",
    8: "Hungaroring",
    9: "Spa-Francorchamps",
    10: "Monza",
    11: "Singapore",
    12: "Suzuka",
    13: "Abu Dhabi",
    14: "Austin",
    15: "Sao Paulo",
    16: "Spielberg",
    17: "Mexico City",
    18: "Baku",
    19: "Sakhir Short",
    20: "Silverstone Short",
    21: "Austin Short",
    22: "Suzuka Short",
    23: "Hanoi",
    24: "Zandvoort",
    25: "Imola",
    26: "Portimao",
    27: "Jeddah",
    28: "Miami",
    29: "Las Vegas",
    30: "Losail",
    31: "Qatar",
}

SESSION_TYPES = {
    0: "unknown",
    1: "practice 1",
    2: "practice 2",
    3: "practice 3",
    4: "short practice",
    5: "qualifying 1",
    6: "qualifying 2",
    7: "qualifying 3",
    8: "short qualifying",
    9: "one-shot qualifying",
    10: "race",
    11: "race 2",
    12: "race 3",
    13: "time trial",
}

WEATHER = {
    0: "clear",
    1: "light cloud",
    2: "overcast",
    3: "light rain",
    4: "heavy rain",
    5: "storm",
}

# Actual compound -> (spoken name, C index)
ACTUAL_COMPOUNDS = {
    16: ("soft", "C5"),
    17: ("medium", "C4"),
    18: ("hard", "C3"),
    19: ("medium", "C2"),
    20: ("hard", "C1"),
    21: ("hard", "C0"),
    7: ("intermediate", None),
    8: ("wet", None),
    9: ("dry", None),
    10: ("wet", None),
}

VISUAL_COMPOUNDS = {16: "soft", 17: "medium", 18: "hard", 7: "intermediate", 8: "wet"}

FIA_FLAGS = {-1: "unknown", 0: "none", 1: "green", 2: "blue", 3: "yellow", 4: "red"}

SAFETY_CAR = {0: "none", 1: "safety car", 2: "virtual safety car", 3: "formation lap"}

PIT_STATUS = {0: "on track", 1: "in pit lane", 2: "in pit box"}

EVENT_NAMES = {
    "SSTA": "session started",
    "SEND": "session ended",
    "FTLP": "fastest lap",
    "RTMT": "retirement",
    "DRSE": "DRS enabled",
    "DRSD": "DRS disabled",
    "TMPT": "team mate in pits",
    "CHQF": "chequered flag",
    "RCWN": "race winner",
    "PENA": "penalty issued",
    "SPTP": "speed trap",
    "STLG": "start lights",
    "LGOT": "lights out",
    "DTSV": "drive through served",
    "SGSV": "stop go served",
    "FLBK": "flashback",
    "BUTN": "button status",
    "RDFL": "red flag",
    "OVTK": "overtake",
    "SCAR": "safety car",
    "COLL": "collision",
}


@dataclass
class LapRecord:
    lap_number: int
    lap_time_ms: int
    compound: str
    max_wear: float
    fuel_used_kg: float | None

    @property
    def seconds(self) -> float:
        return self.lap_time_ms / 1000.0


@dataclass
class RaceState:
    # identity
    session_uid: int = 0
    player_index: int = 255
    # connection
    last_packet_at: float = 0.0
    packets_seen: int = 0
    format_ok: bool = True
    format_error: str = ""
    # session
    track_id: int = -1
    session_type: int = 0
    weather: int = 0
    air_temp_c: int = 0
    track_temp_c: int = 0
    total_laps: int = 0
    track_length_m: int = 0
    safety_car: int = 0
    pit_window_ideal: int = 0
    pit_window_latest: int = 0
    pit_rejoin_position: int = 0
    forecast: list[dict[str, Any]] = field(default_factory=list)
    # lap
    lap: int = 0
    position: int = 0
    grid_position: int = 0
    last_lap_ms: int = 0
    current_lap_ms: int = 0
    sector: int = 0
    lap_distance: float = 0.0
    delta_ahead_ms: int = 0
    delta_leader_ms: int = 0
    pit_status: int = 0
    pit_stops: int = 0
    penalties_s: int = 0
    lap_invalid: bool = False
    driver_status: int = 0
    speed_trap_kph: float = 0.0
    # telemetry
    speed_kph: int = 0
    gear: int = 0
    rpm: int = 0
    throttle: float = 0.0
    brake: float = 0.0
    drs: int = 0
    brake_temps_c: tuple[int, int, int, int] = (0, 0, 0, 0)
    tyre_surface_c: tuple[int, int, int, int] = (0, 0, 0, 0)
    tyre_inner_c: tuple[int, int, int, int] = (0, 0, 0, 0)
    tyre_pressure_psi: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # car status
    fuel_kg: float = 0.0
    fuel_capacity_kg: float = 0.0
    fuel_laps_remaining: float = 0.0
    compound_code: int = 0
    tyre_age_laps: int = 0
    fia_flag: int = 0
    ers_joules: float = 0.0
    ers_mode: int = 0
    drs_allowed: int = 0
    # damage
    tyre_wear: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    tyre_damage: tuple[int, int, int, int] = (0, 0, 0, 0)
    wing_damage: int = 0
    floor_damage: int = 0
    sidepod_damage: int = 0
    # participants / gaps
    participants: list[dict[str, Any]] = field(default_factory=list)
    gap_behind_s: float | None = None
    gap_ahead_s: float | None = None
    # history
    lap_history: deque[LapRecord] = field(default_factory=deque, repr=False)
    fuel_per_lap_kg: float | None = None
    wear_per_lap: float | None = None
    events: deque[tuple[float, str]] = field(default_factory=deque, repr=False)
    # internals
    lap_start_fuel: float | None = None
    lap_start_wear: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ------------------------------------------------------------------
    def reset_session(self, uid: int) -> None:
        with self._lock:
            keep = (self.packets_seen, self.last_packet_at, self.format_ok, self.format_error)
            self.__dict__.update(RaceState().__dict__)
            self._lock = threading.RLock()
            self.packets_seen, self.last_packet_at, self.format_ok, self.format_error = keep
            self.session_uid = uid

    # ------------------------------------------------------------------
    def apply(self, packet_id: int, packet, header) -> None:
        now = time.time()
        with self._lock:
            self.packets_seen += 1
            self.last_packet_at = now
            if header.packet_format != 2024:
                self.format_ok = False
                self.format_error = f"game is sending format {header.packet_format}, expected 2024"
                return
            self.format_ok = True
            if header.session_uid != self.session_uid:
                self.reset_session(header.session_uid)
                self.last_packet_at = now
            self.player_index = header.player_car_index

            if packet is None:
                return
            handler = {
                p.SESSION: self._apply_session,
                p.LAP_DATA: self._apply_lap_data,
                p.CAR_TELEMETRY: self._apply_telemetry,
                p.CAR_STATUS: self._apply_status,
                p.CAR_DAMAGE: self._apply_damage,
                p.PARTICIPANTS: self._apply_participants,
                p.EVENT: self._apply_event,
            }.get(packet_id)
            if handler:
                handler(packet)

    # ------------------------------------------------------------------
    def _apply_session(self, packet) -> None:
        d = packet.data
        self.track_id = d.track_id
        self.session_type = d.session_type
        self.weather = d.weather
        self.air_temp_c = d.air_temperature
        self.track_temp_c = d.track_temperature
        self.total_laps = d.total_laps
        self.track_length_m = d.track_length
        self.safety_car = d.safety_car_status
        self.pit_window_ideal = d.pit_stop_window_ideal_lap
        self.pit_window_latest = d.pit_stop_window_latest_lap
        self.pit_rejoin_position = d.pit_stop_rejoin_position
        n = min(int(d.num_weather_forecast_samples), p.MAX_WEATHER_SAMPLES)
        self.forecast = [
            {
                "minutes": int(d.weather_forecast_samples[i].time_offset),
                "weather": WEATHER.get(int(d.weather_forecast_samples[i].weather), "unknown"),
                "rain_pct": int(d.weather_forecast_samples[i].rain_percentage),
            }
            for i in range(n)
        ]

    def _apply_lap_data(self, packet) -> None:
        if self.player_index >= p.MAX_CARS:
            return
        me = packet.lap_data[self.player_index]
        new_lap = int(me.current_lap_num)
        if self.lap and new_lap != self.lap:
            self._record_lap(me)
        self.lap = new_lap
        self.position = int(me.car_position)
        self.grid_position = int(me.grid_position)
        self.last_lap_ms = int(me.last_lap_time_in_ms)
        self.current_lap_ms = int(me.current_lap_time_in_ms)
        self.sector = int(me.sector)
        self.lap_distance = float(me.lap_distance)
        self.delta_ahead_ms = (
            int(me.delta_to_car_in_front_minutes_part) * 60000
            + int(me.delta_to_car_in_front_ms_part)
        )
        self.delta_leader_ms = (
            int(me.delta_to_race_leader_minutes_part) * 60000
            + int(me.delta_to_race_leader_ms_part)
        )
        self.pit_status = int(me.pit_status)
        self.pit_stops = int(me.num_pit_stops)
        self.penalties_s = int(me.penalties)
        self.lap_invalid = bool(me.current_lap_invalid)
        self.driver_status = int(me.driver_status)
        self.speed_trap_kph = float(me.speed_trap_fastest_speed)
        self._update_gaps(packet)

    def _update_gaps(self, packet) -> None:
        ahead = behind = None
        for i in range(p.MAX_CARS):
            car = packet.lap_data[i]
            pos = int(car.car_position)
            if pos == 0 or i == self.player_index:
                continue
            gap_ms = (
                int(car.delta_to_car_in_front_minutes_part) * 60000
                + int(car.delta_to_car_in_front_ms_part)
            )
            if pos == self.position + 1:
                behind = gap_ms / 1000.0 if gap_ms else None
        self.gap_ahead_s = self.delta_ahead_ms / 1000.0 if self.delta_ahead_ms else None
        self.gap_behind_s = behind

    def _record_lap(self, me) -> None:
        lap_ms = int(me.last_lap_time_in_ms)
        if lap_ms <= 0:
            self.lap_start_fuel = self.fuel_kg
            return
        wear = max(self.tyre_wear) if self.tyre_wear else 0.0
        fuel_used = None
        if self.lap_start_fuel is not None and self.fuel_kg:
            fuel_used = max(0.0, self.lap_start_fuel - self.fuel_kg)
            if 0.5 < fuel_used < 20:
                self.fuel_per_lap_kg = (
                    fuel_used
                    if self.fuel_per_lap_kg is None
                    else 0.7 * self.fuel_per_lap_kg + 0.3 * fuel_used
                )
        if self.lap_start_wear and wear > self.lap_start_wear:
            delta = wear - self.lap_start_wear
            self.wear_per_lap = (
                delta if self.wear_per_lap is None else 0.7 * self.wear_per_lap + 0.3 * delta
            )
        self.lap_history.append(
            LapRecord(
                lap_number=self.lap,
                lap_time_ms=lap_ms,
                compound=self.compound_name,
                max_wear=wear,
                fuel_used_kg=fuel_used,
            )
        )
        while len(self.lap_history) > 10:
            self.lap_history.popleft()
        self.lap_start_fuel = self.fuel_kg
        self.lap_start_wear = wear

    def _apply_telemetry(self, packet) -> None:
        if self.player_index >= p.MAX_CARS:
            return
        t = packet.car_telemetry_data[self.player_index]
        self.speed_kph = int(t.speed)
        self.gear = int(t.gear)
        self.rpm = int(t.engine_rpm)
        self.throttle = float(t.throttle)
        self.brake = float(t.brake)
        self.drs = int(t.drs)
        self.brake_temps_c = tuple(int(x) for x in t.brakes_temperature)
        self.tyre_surface_c = tuple(int(x) for x in t.tyres_surface_temperature)
        self.tyre_inner_c = tuple(int(x) for x in t.tyres_inner_temperature)
        self.tyre_pressure_psi = tuple(round(float(x), 1) for x in t.tyres_pressure)

    def _apply_status(self, packet) -> None:
        if self.player_index >= p.MAX_CARS:
            return
        s = packet.car_status_data[self.player_index]
        self.fuel_kg = float(s.fuel_in_tank)
        self.fuel_capacity_kg = float(s.fuel_capacity)
        self.fuel_laps_remaining = float(s.fuel_remaining_laps)
        self.compound_code = int(s.actual_tyre_compound)
        self.tyre_age_laps = int(s.tyres_age_laps)
        self.fia_flag = int(s.vehicle_fia_flags)
        self.ers_joules = float(s.ers_store_energy)
        self.ers_mode = int(s.ers_deploy_mode)
        self.drs_allowed = int(s.drs_allowed)
        if self.lap_start_fuel is None or self.lap_start_fuel <= 0:
            self.lap_start_fuel = self.fuel_kg

    def _apply_damage(self, packet) -> None:
        if self.player_index >= p.MAX_CARS:
            return
        d = packet.car_damage_data[self.player_index]
        self.tyre_wear = tuple(round(float(x), 1) for x in d.tyres_wear)
        self.tyre_damage = tuple(int(x) for x in d.tyres_damage)
        self.wing_damage = max(int(d.front_left_wing_damage), int(d.front_right_wing_damage))
        self.floor_damage = int(d.floor_damage)
        self.sidepod_damage = int(d.sidepod_damage)

    def _apply_participants(self, packet) -> None:
        n = min(int(packet.num_active_cars), p.MAX_CARS)
        out = []
        for i in range(n):
            part = packet.participants[i]
            name = bytes(part.name).split(b"\0")[0].decode("utf-8", "replace").strip()
            out.append(
                {
                    "index": i,
                    "name": name,
                    "team_id": int(part.team_id),
                    "race_number": int(part.race_number),
                    "ai": bool(part.ai_controlled),
                }
            )
        self.participants = out

    def _apply_event(self, packet) -> None:
        code = bytes(packet.event_string_code).decode("ascii", "replace")
        label = EVENT_NAMES.get(code, code)
        if code == "SCAR":
            label = f"safety car: {packet.event_details.safety_car_type}"
        elif code == "PENA":
            label = f"penalty issued ({packet.event_details.vehicle_idx})"
        elif code == "OVTK":
            label = (
                f"overtake: car {packet.event_details.overtaking_vehicle_idx} on "
                f"{packet.event_details.being_overtaken_vehicle_idx}"
            )
        self.events.append((time.time(), label))
        while len(self.events) > 40:
            self.events.popleft()

    # ------------------------------------------------------------------
    # read-only helpers
    # ------------------------------------------------------------------
    @property
    def compound_name(self) -> str:
        name, _ = ACTUAL_COMPOUNDS.get(self.compound_code, ("unknown", None))
        return name

    @property
    def compound_c_index(self) -> str | None:
        _, c = ACTUAL_COMPOUNDS.get(self.compound_code, (None, None))
        return c

    @property
    def track_name(self) -> str:
        return TRACKS.get(self.track_id, "unknown track")

    @property
    def connected(self) -> bool:
        return (time.time() - self.last_packet_at) < 3.0 and self.packets_seen > 0

    def fuel_to_end_kg(self) -> float | None:
        remaining = self.laps_remaining()
        if remaining is None or not self.fuel_per_lap_kg:
            return None
        return self.fuel_per_lap_kg * remaining

    def laps_remaining(self) -> int | None:
        if self.total_laps <= 0 or self.lap <= 0:
            return None
        return max(0, self.total_laps - self.lap + 1)

    def fuel_surplus_laps(self) -> float | None:
        """Positive = laps of fuel in hand, negative = short."""
        if not self.fuel_per_lap_kg:
            return None
        return self.fuel_kg / self.fuel_per_lap_kg - (self.laps_remaining() or 0)

    def predicted_tyre_life(self) -> float | None:
        if not self.wear_per_lap or self.wear_per_lap <= 0.01:
            return None
        worst = max(self.tyre_wear) if self.tyre_wear else 0.0
        return max(0.0, (100.0 - worst - 15.0) / self.wear_per_lap)

    def recent_events(self, seconds: float = 15.0) -> list[str]:
        cutoff = time.time() - seconds
        return [label for ts, label in self.events if ts >= cutoff]

    def snapshot(self) -> dict[str, Any]:
        """Compact, JSON-safe view for the language model and console."""
        with self._lock:
            last5 = list(self.lap_history)[-5:]
            return {
                "connected": self.connected,
                "track": self.track_name,
                "session": SESSION_TYPES.get(self.session_type, "unknown"),
                "weather": WEATHER.get(self.weather, "unknown"),
                "air_temp_c": self.air_temp_c,
                "track_temp_c": self.track_temp_c,
                "safety_car": SAFETY_CAR.get(self.safety_car, "none"),
                "flag": FIA_FLAGS.get(self.fia_flag, "unknown"),
                "lap": self.lap,
                "total_laps": self.total_laps,
                "laps_remaining": self.laps_remaining(),
                "position": self.position,
                "grid_position": self.grid_position,
                "last_lap_s": round(self.last_lap_ms / 1000.0, 3) if self.last_lap_ms else None,
                "current_lap_s": round(self.current_lap_ms / 1000.0, 3),
                "lap_invalid": self.lap_invalid,
                "sector": self.sector + 1,
                "gap_ahead_s": self.gap_ahead_s,
                "gap_behind_s": self.gap_behind_s,
                "gap_to_leader_s": round(self.delta_leader_ms / 1000.0, 1)
                if self.delta_leader_ms
                else None,
                "driver_name": self.driver_name,
                "pit_status": PIT_STATUS.get(self.pit_status, "on track"),
                "pit_stops": self.pit_stops,
                "pit_window_ideal_lap": self.pit_window_ideal,
                "pit_window_latest_lap": self.pit_window_latest,
                "penalties_s": self.penalties_s,
                "speed_kph": self.speed_kph,
                "gear": self.gear,
                "rpm": self.rpm,
                "drs": bool(self.drs),
                "ers_pct": round(100.0 * self.ers_joules / 4_000_000.0, 0),
                "ers_deploy_mode": self.ers_mode,
                "fuel_kg": round(self.fuel_kg, 1),
                "fuel_laps_remaining": round(self.fuel_laps_remaining, 1),
                "fuel_per_lap_kg": round(self.fuel_per_lap_kg, 2)
                if self.fuel_per_lap_kg
                else None,
                "fuel_to_end_kg": round(self.fuel_to_end_kg(), 2)
                if self.fuel_to_end_kg() is not None
                else None,
                "fuel_surplus_laps": round(self.fuel_surplus_laps(), 2)
                if self.fuel_surplus_laps() is not None
                else None,
                "tyre": {
                    "compound": self.compound_name,
                    "c_index": self.compound_c_index,
                    "age_laps": self.tyre_age_laps,
                    "wear_pct": {
                        "front_left": self.tyre_wear[0],
                        "front_right": self.tyre_wear[1],
                        "rear_left": self.tyre_wear[2],
                        "rear_right": self.tyre_wear[3],
                    },
                    "wear_rate_per_lap": round(self.wear_per_lap, 2)
                    if self.wear_per_lap
                    else None,
                    "predicted_life_laps": round(self.predicted_tyre_life(), 1)
                    if self.predicted_tyre_life() is not None
                    else None,
                    "surface_c": {
                        "front_left": self.tyre_surface_c[0],
                        "front_right": self.tyre_surface_c[1],
                        "rear_left": self.tyre_surface_c[2],
                        "rear_right": self.tyre_surface_c[3],
                    },
                    "inner_c": {
                        "front_left": self.tyre_inner_c[0],
                        "front_right": self.tyre_inner_c[1],
                        "rear_left": self.tyre_inner_c[2],
                        "rear_right": self.tyre_inner_c[3],
                    },
                },
                "damage": {
                    "front_wing": self.wing_damage,
                    "floor": self.floor_damage,
                    "sidepod": self.sidepod_damage,
                },
                "rain_forecast": [
                    f"+{s['minutes']}m {s['weather']} {s['rain_pct']}%" for s in self.forecast[:4]
                ],
                "recent_laps": [
                    {"lap": r.lap_number, "time_s": round(r.seconds, 3), "tyre": r.compound}
                    for r in last5
                ],
                "recent_events": self.recent_events(),
            }

    @property
    def driver_name(self) -> str:
        if 0 <= self.player_index < len(self.participants):
            return self.participants[self.player_index]["name"]
        return "driver"
