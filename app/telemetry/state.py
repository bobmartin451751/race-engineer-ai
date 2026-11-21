"""Live race state assembled from F1 24 UDP packets.

All 22 cars are tracked, so the engineer can answer questions about rivals,
not just the player's car. The network thread writes, voice threads read, so
public accessors take the internal lock.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import packets as p

TRACKS = {
    0: "Melbourne", 1: "Shanghai", 2: "Sakhir", 3: "Barcelona", 4: "Monaco",
    5: "Montreal", 6: "Silverstone", 7: "Hockenheim", 8: "Hungaroring",
    9: "Spa-Francorchamps", 10: "Monza", 11: "Singapore", 12: "Suzuka",
    13: "Abu Dhabi", 14: "Austin", 15: "Sao Paulo", 16: "Spielberg",
    17: "Mexico City", 18: "Baku", 19: "Sakhir Short", 20: "Silverstone Short",
    21: "Austin Short", 22: "Suzuka Short", 23: "Hanoi", 24: "Zandvoort",
    25: "Imola", 26: "Portimao", 27: "Jeddah", 28: "Miami", 29: "Las Vegas",
    30: "Losail", 31: "Qatar",
}

SESSION_TYPES = {
    0: "unknown", 1: "practice 1", 2: "practice 2", 3: "practice 3",
    4: "short practice", 5: "qualifying 1", 6: "qualifying 2", 7: "qualifying 3",
    8: "short qualifying", 9: "one-shot qualifying", 10: "race", 11: "race 2",
    12: "race 3", 13: "time trial",
}

WEATHER = {
    0: "clear", 1: "light cloud", 2: "overcast", 3: "light rain", 4: "heavy rain",
    5: "storm",
}

# Actual compound -> (spoken name, C index)
ACTUAL_COMPOUNDS = {
    16: ("soft", "C5"), 17: ("medium", "C4"), 18: ("hard", "C3"),
    19: ("medium", "C2"), 20: ("hard", "C1"), 21: ("hard", "C0"),
    7: ("intermediate", None), 8: ("wet", None), 9: ("dry", None),
    10: ("wet", None), 11: ("supersoft", None), 12: ("soft", None),
    13: ("medium", None), 14: ("hard", None), 15: ("wet", None),
}

FIA_FLAGS = {-1: "unknown", 0: "none", 1: "green", 2: "blue", 3: "yellow", 4: "red"}
ERS_MODES = {0: "none", 1: "medium", 2: "hotlap", 3: "overtake"}
FUEL_MIXES = {0: "lean", 1: "standard", 2: "rich", 3: "max"}

# m_visualTyreCompound is what the game itself displays. It is the reliable
# source for soft/medium/hard; m_actualTyreCompound must not be used for names.
VISUAL_COMPOUNDS = {
    16: "soft", 17: "medium", 18: "hard",
    7: "intermediate", 8: "wet",
    11: "supersoft", 12: "soft", 13: "medium", 14: "hard", 15: "wet",
    19: "supersoft", 20: "soft", 21: "medium", 22: "hard",
}
SAFETY_CAR = {0: "none", 1: "safety car", 2: "virtual safety car", 3: "formation lap"}
PIT_STATUS = {0: "on track", 1: "in pit lane", 2: "in pit box"}
RESULT_STATUS = {
    0: "invalid", 1: "inactive", 2: "active", 3: "finished", 4: "DNF",
    5: "disqualified", 6: "not classified", 7: "retired",
}
DRIVER_STATUS = {0: "in garage", 1: "flying lap", 2: "in lap", 3: "out lap", 4: "on track"}

# The game orders wheel arrays rear-left, rear-right, front-left, front-right.
CORNERS = ("rear_left", "rear_right", "front_left", "front_right")


def _corner_dict(values) -> dict[str, Any]:
    return {name: value for name, value in zip(CORNERS, values)}


EVENT_NAMES = {
    "SSTA": "session started", "SEND": "session ended", "FTLP": "fastest lap",
    "RTMT": "retirement", "DRSE": "DRS enabled", "DRSD": "DRS disabled",
    "TMPT": "team mate in pits", "CHQF": "chequered flag", "RCWN": "race winner",
    "PENA": "penalty issued", "SPTP": "speed trap", "STLG": "start lights",
    "LGOT": "lights out", "DTSV": "drive through served", "SGSV": "stop go served",
    "FLBK": "flashback", "BUTN": "button status", "RDFL": "red flag",
    "OVTK": "overtake", "SCAR": "safety car", "COLL": "collision",
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
class CarState:
    """Everything known about one car in the session."""

    index: int
    name: str = "unknown"
    team_id: int = 255
    race_number: int = 0
    ai: bool = True
    # lap data
    position: int = 0
    lap: int = 0
    grid_position: int = 0
    last_lap_ms: int = 0
    current_lap_ms: int = 0
    sector: int = 0
    lap_distance: float = 0.0
    total_distance: float = 0.0
    delta_ahead_ms: int = 0
    delta_leader_ms: int = 0
    pit_status: int = 0
    pit_stops: int = 0
    penalties_s: int = 0
    lap_invalid: bool = False
    driver_status: int = 0
    result_status: int = 0
    speed_trap_kph: float = 0.0
    # telemetry
    speed_kph: int = 0
    gear: int = 0
    rpm: int = 0
    throttle: float = 0.0
    brake: float = 0.0
    drs: int = 0
    brake_temps_c: tuple = (0, 0, 0, 0)
    tyre_surface_c: tuple = (0, 0, 0, 0)
    tyre_inner_c: tuple = (0, 0, 0, 0)
    tyre_pressure_psi: tuple = (0.0, 0.0, 0.0, 0.0)
    # car status
    fuel_kg: float = 0.0
    fuel_capacity_kg: float = 0.0
    fuel_laps_remaining: float = 0.0
    fuel_mix: int = 0
    compound_code: int = 0
    visual_compound_code: int = 0
    tyre_age_laps: int = 0
    fia_flag: int = 0
    ers_joules: float = 0.0
    ers_mode: int = 0
    ers_harvested_mguk_j: float = 0.0
    ers_harvested_mguh_j: float = 0.0
    ers_deployed_j: float = 0.0
    brake_bias: int = 0
    engine_temp_c: int = 0
    drs_allowed: int = 0
    drs_activation_distance_m: int = 0
    wear_samples: list = field(default_factory=list)
    last_wear_lap: int = 0
    # damage
    tyre_wear: tuple = (0.0, 0.0, 0.0, 0.0)
    tyre_damage: tuple = (0, 0, 0, 0)
    brakes_damage: tuple = (0, 0, 0, 0)
    wing_damage: int = 0
    floor_damage: int = 0
    diffuser_damage: int = 0
    sidepod_damage: int = 0
    drs_fault: int = 0
    ers_fault: int = 0
    gearbox_damage: int = 0
    engine_damage: int = 0
    engine_wear: dict = field(default_factory=dict)
    engine_blown: int = 0
    engine_seized: int = 0
    # setup / tyres / history
    setup: dict = field(default_factory=dict)
    tyre_sets: list = field(default_factory=list)
    session_laps: list = field(default_factory=list)
    tyre_stints: list = field(default_factory=list)
    best_lap_ms: int = 0
    best_s1_ms: int = 0
    best_s2_ms: int = 0
    best_s3_ms: int = 0

    @property
    def compound_name(self) -> str:
        name = VISUAL_COMPOUNDS.get(self.visual_compound_code)
        if name:
            return name
        return ACTUAL_COMPOUNDS.get(self.compound_code, ("unknown", None))[0]

    @property
    def compound_c_index(self) -> str | None:
        return ACTUAL_COMPOUNDS.get(self.compound_code, (None, None))[1]

    @property
    def wear_rate_per_lap(self) -> float | None:
        if len(self.wear_samples) < 2:
            return None
        (lap_a, wear_a), (lap_b, wear_b) = self.wear_samples[-2], self.wear_samples[-1]
        laps = lap_b - lap_a
        if laps <= 0 or wear_b <= wear_a:
            return None
        return (wear_b - wear_a) / laps

    @property
    def predicted_tyre_life(self) -> float | None:
        rate = self.wear_rate_per_lap
        if not rate:
            return None
        worst = max(self.tyre_wear) if self.tyre_wear else 0.0
        return max(0.0, (100.0 - worst - 15.0) / rate)

    def to_dict(self) -> dict[str, Any]:
        gap = self.delta_leader_ms / 1000.0 if self.delta_leader_ms else 0.0
        life = self.predicted_tyre_life
        wear = max(self.tyre_wear) if self.tyre_wear else 0.0
        return {
            "pos": self.position,
            "driver": self.name,
            "gap_to_leader_s": round(gap, 1),
            "lap": self.lap,
            "tyre": self.compound_name,
            "tyre_age": self.tyre_age_laps,
            "wear_pct": round(wear, 1),
            "tyre_life": round(life, 1) if life is not None else None,
            "predicted_pit_lap": self.lap + round(life) if life is not None else None,
            "last_lap_s": round(self.last_lap_ms / 1000.0, 3) if self.last_lap_ms else None,
            "stops": self.pit_stops,
            "status": PIT_STATUS.get(self.pit_status, "on track"),
            "result": RESULT_STATUS.get(self.result_status, "unknown"),
            "penalties_s": self.penalties_s,
            "is_ai": self.ai,
        }


@dataclass
class RaceState:
    # identity / connection
    session_uid: int = 0
    player_index: int = 255
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
    forecast: list = field(default_factory=list)
    # cars
    cars: list = field(default_factory=lambda: [CarState(i) for i in range(p.MAX_CARS)])
    # player-derived
    gap_ahead_s: float | None = None
    gap_behind_s: float | None = None
    fuel_per_lap_kg: float | None = None
    wear_per_lap: float | None = None
    lap_history: deque = field(default_factory=deque, repr=False)
    events: deque = field(default_factory=deque, repr=False)
    final_classification: list = field(default_factory=list)
    lobby: list = field(default_factory=list)
    motion: dict = field(default_factory=dict)
    pit_loss_s: float = 21.0
    traffic_window_s: float = 2.0
    # internals
    lap_start_fuel: float | None = None
    lap_start_wear: float = 0.0
    _gap_history: deque = field(default_factory=lambda: deque(maxlen=600), repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ------------------------------------------------------------------
    @property
    def player(self) -> CarState:
        return self.cars[self.player_index] if 0 <= self.player_index < len(self.cars) else self.cars[0]

    def reset_session(self, uid: int) -> None:
        with self._lock:
            keep = (self.packets_seen, self.last_packet_at, self.format_ok, self.format_error)
            self.__dict__ = RaceState().__dict__
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
                p.MOTION: self._apply_motion,
                p.SESSION: self._apply_session,
                p.LAP_DATA: self._apply_lap_data,
                p.EVENT: self._apply_event,
                p.PARTICIPANTS: self._apply_participants,
                p.CAR_SETUPS: self._apply_setups,
                p.CAR_TELEMETRY: self._apply_telemetry,
                p.CAR_STATUS: self._apply_status,
                p.FINAL_CLASSIFICATION: self._apply_final_classification,
                p.LOBBY_INFO: self._apply_lobby,
                p.CAR_DAMAGE: self._apply_damage,
                p.SESSION_HISTORY: self._apply_session_history,
                p.TYRE_SETS: self._apply_tyre_sets,
                p.MOTION_EX: self._apply_motion_ex,
                p.TIME_TRIAL: self._apply_time_trial,
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
        for i, me in enumerate(packet.lap_data):
            car = self.cars[i]
            new_lap = int(me.current_lap_num)
            if i == self.player_index and car.lap and new_lap != car.lap:
                self._record_player_lap(car, me)
            car.lap = new_lap
            car.position = int(me.car_position)
            car.grid_position = int(me.grid_position)
            car.last_lap_ms = int(me.last_lap_time_in_ms)
            car.current_lap_ms = int(me.current_lap_time_in_ms)
            car.sector = int(me.sector)
            car.lap_distance = float(me.lap_distance)
            car.total_distance = float(me.total_distance)
            car.delta_ahead_ms = (
                int(me.delta_to_car_in_front_minutes_part) * 60000
                + int(me.delta_to_car_in_front_ms_part)
            )
            car.delta_leader_ms = (
                int(me.delta_to_race_leader_minutes_part) * 60000
                + int(me.delta_to_race_leader_ms_part)
            )
            car.pit_status = int(me.pit_status)
            car.pit_stops = int(me.num_pit_stops)
            car.penalties_s = int(me.penalties)
            car.lap_invalid = bool(me.current_lap_invalid)
            car.driver_status = int(me.driver_status)
            car.result_status = int(me.result_status)
            car.speed_trap_kph = float(me.speed_trap_fastest_speed)
        self._update_gaps()
        me = self.player
        if self.lap_start_fuel is None and me.fuel_kg:
            self.lap_start_fuel = me.fuel_kg

    def _update_gaps(self) -> None:
        me = self.player
        self.gap_ahead_s = me.delta_ahead_ms / 1000.0 if me.delta_ahead_ms else None
        behind = None
        for car in self.cars:
            if car.position == me.position + 1 and car.index != me.index:
                if car.delta_ahead_ms:
                    behind = car.delta_ahead_ms / 1000.0
                break
        self.gap_behind_s = behind
        self._gap_history.append((time.time(), self.gap_ahead_s))

    def _record_player_lap(self, car: CarState, me) -> None:
        lap_ms = int(me.last_lap_time_in_ms)
        if lap_ms <= 0:
            self.lap_start_fuel = car.fuel_kg
            return
        wear = max(car.tyre_wear) if car.tyre_wear else 0.0
        fuel_used = None
        if self.lap_start_fuel is not None and car.fuel_kg:
            fuel_used = max(0.0, self.lap_start_fuel - car.fuel_kg)
            if 0.5 < fuel_used < 20:
                self.fuel_per_lap_kg = (
                    fuel_used if self.fuel_per_lap_kg is None
                    else 0.7 * self.fuel_per_lap_kg + 0.3 * fuel_used
                )
        if self.lap_start_wear and wear > self.lap_start_wear:
            delta = wear - self.lap_start_wear
            self.wear_per_lap = (
                delta if self.wear_per_lap is None else 0.7 * self.wear_per_lap + 0.3 * delta
            )
        self.lap_history.append(
            LapRecord(
                lap_number=car.lap,
                lap_time_ms=lap_ms,
                compound=car.compound_name,
                max_wear=wear,
                fuel_used_kg=fuel_used,
            )
        )
        while len(self.lap_history) > 10:
            self.lap_history.popleft()
        self.lap_start_fuel = car.fuel_kg
        self.lap_start_wear = wear

    def _apply_telemetry(self, packet) -> None:
        for i, t in enumerate(packet.car_telemetry_data):
            car = self.cars[i]
            car.speed_kph = int(t.speed)
            car.gear = int(t.gear)
            car.rpm = int(t.engine_rpm)
            car.throttle = float(t.throttle)
            car.brake = float(t.brake)
            car.drs = int(t.drs)
            car.brake_temps_c = tuple(int(x) for x in t.brakes_temperature)
            car.tyre_surface_c = tuple(int(x) for x in t.tyres_surface_temperature)
            car.tyre_inner_c = tuple(int(x) for x in t.tyres_inner_temperature)
            car.tyre_pressure_psi = tuple(round(float(x), 1) for x in t.tyres_pressure)
            car.engine_temp_c = int(t.engine_temperature)

    def _apply_status(self, packet) -> None:
        for i, s in enumerate(packet.car_status_data):
            car = self.cars[i]
            car.fuel_kg = float(s.fuel_in_tank)
            car.fuel_capacity_kg = float(s.fuel_capacity)
            car.fuel_laps_remaining = float(s.fuel_remaining_laps)
            car.fuel_mix = int(s.fuel_mix)
            car.compound_code = int(s.actual_tyre_compound)
            car.visual_compound_code = int(s.visual_tyre_compound)
            car.tyre_age_laps = int(s.tyres_age_laps)
            car.fia_flag = int(s.vehicle_fia_flags)
            car.ers_joules = float(s.ers_store_energy)
            car.ers_mode = int(s.ers_deploy_mode)
            car.ers_harvested_mguk_j = float(s.ers_harvested_this_lap_mguk)
            car.ers_harvested_mguh_j = float(s.ers_harvested_this_lap_mguh)
            car.ers_deployed_j = float(s.ers_deployed_this_lap)
            car.brake_bias = int(s.front_brake_bias)
            car.drs_allowed = int(s.drs_allowed)
            car.drs_activation_distance_m = int(s.drs_activation_distance)
        me = self.player
        if self.lap_start_fuel is None or self.lap_start_fuel <= 0:
            self.lap_start_fuel = me.fuel_kg

    def _apply_damage(self, packet) -> None:
        for i, d in enumerate(packet.car_damage_data):
            car = self.cars[i]
            car.tyre_wear = tuple(round(float(x), 1) for x in d.tyres_wear)
            car.tyre_damage = tuple(int(x) for x in d.tyres_damage)
            car.brakes_damage = tuple(int(x) for x in d.brakes_damage)
            car.wing_damage = max(int(d.front_left_wing_damage), int(d.front_right_wing_damage))
            car.floor_damage = int(d.floor_damage)
            car.diffuser_damage = int(d.diffuser_damage)
            car.sidepod_damage = int(d.sidepod_damage)
            car.drs_fault = int(d.drs_fault)
            car.ers_fault = int(d.ers_fault)
            car.gearbox_damage = int(d.gearbox_damage)
            car.engine_damage = int(d.engine_damage)
            car.engine_wear = {
                "mguh": int(d.engine_mguh_wear),
                "es": int(d.engine_es_wear),
                "ce": int(d.engine_ce_wear),
                "ice": int(d.engine_ice_wear),
                "mguk": int(d.engine_mguk_wear),
                "tc": int(d.engine_tc_wear),
            }
            car.engine_blown = int(d.engine_blown)
            car.engine_seized = int(d.engine_seized)
            if car.lap and car.lap != car.last_wear_lap:
                car.wear_samples.append((car.lap, max(car.tyre_wear) if car.tyre_wear else 0.0))
                while len(car.wear_samples) > 10:
                    car.wear_samples.pop(0)
                car.last_wear_lap = car.lap

    def _apply_participants(self, packet) -> None:
        n = min(int(packet.num_active_cars), p.MAX_CARS)
        for i in range(n):
            part = packet.participants[i]
            car = self.cars[i]
            car.name = bytes(part.name).split(b"\0")[0].decode("utf-8", "replace").strip()
            car.team_id = int(part.team_id)
            car.race_number = int(part.race_number)
            car.ai = bool(part.ai_controlled)

    def _apply_setups(self, packet) -> None:
        for i, s in enumerate(packet.car_setups):
            self.cars[i].setup = {
                "front_wing": int(s.front_wing),
                "rear_wing": int(s.rear_wing),
                "on_throttle": int(s.on_throttle),
                "off_throttle": int(s.off_throttle),
                "front_camber": round(float(s.front_camber), 2),
                "rear_camber": round(float(s.rear_camber), 2),
                "front_toe": round(float(s.front_toe), 2),
                "rear_toe": round(float(s.rear_toe), 2),
                "front_suspension": int(s.front_suspension),
                "rear_suspension": int(s.rear_suspension),
                "front_arb": int(s.front_anti_roll_bar),
                "rear_arb": int(s.rear_anti_roll_bar),
                "front_ride_height": int(s.front_suspension_height),
                "rear_ride_height": int(s.rear_suspension_height),
                "brake_pressure": int(s.brake_pressure),
                "brake_bias": int(s.brake_bias),
                "engine_braking": int(s.engine_braking),
                "ballast": int(s.ballast),
                "fuel_load": round(float(s.fuel_load), 1),
                "tyre_pressure": {
                    "rear_left": round(float(s.rear_left_tyre_pressure), 1),
                    "rear_right": round(float(s.rear_right_tyre_pressure), 1),
                    "front_left": round(float(s.front_left_tyre_pressure), 1),
                    "front_right": round(float(s.front_right_tyre_pressure), 1),
                },
            }
        self.cars[self.player_index].setup["next_front_wing"] = round(
            float(packet.next_front_wing_value), 2
        )

    def _apply_final_classification(self, packet) -> None:
        n = min(int(packet.num_cars), p.MAX_CARS)
        out = []
        for i in range(n):
            d = packet.classification_data[i]
            out.append(
                {
                    "position": int(d.position),
                    "driver": self.cars[i].name,
                    "laps": int(d.num_laps),
                    "grid": int(d.grid_position),
                    "points": int(d.points),
                    "stops": int(d.num_pit_stops),
                    "result": RESULT_STATUS.get(int(d.result_status), "unknown"),
                    "best_lap_s": round(int(d.best_lap_time_in_ms) / 1000.0, 3)
                    if d.best_lap_time_in_ms else None,
                    "total_time_s": round(float(d.total_race_time), 3),
                    "penalties_s": int(d.penalties_time),
                    "stints": [
                        {
                            "end_lap": int(d.tyre_stints_end_laps[j]),
                            "compound": ACTUAL_COMPOUNDS.get(
                                int(d.tyre_stints_actual[j]), ("unknown", None)
                            )[0],
                        }
                        for j in range(min(int(d.num_tyre_stints), 8))
                    ],
                }
            )
        self.final_classification = out

    def _apply_lobby(self, packet) -> None:
        n = min(int(packet.num_players), p.MAX_CARS)
        self.lobby = [
            {
                "driver": bytes(packet.lobby_players[i].name)
                .split(b"\0")[0]
                .decode("utf-8", "replace")
                .strip(),
                "team_id": int(packet.lobby_players[i].team_id),
                "car_number": int(packet.lobby_players[i].car_number),
                "ready": int(packet.lobby_players[i].ready_status),
                "ai": bool(packet.lobby_players[i].ai_controlled),
            }
            for i in range(n)
        ]

    def _apply_session_history(self, packet) -> None:
        idx = int(packet.car_idx)
        if idx >= p.MAX_CARS:
            return
        car = self.cars[idx]
        laps = []
        for i in range(min(int(packet.num_laps), 100)):
            h = packet.lap_history_data[i]
            if not h.lap_time_in_ms:
                continue
            laps.append(
                {
                    "lap": i + 1,
                    "time_s": round(int(h.lap_time_in_ms) / 1000.0, 3),
                    "s1_s": round(
                        int(h.sector1_time_minutes_part) * 60
                        + int(h.sector1_time_ms_part) / 1000.0, 3),
                    "s2_s": round(
                        int(h.sector2_time_minutes_part) * 60
                        + int(h.sector2_time_ms_part) / 1000.0, 3),
                    "s3_s": round(
                        int(h.sector3_time_minutes_part) * 60
                        + int(h.sector3_time_ms_part) / 1000.0, 3),
                    "valid": bool(h.lap_valid_bit_flags & 0x01),
                }
            )
        car.session_laps = laps
        car.tyre_stints = [
            {
                "end_lap": int(packet.tyre_stints_history_data[i].end_lap),
                "compound": ACTUAL_COMPOUNDS.get(
                    int(packet.tyre_stints_history_data[i].tyre_actual_compound),
                    ("unknown", None),
                )[0],
            }
            for i in range(min(int(packet.num_tyre_stints), 8))
        ]
        valid = [lap for lap in laps if lap["valid"]]
        if valid:
            car.best_lap_ms = int(min(lap["time_s"] for lap in valid) * 1000)
            car.best_s1_ms = int(min(lap["s1_s"] for lap in valid) * 1000)
            car.best_s2_ms = int(min(lap["s2_s"] for lap in valid) * 1000)
            car.best_s3_ms = int(min(lap["s3_s"] for lap in valid) * 1000)

    def _apply_tyre_sets(self, packet) -> None:
        idx = int(packet.car_idx)
        if idx >= p.MAX_CARS:
            return
        sets = []
        for i in range(p.MAX_TYRE_SETS):
            s = packet.tyre_set_data[i]
            if not s.actual_tyre_compound:
                continue
            actual_name = ACTUAL_COMPOUNDS.get(int(s.actual_tyre_compound), ("unknown", None))[0]
            visual_name = VISUAL_COMPOUNDS.get(int(s.visual_tyre_compound), actual_name)
            sets.append(
                {
                    "index": i,
                    "compound": visual_name,
                    "actual": actual_name,
                    "visual_code": int(s.visual_tyre_compound),
                    "actual_code": int(s.actual_tyre_compound),
                    "wear": int(s.wear),
                    "available": bool(s.available),
                    "laps_left": int(s.life_span),
                    "usable_life": int(s.usable_life),
                    "delta_ms": int(s.lap_delta_time),
                    "fitted": bool(s.fitted),
                }
            )
        self.cars[idx].tyre_sets = sets

    def _apply_motion(self, packet) -> None:
        idx = self.player_index
        if idx >= p.MAX_CARS:
            return
        m = packet.car_motion_data[idx]
        self.motion = {
            "g_lat": round(float(m.g_force_lateral), 2),
            "g_long": round(float(m.g_force_longitudinal), 2),
            "g_vert": round(float(m.g_force_vertical), 2),
            "yaw": round(float(m.yaw), 3),
            "pitch": round(float(m.pitch), 3),
            "roll": round(float(m.roll), 3),
            "world_velocity": [
                round(float(m.world_velocity_x), 2),
                round(float(m.world_velocity_y), 2),
                round(float(m.world_velocity_z), 2),
            ],
        }

    def _apply_motion_ex(self, packet) -> None:
        d = packet.data
        self.motion.update(
            {
                "front_aero_height": round(float(d.front_aero_height), 4),
                "rear_aero_height": round(float(d.rear_aero_height), 4),
                "front_roll_angle": round(float(d.front_roll_angle), 4),
                "rear_roll_angle": round(float(d.rear_roll_angle), 4),
                "chassis_yaw": round(float(d.chassis_yaw), 4),
                "suspension_position": [round(float(x), 4) for x in d.suspension_position],
                "wheel_slip_ratio": [round(float(x), 3) for x in d.wheel_slip_ratio],
                "wheel_vert_force": [round(float(x), 1) for x in d.wheel_vert_force],
            }
        )

    def _apply_time_trial(self, packet) -> None:
        def dataset(ds):
            return {
                "lap_s": round(int(ds.lap_time_in_ms) / 1000.0, 3),
                "s1_s": round(int(ds.sector1_time_in_ms) / 1000.0, 3),
                "s2_s": round(int(ds.sector2_time_in_ms) / 1000.0, 3),
                "s3_s": round(int(ds.sector3_time_in_ms) / 1000.0, 3),
                "valid": bool(ds.valid),
            }

        self.motion["time_trial"] = {
            "session_best": dataset(packet.player_session_best),
            "personal_best": dataset(packet.personal_best),
            "rival": dataset(packet.rival),
        }

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
    # player mirror properties (keeps the rest of the app simple)
    # ------------------------------------------------------------------
    @property
    def lap(self) -> int:
        return self.player.lap

    @property
    def position(self) -> int:
        return self.player.position

    @property
    def last_lap_ms(self) -> int:
        return self.player.last_lap_ms

    @property
    def sector(self) -> int:
        return self.player.sector

    @property
    def lap_invalid(self) -> bool:
        return self.player.lap_invalid

    @property
    def pit_status(self) -> int:
        return self.player.pit_status

    @property
    def pit_stops(self) -> int:
        return self.player.pit_stops

    @property
    def penalties_s(self) -> int:
        return self.player.penalties_s

    @property
    def speed_kph(self) -> int:
        return self.player.speed_kph

    @property
    def gear(self) -> int:
        return self.player.gear

    @property
    def rpm(self) -> int:
        return self.player.rpm

    @property
    def drs(self) -> int:
        return self.player.drs

    @property
    def tyre_wear(self) -> tuple:
        return self.player.tyre_wear

    @property
    def tyre_damage(self) -> tuple:
        return self.player.tyre_damage

    @property
    def wing_damage(self) -> int:
        return self.player.wing_damage

    @property
    def floor_damage(self) -> int:
        return self.player.floor_damage

    @property
    def diffuser_damage(self) -> int:
        return self.player.diffuser_damage

    @property
    def sidepod_damage(self) -> int:
        return self.player.sidepod_damage

    @property
    def engine_damage(self) -> int:
        return self.player.engine_damage

    @property
    def tyre_surface_c(self) -> tuple:
        return self.player.tyre_surface_c

    @property
    def tyre_inner_c(self) -> tuple:
        return self.player.tyre_inner_c

    @property
    def tyre_pressure_psi(self) -> tuple:
        return self.player.tyre_pressure_psi

    @property
    def brake_temps_c(self) -> tuple:
        return self.player.brake_temps_c

    @property
    def fuel_kg(self) -> float:
        return self.player.fuel_kg

    @property
    def fuel_laps_remaining(self) -> float:
        return self.player.fuel_laps_remaining

    @property
    def fuel_mix(self) -> int:
        return self.player.fuel_mix

    @property
    def compound_code(self) -> int:
        return self.player.compound_code

    @property
    def tyre_age_laps(self) -> int:
        return self.player.tyre_age_laps

    @property
    def fia_flag(self) -> int:
        return self.player.fia_flag

    @property
    def ers_joules(self) -> float:
        return self.player.ers_joules

    @property
    def ers_mode(self) -> int:
        return self.player.ers_mode

    @property
    def drs_allowed(self) -> int:
        return self.player.drs_allowed

    @property
    def compound_name(self) -> str:
        return self.player.compound_name

    @property
    def compound_c_index(self) -> str | None:
        return self.player.compound_c_index

    @property
    def setup(self) -> dict:
        return self.player.setup

    @property
    def tyre_sets(self) -> list:
        return self.player.tyre_sets

    @property
    def session_laps(self) -> list:
        return self.player.session_laps

    @property
    def tyre_stints(self) -> list:
        return self.player.tyre_stints

    @property
    def track_name(self) -> str:
        return TRACKS.get(self.track_id, "unknown track")

    @property
    def driver_name(self) -> str:
        return self.player.name

    @property
    def connected(self) -> bool:
        return (time.time() - self.last_packet_at) < 3.0 and self.packets_seen > 0

    # ------------------------------------------------------------------
    def laps_remaining(self) -> int | None:
        if self.total_laps <= 0 or self.lap <= 0:
            return None
        return max(0, self.total_laps - self.lap + 1)

    def fuel_to_end_kg(self) -> float | None:
        remaining = self.laps_remaining()
        if remaining is None or not self.fuel_per_lap_kg:
            return None
        return self.fuel_per_lap_kg * remaining

    def fuel_surplus_laps(self) -> float | None:
        if not self.fuel_per_lap_kg:
            return None
        return self.fuel_kg / self.fuel_per_lap_kg - (self.laps_remaining() or 0)

    def predicted_tyre_life(self) -> float | None:
        return self.player.predicted_tyre_life

    def grid(self) -> list[dict[str, Any]]:
        rows = [car.to_dict() for car in self.cars if car.position > 0]
        return sorted(rows, key=lambda row: row["pos"])

    def gap_trend_s(self, window_s: float = 5.0) -> float | None:
        """Positive = the gap ahead is opening, negative = closing."""
        if self.gap_ahead_s is None or not self._gap_history:
            return None
        cutoff = time.time() - window_s
        old = None
        for ts, gap in self._gap_history:
            if ts >= cutoff and gap is not None:
                old = gap
                break
        if old is None:
            return None
        return round(self.gap_ahead_s - old, 2)

    def pace_summary(self) -> dict[str, Any]:
        laps = [lap for lap in self.player.session_laps if lap.get("valid")]
        if not laps:
            return {}
        best_lap = min(lap["time_s"] for lap in laps)
        last = laps[-1]
        best_sectors = {
            "s1": min(lap["s1_s"] for lap in laps),
            "s2": min(lap["s2_s"] for lap in laps),
            "s3": min(lap["s3_s"] for lap in laps),
        }
        sectors_last = {"s1": last["s1_s"], "s2": last["s2_s"], "s3": last["s3_s"]}
        sector_deltas = {
            key: round(sectors_last[key] - best_sectors[key], 3) for key in best_sectors
        }
        recent = laps[-3:]
        rolling = sum(lap["time_s"] for lap in recent) / len(recent)
        trend = None
        if len(recent) >= 2:
            trend = round(recent[-1]["time_s"] - recent[0]["time_s"], 3)
        return {
            "best_lap_s": round(best_lap, 3),
            "last_lap_s": round(last["time_s"], 3),
            "delta_to_best_s": round(last["time_s"] - best_lap, 3),
            "best_sectors_s": {k: round(v, 3) for k, v in best_sectors.items()},
            "last_sectors_s": {k: round(v, 3) for k, v in sectors_last.items()},
            "sector_deltas_s": sector_deltas,
            "rolling_pace_3_s": round(rolling, 3),
            "pace_trend_s": trend,
            "valid_laps": len(laps),
        }

    def pit_projection(
        self, pit_loss_s: float | None = None, traffic_window_s: float | None = None
    ) -> dict[str, Any]:
        me = self.player
        if not me.position:
            return {}
        loss = self.pit_loss_s if pit_loss_s is None else pit_loss_s
        window = self.traffic_window_s if traffic_window_s is None else traffic_window_s
        base = me.delta_leader_ms / 1000.0
        projected = base + loss
        rejoin = 1
        traffic = []
        for car in self.cars:
            if car.index == me.index or not car.position:
                continue
            gap = car.delta_leader_ms / 1000.0
            if gap < projected:
                rejoin += 1
            if abs(gap - projected) <= window:
                traffic.append(car.name)
        ahead = self.rival(me.position - 1)
        behind = self.rival(me.position + 1)
        undercut_gap = None
        if behind is not None and self.gap_behind_s is not None:
            undercut_gap = round(loss - self.gap_behind_s, 1)
        return {
            "pit_loss_s": loss,
            "projected_rejoin_position": rejoin,
            "projected_gap_to_leader_s": round(projected, 1),
            "gap_to_car_ahead_s": self.gap_ahead_s,
            "gap_to_car_behind_s": self.gap_behind_s,
            "traffic_on_exit": traffic,
            "undercut_margin_s": undercut_gap,
            "car_ahead": ahead.name if ahead else None,
            "car_behind": behind.name if behind else None,
        }

    def systems(self) -> dict[str, Any]:
        me = self.player
        surface = me.tyre_surface_c
        inner = me.tyre_inner_c
        carcass_delta = None
        if surface and inner:
            carcass_delta = round(
                sum(inner) / len(inner) - sum(surface) / len(surface), 1
            )
        return {
            "ers_pct": round(100.0 * me.ers_joules / 4_000_000.0, 0),
            "ers_mode": ERS_MODES.get(me.ers_mode, "unknown"),
            "ers_harvested_mj": round(
                (me.ers_harvested_mguk_j + me.ers_harvested_mguh_j) / 1_000_000.0, 2
            ),
            "ers_deployed_mj": round(me.ers_deployed_j / 1_000_000.0, 2),
            "fuel_mix": FUEL_MIXES.get(me.fuel_mix, "unknown"),
            "brake_bias_pct": me.brake_bias,
            "engine_temp_c": me.engine_temp_c,
            "brake_temps_c": _corner_dict(me.brake_temps_c),
            "drs_allowed": bool(me.drs_allowed),
            "drs_activation_distance_m": me.drs_activation_distance_m,
            "tyre_carcass_delta_c": carcass_delta,
        }

    def rival(self, reference: str | int) -> CarState | None:
        if isinstance(reference, int) or str(reference).isdigit():
            pos = int(reference)
            for car in self.cars:
                if car.position == pos and car.index != self.player_index:
                    return car
            return None
        text = str(reference).lower()
        for car in self.cars:
            if car.index != self.player_index and text in car.name.lower():
                return car
        return None

    def recent_events(self, seconds: float = 15.0) -> list[str]:
        cutoff = time.time() - seconds
        return [label for ts, label in self.events if ts >= cutoff]

    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            me = self.player
            last5 = list(self.lap_history)[-5:]
            return {
                "connected": self.connected,
                "track": self.track_name,
                "session": SESSION_TYPES.get(self.session_type, "unknown"),
                "weather": WEATHER.get(self.weather, "unknown"),
                "air_temp_c": self.air_temp_c,
                "track_temp_c": self.track_temp_c,
                "safety_car": SAFETY_CAR.get(self.safety_car, "none"),
                "flag": FIA_FLAGS.get(me.fia_flag, "unknown"),
                "lap": me.lap,
                "total_laps": self.total_laps,
                "laps_remaining": self.laps_remaining(),
                "position": me.position,
                "grid_position": me.grid_position,
                "last_lap_s": round(me.last_lap_ms / 1000.0, 3) if me.last_lap_ms else None,
                "current_lap_s": round(me.current_lap_ms / 1000.0, 3),
                "lap_invalid": me.lap_invalid,
                "sector": me.sector + 1,
                "gap_ahead_s": self.gap_ahead_s,
                "gap_behind_s": self.gap_behind_s,
                "gap_to_leader_s": round(me.delta_leader_ms / 1000.0, 1)
                if me.delta_leader_ms else None,
                "driver_name": me.name,
                "pit_status": PIT_STATUS.get(me.pit_status, "on track"),
                "pit_stops": me.pit_stops,
                "pit_window_ideal_lap": self.pit_window_ideal,
                "pit_window_latest_lap": self.pit_window_latest,
                "pit_rejoin_position": self.pit_rejoin_position,
                "penalties_s": me.penalties_s,
                "speed_kph": me.speed_kph,
                "gear": me.gear,
                "rpm": me.rpm,
                "drs": bool(me.drs),
                "ers_pct": round(100.0 * me.ers_joules / 4_000_000.0, 0),
                "ers_deploy_mode": me.ers_mode,
                "fuel_mix": me.fuel_mix,
                "fuel_kg": round(me.fuel_kg, 1),
                "fuel_laps_remaining": round(me.fuel_laps_remaining, 1),
                "fuel_per_lap_kg": round(self.fuel_per_lap_kg, 2)
                if self.fuel_per_lap_kg else None,
                "fuel_to_end_kg": round(self.fuel_to_end_kg(), 2)
                if self.fuel_to_end_kg() is not None else None,
                "fuel_surplus_laps": round(self.fuel_surplus_laps(), 2)
                if self.fuel_surplus_laps() is not None else None,
                "tyre": {
                    "compound": me.compound_name,
                    "actual_code": me.compound_code,
                    "visual_code": me.visual_compound_code,
                    "age_laps": me.tyre_age_laps,
                    "wear_pct": _corner_dict(me.tyre_wear),
                    "damage_pct": _corner_dict(me.tyre_damage),
                    "wear_rate_per_lap": round(me.wear_rate_per_lap, 2)
                    if me.wear_rate_per_lap else None,
                    "predicted_life_laps": round(me.predicted_tyre_life, 1)
                    if me.predicted_tyre_life is not None else None,
                    "surface_c": _corner_dict(me.tyre_surface_c),
                    "inner_c": _corner_dict(me.tyre_inner_c),
                    "pressure_psi": _corner_dict(me.tyre_pressure_psi),
                },
                "brake_temps_c": _corner_dict(me.brake_temps_c),
                "damage": {
                    "front_wing": me.wing_damage,
                    "floor": me.floor_damage,
                    "diffuser": me.diffuser_damage,
                    "sidepod": me.sidepod_damage,
                    "gearbox": me.gearbox_damage,
                    "engine": me.engine_damage,
                    "engine_wear": me.engine_wear,
                    "drs_fault": me.drs_fault,
                    "ers_fault": me.ers_fault,
                },
                "rain_forecast": [
                    f"+{s['minutes']}m {s['weather']} {s['rain_pct']}%" for s in self.forecast[:4]
                ],
                "recent_laps": [
                    {"lap": r.lap_number, "time_s": round(r.seconds, 3), "tyre": r.compound}
                    for r in last5
                ],
                "best_lap_s": round(me.best_lap_ms / 1000.0, 3) if me.best_lap_ms else None,
                "setup": me.setup,
                "tyre_sets": me.tyre_sets,
                "session_laps": me.session_laps[-10:],
                "tyre_stints": me.tyre_stints,
                "grid": self.grid(),
                "final_classification": self.final_classification,
                "motion": self.motion,
                "pace": self.pace_summary(),
                "gap_trend_s": self.gap_trend_s(),
                "systems": self.systems(),
                "strategy": self.pit_projection(),
                "recent_events": self.recent_events(),
            }
