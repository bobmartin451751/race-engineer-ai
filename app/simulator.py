"""Synthetic F1 24 telemetry, so the engineer can be tested without the game.

Usage:
    python -m app.simulator --duration 120

Then run the engineer as usual; it will see a car lapping Monza.
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
    names = ["You", "Verstappen", "Hamilton", "Leclerc", "Norris"] + [f"Car {i}" for i in range(5, 22)]
    for i, name in enumerate(names):
        part = pkt.participants[i]
        part.ai_controlled = 1
        part.team_id = i % 10
        part.race_number = i + 1
        part.name = name.encode("utf-8")[:47]
    pkt.participants[0].ai_controlled = 0
    return bytes(pkt)


def _lap_packet(frame: int, now: float, lap: int, lap_progress: float,
                position: int = 4, fuel_wear: float = 0.0) -> bytes:
    pkt = p.PacketLapData()
    pkt.header = _header(p.LAP_DATA, frame, now)
    for i in range(p.MAX_CARS):
        car = pkt.lap_data[i]
        car.car_position = i + 1
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
        car.delta_to_race_leader_ms_part = 4000 + i * 900
        car.pit_status = 0
        car.sector = min(2, int(lap_progress * 3))
    me = pkt.lap_data[0]
    me.car_position = position
    me.delta_to_car_in_front_ms_part = 650
    me.delta_to_race_leader_ms_part = 12000
    return bytes(pkt)


def _telemetry_packet(frame: int, now: float, lap_progress: float) -> bytes:
    pkt = p.PacketCarTelemetryData()
    pkt.header = _header(p.CAR_TELEMETRY, frame, now)
    for i in range(p.MAX_CARS):
        car = pkt.car_telemetry_data[i]
        speed = 280 + 40 * math.sin(lap_progress * 6.28 * 3)
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
                   compound: int, age: int) -> bytes:
    pkt = p.PacketCarStatusData()
    pkt.header = _header(p.CAR_STATUS, frame, now)
    for i in range(p.MAX_CARS):
        s = pkt.car_status_data[i]
        s.fuel_in_tank = 110.0 if i else fuel
        s.fuel_capacity = 110.0
        s.fuel_remaining_laps = fuel / 2.6
        s.fuel_mix = 1
        s.max_rpm = 15000
        s.idle_rpm = 4000
        s.max_gears = 8
        s.drs_allowed = 1
        s.actual_tyre_compound = compound
        s.visual_tyre_compound = 17
        s.tyres_age_laps = age
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
    d = pkt.car_damage_data[0]
    d.front_left_wing_damage = 5
    d.floor_damage = 3
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

            packets = [
                _lap_packet(frame, elapsed, lap, progress, position=4),
                _telemetry_packet(frame, elapsed, progress),
                _status_packet(frame, elapsed, fuel, wear, compound, age),
                _damage_packet(frame, elapsed, wear),
            ]
            if frame % int(hz) == 0:
                packets.append(_session_packet(frame, elapsed))
                packets.append(_participants(frame, elapsed))
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
