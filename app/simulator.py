"""Synthetic F1 24 telemetry, so the engineer can be tested without the game.

Emits every packet type in the F1 24 spec (2024 format), including all 22 cars,
so the full-race data path can be exercised offline.

    python -m app.simulator --duration 120
"""

from __future__ import annotations

import argparse
import math
import socket
import time

from .telemetry import packets as p

SESSION_UID = 0x5A1B2C3D
TRACK_ID = 10  # Monza
TOTAL_LAPS = 12
LAP_SECONDS = 18.0

DRIVERS = [
    "You", "Verstappen", "Hamilton", "Leclerc", "Norris", "Piastri",
    "Russell", "Sainz", "Alonso", "Stroll", "Gasly", "Ocon", "Tsunoda",
    "Ricciardo", "Hulkenberg", "Magnussen", "Bottas", "Zhou", "Albon",
    "Sargeant", "De Vries", "Drugovich",
]


def _header(packet_id: int, frame: int, session_time: float) -> p.PacketHeader:
    h = p.PacketHeader()
    h.packet_format = 2024
    h.game_year = 24
    h.game_major_version = 1
    h.game_minor_version = 0
    h.packet_version = 1
    h.packet_id = packet_id
    h.session_uid = SESSION_UID
    h.session_time = session_time
    h.frame_identifier = frame
    h.overall_frame_identifier = frame
    h.player_car_index = 0
    h.secondary_player_car_index = 255
    return h


def _session_packet(frame: int, now: float, weather: int = 1) -> bytes:
    pkt = p.PacketSessionData()
    pkt.header = _header(p.SESSION, frame, now)
    d = pkt.data
    d.weather = weather
    d.track_temperature = 31
    d.air_temperature = 24
    d.total_laps = TOTAL_LAPS
    d.track_length = 5793
    d.session_type = 10
    d.track_id = TRACK_ID
    d.formula = 0
    d.session_time_left = 1800
    d.session_duration = 1800
    d.pit_speed_limit = 80
    d.safety_car_status = 0
    d.network_game = 0
    d.num_weather_forecast_samples = 4
    samples = [(0, 1, 10), (10, 1, 20), (20, 3, 65), (30, 3, 70)]
    for i, (mins, wx, rain) in enumerate(samples):
        s = d.weather_forecast_samples[i]
        s.session_type = 10
        s.time_offset = mins
        s.weather = wx
        s.track_temperature = 30
        s.air_temperature = 24
        s.rain_percentage = rain
    d.pit_stop_window_ideal_lap = 5
    d.pit_stop_window_latest_lap = 7
    d.pit_stop_rejoin_position = 4
    return bytes(pkt)


def _participants(frame: int, now: float) -> bytes:
    pkt = p.PacketParticipantsData()
    pkt.header = _header(p.PARTICIPANTS, frame, now)
    pkt.num_active_cars = 22
    for i, name in enumerate(DRIVERS):
        part = pkt.participants[i]
        part.ai_controlled = 0 if i == 0 else 1
        part.team_id = i % 10
        part.race_number = i + 1
        part.name = name.encode("utf-8")[:47]
    return bytes(pkt)


def _lap_packet(frame: int, now: float, lap: int, lap_progress: float,
                pit_lap: int | None = None) -> bytes:
    pkt = p.PacketLapData()
    pkt.header = _header(p.LAP_DATA, frame, now)
    positions = list(range(1, p.MAX_CARS + 1))
    # put the player in P4 so the engineer has cars on both sides
    positions[0], positions[3] = positions[3], positions[0]
    for i in range(p.MAX_CARS):
        car = pkt.lap_data[i]
        car.car_position = positions[i]
        car.current_lap_num = lap
        car.driver_status = 4
        car.result_status = 2
        car.grid_position = i + 1
        car.current_lap_time_in_ms = int(lap_progress * LAP_SECONDS * 1000)
        car.last_lap_time_in_ms = int((82.4 + (i % 5) * 0.15) * 1000)
        car.lap_distance = lap_progress * 5793.0
        car.total_distance = (lap - 1) * 5793.0 + car.lap_distance
        car.delta_to_car_in_front_ms_part = 850 + i * 20
        car.delta_to_race_leader_minutes_part = 0
        car.delta_to_race_leader_ms_part = (positions[i] - 1) * 900
        car.pit_status = 0
        car.sector = min(2, int(lap_progress * 3))
        if i == 1 and pit_lap is not None and lap >= pit_lap and lap_progress < 0.08:
            car.pit_status = 2
            car.driver_status = 2
    # the car directly behind the player reports its gap to us
    pkt.lap_data[4].delta_to_car_in_front_ms_part = 930
    return bytes(pkt)


def _telemetry_packet(frame: int, now: float, lap_progress: float) -> bytes:
    pkt = p.PacketCarTelemetryData()
    pkt.header = _header(p.CAR_TELEMETRY, frame, now)
    for i in range(p.MAX_CARS):
        car = pkt.car_telemetry_data[i]
        speed = 280 + 40 * math.sin(lap_progress * 6.28 * 3 + i)
        car.speed = int(max(60, speed))
        car.throttle = 1.0 if lap_progress % 0.25 < 0.18 else 0.0
        car.brake = 0.0 if car.throttle else 0.8
        car.gear = 7 if speed > 200 else 3
        car.engine_rpm = 11000 + int(1500 * math.sin(lap_progress * 20))
        car.drs = 1 if 0.4 < lap_progress < 0.6 else 0
        car.brakes_temperature[0] = 610
        car.brakes_temperature[1] = 600
        car.brakes_temperature[2] = 480
        car.brakes_temperature[3] = 470
        for j, temp in enumerate((92, 96, 88, 91)):
            car.tyres_surface_temperature[j] = temp + int(6 * math.sin(lap_progress * 8))
            car.tyres_inner_temperature[j] = temp + 8
        car.engine_temperature = 105
        car.tyres_pressure[0] = 22.4
        car.tyres_pressure[1] = 22.6
        car.tyres_pressure[2] = 21.8
        car.tyres_pressure[3] = 21.9
        car.surface_type[0] = 1
    return bytes(pkt)


def _status_packet(frame: int, now: float, fuel: float, wear: float,
                   compound: int, age: int, pit_lap: int | None, lap: int) -> bytes:
    pkt = p.PacketCarStatusData()
    pkt.header = _header(p.CAR_STATUS, frame, now)
    for i in range(p.MAX_CARS):
        s = pkt.car_status_data[i]
        # rivals carry slightly different fuel and tyres
        s.fuel_in_tank = 110.0 if i else fuel
        s.fuel_capacity = 110.0
        s.fuel_remaining_laps = (fuel if i == 0 else 110.0) / 2.6
        s.fuel_mix = 1
        s.max_rpm = 15000
        s.idle_rpm = 4000
        s.max_gears = 8
        s.drs_allowed = 1
        s.actual_tyre_compound = compound if i == 0 else (17 if i % 3 else 18)
        s.visual_tyre_compound = 17 if i == 0 else (17 if i % 3 else 18)
        s.tyres_age_laps = age if i == 0 else (lap + i) % 15
        if i == 1 and pit_lap is not None and lap > pit_lap:
            s.actual_tyre_compound = 18
            s.tyres_age_laps = lap - pit_lap
        s.vehicle_fia_flags = 1
        s.ers_store_energy = 3_200_000
        s.ers_deploy_mode = 1
    return bytes(pkt)


def _damage_packet(frame: int, now: float, wear: float) -> bytes:
    pkt = p.PacketCarDamageData()
    pkt.header = _header(p.CAR_DAMAGE, frame, now)
    for i in range(p.MAX_CARS):
        d = pkt.car_damage_data[i]
        for j in range(4):
            d.tyres_wear[j] = wear
            d.tyres_damage[j] = 0
            d.brakes_damage[j] = 2
        d.front_left_wing_damage = 5
        d.front_right_wing_damage = 6
        d.floor_damage = 3
        d.diffuser_damage = 1
        d.sidepod_damage = 0
        d.gearbox_damage = 4
        d.engine_damage = 2
        d.engine_mguh_wear = 3
        d.engine_es_wear = 4
        d.engine_ce_wear = 5
        d.engine_ice_wear = 6
        d.engine_mguk_wear = 2
        d.engine_tc_wear = 3
    return bytes(pkt)


def _setup_packet(frame: int, now: float) -> bytes:
    pkt = p.PacketCarSetupData()
    pkt.header = _header(p.CAR_SETUPS, frame, now)
    for i in range(p.MAX_CARS):
        s = pkt.car_setups[i]
        s.front_wing = 32
        s.rear_wing = 24
        s.on_throttle = 55
        s.off_throttle = 60
        s.front_camber = -3.2
        s.rear_camber = -1.7
        s.front_toe = 0.06
        s.rear_toe = 0.18
        s.front_suspension = 5
        s.rear_suspension = 6
        s.front_anti_roll_bar = 7
        s.rear_anti_roll_bar = 4
        s.front_suspension_height = 3
        s.rear_suspension_height = 4
        s.brake_pressure = 100
        s.brake_bias = 56
        s.engine_braking = 50
        s.rear_left_tyre_pressure = 22.4
        s.rear_right_tyre_pressure = 22.6
        s.front_left_tyre_pressure = 21.8
        s.front_right_tyre_pressure = 21.9
        s.ballast = 0
        s.fuel_load = 78.0
    pkt.next_front_wing_value = 33.0
    return bytes(pkt)


def _session_history_packet(frame: int, now: float, car_idx: int, lap: int) -> bytes:
    pkt = p.PacketSessionHistoryData()
    pkt.header = _header(p.SESSION_HISTORY, frame, now)
    pkt.car_idx = car_idx
    completed = max(0, lap - 1)
    pkt.num_laps = min(100, completed + 1)
    pkt.num_tyre_stints = 2 if completed >= 5 else 1
    pkt.best_lap_time_lap_num = 1 if completed else 0
    pkt.best_sector1_lap_num = 1 if completed else 0
    pkt.best_sector2_lap_num = 1 if completed else 0
    pkt.best_sector3_lap_num = 1 if completed else 0
    for i in range(min(completed, 100)):
        h = pkt.lap_history_data[i]
        h.lap_time_in_ms = 82400 + (i % 3) * 120
        h.sector1_time_ms_part = 27100
        h.sector1_time_minutes_part = 0
        h.sector2_time_ms_part = 28200
        h.sector2_time_minutes_part = 0
        h.sector3_time_ms_part = 27100
        h.sector3_time_minutes_part = 0
        h.lap_valid_bit_flags = 0x0F
    pkt.tyre_stints_history_data[0].end_lap = 5
    pkt.tyre_stints_history_data[0].tyre_actual_compound = 17
    pkt.tyre_stints_history_data[0].tyre_visual_compound = 17
    if pkt.num_tyre_stints > 1:
        pkt.tyre_stints_history_data[1].end_lap = 255
        pkt.tyre_stints_history_data[1].tyre_actual_compound = 18
        pkt.tyre_stints_history_data[1].tyre_visual_compound = 18
    return bytes(pkt)


def _tyre_sets_packet(frame: int, now: float, car_idx: int) -> bytes:
    pkt = p.PacketTyreSetsData()
    pkt.header = _header(p.TYRE_SETS, frame, now)
    pkt.car_idx = car_idx
    for i in range(20):
        s = pkt.tyre_set_data[i]
        s.actual_tyre_compound = (17, 18, 16)[i % 3]
        s.visual_tyre_compound = (17, 18, 16)[i % 3]
        s.wear = 0 if i > 3 else 8
        s.available = 1 if i > 3 else 0
        s.life_span = 18 if i > 3 else 2
        s.usable_life = 20
        s.lap_delta_time = (i - 3) * 40
        s.fitted = 1 if i == 0 else 0
    pkt.fitted_idx = 0
    return bytes(pkt)


def _motion_packet(frame: int, now: float, lap_progress: float) -> bytes:
    pkt = p.PacketMotionData()
    pkt.header = _header(p.MOTION, frame, now)
    for i in range(p.MAX_CARS):
        m = pkt.car_motion_data[i]
        m.world_position_x = float(i * 10)
        m.world_position_y = 0.0
        m.world_position_z = lap_progress * 5793.0
        m.world_velocity_x = 0.0
        m.world_velocity_y = 0.0
        m.world_velocity_z = 80.0
        m.g_force_lateral = 2.1 * math.sin(lap_progress * 12)
        m.g_force_longitudinal = 1.4 * math.cos(lap_progress * 9)
        m.g_force_vertical = 0.2
        m.yaw = 0.1
        m.pitch = 0.0
        m.roll = 0.02
    return bytes(pkt)


def _motion_ex_packet(frame: int, now: float, lap_progress: float) -> bytes:
    pkt = p.PacketMotionExData()
    pkt.header = _header(p.MOTION_EX, frame, now)
    d = pkt.data
    for i in range(4):
        d.suspension_position[i] = 0.02 + 0.001 * i
        d.suspension_velocity[i] = 0.1 * math.sin(lap_progress * 10 + i)
        d.suspension_acceleration[i] = 0.5
        d.wheel_speed[i] = 80.0
        d.wheel_slip_ratio[i] = 0.05
        d.wheel_slip_angle[i] = 0.02
        d.wheel_lat_force[i] = 800.0
        d.wheel_long_force[i] = 400.0
        d.wheel_vert_force[i] = 3200.0
    d.height_of_cog_above_ground = 0.28
    d.local_velocity_x = 0.4
    d.local_velocity_y = 0.0
    d.local_velocity_z = 80.0
    d.angular_velocity_x = 0.01
    d.angular_velocity_y = 0.0
    d.angular_velocity_z = 0.0
    d.angular_acceleration_x = 0.02
    d.angular_acceleration_y = 0.0
    d.angular_acceleration_z = 0.0
    d.front_wheels_angle = 0.05
    d.front_aero_height = 0.075
    d.rear_aero_height = 0.12
    d.front_roll_angle = 0.01
    d.rear_roll_angle = 0.008
    d.chassis_yaw = 0.002
    return bytes(pkt)


def _final_classification_packet(frame: int, now: float) -> bytes:
    pkt = p.PacketFinalClassificationData()
    pkt.header = _header(p.FINAL_CLASSIFICATION, frame, now)
    pkt.num_cars = 22
    for i in range(p.MAX_CARS):
        d = pkt.classification_data[i]
        d.position = i + 1
        d.num_laps = TOTAL_LAPS
        d.grid_position = i + 1
        d.points = max(0, 25 - i * 2)
        d.num_pit_stops = 1
        d.result_status = 3
        d.best_lap_time_in_ms = 82100 + i * 150
        d.total_race_time = 5000.0 + i * 3.2
        d.penalties_time = 0
        d.num_penalties = 0
        d.num_tyre_stints = 2
        d.tyre_stints_actual[0] = 17
        d.tyre_stints_actual[1] = 18
        d.tyre_stints_visual[0] = 17
        d.tyre_stints_visual[1] = 18
        d.tyre_stints_end_laps[0] = 6
        d.tyre_stints_end_laps[1] = 255
    return bytes(pkt)


def _lobby_packet(frame: int, now: float) -> bytes:
    pkt = p.PacketLobbyInfoData()
    pkt.header = _header(p.LOBBY_INFO, frame, now)
    pkt.num_players = 22
    for i in range(p.MAX_CARS):
        d = pkt.lobby_players[i]
        d.ai_controlled = 0 if i == 0 else 1
        d.team_id = i % 10
        d.nationality = 1
        d.platform = 1
        d.name = DRIVERS[i].encode("utf-8")[:47]
        d.car_number = i + 1
        d.ready_status = 1
    return bytes(pkt)


def _event_packet(frame: int, now: float, code: str) -> bytes:
    pkt = p.PacketEventData()
    pkt.header = _header(p.EVENT, frame, now)
    pkt.event_string_code = code.encode("ascii")
    return bytes(pkt)


def run(host: str, port: int, duration: float | None, hz: float) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start = time.time()
    frame = 0
    fuel = 78.0
    wear = 8.0
    compound = 17
    age = 0
    last_lap = 1
    pit_lap = 4

    print(f"simulating F1 24 telemetry to {host}:{port} at {hz:.0f} Hz (Ctrl+C to stop)")
    try:
        while duration is None or time.time() - start < duration:
            elapsed = time.time() - start
            lap = int(elapsed // LAP_SECONDS) + 1
            if lap > TOTAL_LAPS:
                break
            progress = (elapsed % LAP_SECONDS) / LAP_SECONDS
            if lap != last_lap:
                fuel = max(2.0, fuel - 2.6)
                wear = min(100.0, wear + 3.0)
                age += 1
                last_lap = lap
                print(f"  lap {lap}/{TOTAL_LAPS}", flush=True)

            packets = [
                _lap_packet(frame, elapsed, lap, progress, pit_lap),
                _telemetry_packet(frame, elapsed, progress),
                _status_packet(frame, elapsed, fuel, wear, compound, age, pit_lap, lap),
                _damage_packet(frame, elapsed, wear),
                _motion_packet(frame, elapsed, progress),
                _motion_ex_packet(frame, elapsed, progress),
            ]
            if frame % int(hz) == 0:
                packets += [
                    _session_packet(frame, elapsed),
                    _participants(frame, elapsed),
                    _setup_packet(frame, elapsed),
                ]
            if frame % (int(hz) * 2) == 0:
                packets.append(_lobby_packet(frame, elapsed))
            if frame % (int(hz) * 5) == 0:
                packets.append(_final_classification_packet(frame, elapsed))
            # Session history and tyre sets cycle through cars, like the game does.
            packets.append(_session_history_packet(frame, elapsed, frame % p.MAX_CARS, lap))
            packets.append(_tyre_sets_packet(frame, elapsed, frame % p.MAX_CARS))
            if frame == int(hz) * 3:
                packets.append(_event_packet(frame, elapsed, "OVTK"))

            for data in packets:
                sock.sendto(data, (host, port))
            frame += 1
            time.sleep(1.0 / hz)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        print("simulator stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="F1 24 telemetry simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=20777)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--hz", type=float, default=20)
    args = parser.parse_args()
    run(args.host, args.port, args.duration, args.hz)


if __name__ == "__main__":
    main()
