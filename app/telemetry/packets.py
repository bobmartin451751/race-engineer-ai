"""Binary layouts for the EA SPORTS F1 24 UDP telemetry format (2024).

Every structure is little-endian and packed, matching the wire format.
Layouts follow the official F1 24 UDP specification; cross-checked against
the community reference implementation by Xavier Dubuc (MIT licensed).

Only the packets the race engineer needs are decoded. Unknown packets are
ignored by the listener.
"""

from __future__ import annotations

import ctypes as C

MAX_CARS = 22
MAX_MARSHAL_ZONES = 21
MAX_WEATHER_SAMPLES = 64
MAX_TYRE_SETS = 20
HEADER_SIZE = 29

# Packet ids used by F1 24
MOTION = 0
SESSION = 1
LAP_DATA = 2
EVENT = 3
PARTICIPANTS = 4
CAR_SETUPS = 5
CAR_TELEMETRY = 6
CAR_STATUS = 7
FINAL_CLASSIFICATION = 8
LOBBY_INFO = 9
CAR_DAMAGE = 10
SESSION_HISTORY = 11
TYRE_SETS = 12
MOTION_EX = 13
TIME_TRIAL = 14

PACKET_NAMES = {
    MOTION: "motion",
    SESSION: "session",
    LAP_DATA: "lap_data",
    EVENT: "event",
    PARTICIPANTS: "participants",
    CAR_SETUPS: "car_setups",
    CAR_TELEMETRY: "car_telemetry",
    CAR_STATUS: "car_status",
    FINAL_CLASSIFICATION: "final_classification",
    LOBBY_INFO: "lobby_info",
    CAR_DAMAGE: "car_damage",
    SESSION_HISTORY: "session_history",
    TYRE_SETS: "tyre_sets",
    MOTION_EX: "motion_ex",
    TIME_TRIAL: "time_trial",
}


class _Struct(C.LittleEndianStructure):
    _pack_ = 1


class PacketHeader(_Struct):
    _fields_ = [
        ("packet_format", C.c_uint16),
        ("game_year", C.c_uint8),
        ("game_major_version", C.c_uint8),
        ("game_minor_version", C.c_uint8),
        ("packet_version", C.c_uint8),
        ("packet_id", C.c_uint8),
        ("session_uid", C.c_uint64),
        ("session_time", C.c_float),
        ("frame_identifier", C.c_uint32),
        ("overall_frame_identifier", C.c_uint32),
        ("player_car_index", C.c_uint8),
        ("secondary_player_car_index", C.c_uint8),
    ]


class MarshalZone(_Struct):
    _fields_ = [
        ("zone_start", C.c_float),
        ("zone_flag", C.c_int8),
    ]


class WeatherForecastSample(_Struct):
    _fields_ = [
        ("session_type", C.c_uint8),
        ("time_offset", C.c_uint8),
        ("weather", C.c_uint8),
        ("track_temperature", C.c_int8),
        ("track_temperature_change", C.c_int8),
        ("air_temperature", C.c_int8),
        ("air_temperature_change", C.c_int8),
        ("rain_percentage", C.c_uint8),
    ]


class SessionData(_Struct):
    _fields_ = [
        ("weather", C.c_uint8),
        ("track_temperature", C.c_int8),
        ("air_temperature", C.c_int8),
        ("total_laps", C.c_uint8),
        ("track_length", C.c_uint16),
        ("session_type", C.c_uint8),
        ("track_id", C.c_int8),
        ("formula", C.c_uint8),
        ("session_time_left", C.c_uint16),
        ("session_duration", C.c_uint16),
        ("pit_speed_limit", C.c_uint8),
        ("game_paused", C.c_uint8),
        ("is_spectating", C.c_uint8),
        ("spectator_car_index", C.c_uint8),
        ("sli_pro_native_support", C.c_uint8),
        ("num_marshal_zones", C.c_uint8),
        ("marshal_zones", MarshalZone * MAX_MARSHAL_ZONES),
        ("safety_car_status", C.c_uint8),
        ("network_game", C.c_uint8),
        ("num_weather_forecast_samples", C.c_uint8),
        ("weather_forecast_samples", WeatherForecastSample * MAX_WEATHER_SAMPLES),
        ("forecast_accuracy", C.c_uint8),
        ("ai_difficulty", C.c_uint8),
        ("season_link_identifier", C.c_uint32),
        ("weekend_link_identifier", C.c_uint32),
        ("session_link_identifier", C.c_uint32),
        ("pit_stop_window_ideal_lap", C.c_uint8),
        ("pit_stop_window_latest_lap", C.c_uint8),
        ("pit_stop_rejoin_position", C.c_uint8),
        ("steering_assist", C.c_uint8),
        ("braking_assist", C.c_uint8),
        ("gearbox_assist", C.c_uint8),
        ("pit_assist", C.c_uint8),
        ("pit_release_assist", C.c_uint8),
        ("ers_assist", C.c_uint8),
        ("drs_assist", C.c_uint8),
        ("dynamic_racing_line", C.c_uint8),
        ("dynamic_racing_line_type", C.c_uint8),
        ("game_mode", C.c_uint8),
        ("rule_set", C.c_uint8),
        ("time_of_day", C.c_uint32),
        ("session_length", C.c_uint8),
        ("speed_units_lead_player", C.c_uint8),
        ("temperature_units_lead_player", C.c_uint8),
        ("speed_units_secondary_player", C.c_uint8),
        ("temperature_units_secondary_player", C.c_uint8),
        ("num_safety_car_periods", C.c_uint8),
        ("num_virtual_safety_car_periods", C.c_uint8),
        ("num_red_flag_periods", C.c_uint8),
        # -- new in F1 24 --
        ("equal_car_performance", C.c_uint8),
        ("recovery_mode", C.c_uint8),
        ("flashback_limit", C.c_uint8),
        ("surface_type", C.c_uint8),
        ("low_fuel_mode", C.c_uint8),
        ("race_starts", C.c_uint8),
        ("tyre_temperature", C.c_uint8),
        ("pit_lane_tyre_sim", C.c_uint8),
        ("car_damage", C.c_uint8),
        ("car_damage_rate", C.c_uint8),
        ("collisions", C.c_uint8),
        ("collisions_off_for_first_lap_only", C.c_uint8),
        ("mp_unsafe_pit_release", C.c_uint8),
        ("mp_off_for_griefing", C.c_uint8),
        ("corner_cutting_stringency", C.c_uint8),
        ("parc_ferme_rules", C.c_uint8),
        ("pit_stop_experience", C.c_uint8),
        ("safety_car", C.c_uint8),
        ("safety_car_experience", C.c_uint8),
        ("formation_lap", C.c_uint8),
        ("formation_lap_experience", C.c_uint8),
        ("red_flags", C.c_uint8),
        ("affects_licence_level_solo", C.c_uint8),
        ("affects_licence_level_mp", C.c_uint8),
        ("num_sessions_in_weekend", C.c_uint8),
        ("weekend_structure", C.c_uint8 * 12),
        ("sector2_lap_distance_start", C.c_float),
        ("sector3_lap_distance_start", C.c_float),
    ]


class LapData(_Struct):
    _fields_ = [
        ("last_lap_time_in_ms", C.c_uint32),
        ("current_lap_time_in_ms", C.c_uint32),
        ("sector1_time_ms_part", C.c_uint16),
        ("sector1_time_minutes_part", C.c_uint8),
        ("sector2_time_ms_part", C.c_uint16),
        ("sector2_time_minutes_part", C.c_uint8),
        ("delta_to_car_in_front_ms_part", C.c_uint16),
        ("delta_to_car_in_front_minutes_part", C.c_uint8),
        ("delta_to_race_leader_ms_part", C.c_uint16),
        ("delta_to_race_leader_minutes_part", C.c_uint8),
        ("lap_distance", C.c_float),
        ("total_distance", C.c_float),
        ("safety_car_delta", C.c_float),
        ("car_position", C.c_uint8),
        ("current_lap_num", C.c_uint8),
        ("pit_status", C.c_uint8),
        ("num_pit_stops", C.c_uint8),
        ("sector", C.c_uint8),
        ("current_lap_invalid", C.c_uint8),
        ("penalties", C.c_uint8),
        ("total_warnings", C.c_uint8),
        ("corner_cutting_warnings", C.c_uint8),
        ("num_unserved_drive_through_pens", C.c_uint8),
        ("num_unserved_stop_go_pens", C.c_uint8),
        ("grid_position", C.c_uint8),
        ("driver_status", C.c_uint8),
        ("result_status", C.c_uint8),
        ("pit_lane_timer_active", C.c_uint8),
        ("pit_lane_time_in_lane_in_ms", C.c_uint16),
        ("pit_stop_timer_in_ms", C.c_uint16),
        ("pit_stop_should_serve_pen", C.c_uint8),
        ("speed_trap_fastest_speed", C.c_float),
        ("speed_trap_fastest_lap", C.c_uint8),
    ]


class ParticipantData(_Struct):
    _fields_ = [
        ("ai_controlled", C.c_uint8),
        ("driver_id", C.c_uint8),
        ("network_id", C.c_uint8),
        ("team_id", C.c_uint8),
        ("my_team", C.c_uint8),
        ("race_number", C.c_uint8),
        ("nationality", C.c_uint8),
        ("name", C.c_char * 48),
        ("your_telemetry", C.c_uint8),
        ("show_online_names", C.c_uint8),
        ("tech_level", C.c_uint16),
        ("platform", C.c_uint8),
    ]


class CarTelemetryData(_Struct):
    _fields_ = [
        ("speed", C.c_uint16),
        ("throttle", C.c_float),
        ("steer", C.c_float),
        ("brake", C.c_float),
        ("clutch", C.c_uint8),
        ("gear", C.c_int8),
        ("engine_rpm", C.c_uint16),
        ("drs", C.c_uint8),
        ("rev_lights_percent", C.c_uint8),
        ("rev_lights_bit_value", C.c_uint16),
        ("brakes_temperature", C.c_uint16 * 4),
        ("tyres_surface_temperature", C.c_uint8 * 4),
        ("tyres_inner_temperature", C.c_uint8 * 4),
        ("engine_temperature", C.c_uint16),
        ("tyres_pressure", C.c_float * 4),
        ("surface_type", C.c_uint8 * 4),
    ]


class CarStatusData(_Struct):
    _fields_ = [
        ("traction_control", C.c_uint8),
        ("anti_lock_brakes", C.c_uint8),
        ("fuel_mix", C.c_uint8),
        ("front_brake_bias", C.c_uint8),
        ("pit_limiter_status", C.c_uint8),
        ("fuel_in_tank", C.c_float),
        ("fuel_capacity", C.c_float),
        ("fuel_remaining_laps", C.c_float),
        ("max_rpm", C.c_uint16),
        ("idle_rpm", C.c_uint16),
        ("max_gears", C.c_uint8),
        ("drs_allowed", C.c_uint8),
        ("drs_activation_distance", C.c_uint16),
        ("actual_tyre_compound", C.c_uint8),
        ("visual_tyre_compound", C.c_uint8),
        ("tyres_age_laps", C.c_uint8),
        ("vehicle_fia_flags", C.c_int8),
        ("engine_power_ice", C.c_float),
        ("engine_power_mguk", C.c_float),
        ("ers_store_energy", C.c_float),
        ("ers_deploy_mode", C.c_uint8),
        ("ers_harvested_this_lap_mguk", C.c_float),
        ("ers_harvested_this_lap_mguh", C.c_float),
        ("ers_deployed_this_lap", C.c_float),
        ("network_paused", C.c_uint8),
    ]


class CarDamageData(_Struct):
    _fields_ = [
        ("tyres_wear", C.c_float * 4),
        ("tyres_damage", C.c_uint8 * 4),
        ("brakes_damage", C.c_uint8 * 4),
        ("front_left_wing_damage", C.c_uint8),
        ("front_right_wing_damage", C.c_uint8),
        ("rear_wing_damage", C.c_uint8),
        ("floor_damage", C.c_uint8),
        ("diffuser_damage", C.c_uint8),
        ("sidepod_damage", C.c_uint8),
        ("drs_fault", C.c_uint8),
        ("ers_fault", C.c_uint8),
        ("gearbox_damage", C.c_uint8),
        ("engine_damage", C.c_uint8),
        ("engine_mguh_wear", C.c_uint8),
        ("engine_es_wear", C.c_uint8),
        ("engine_ce_wear", C.c_uint8),
        ("engine_ice_wear", C.c_uint8),
        ("engine_mguk_wear", C.c_uint8),
        ("engine_tc_wear", C.c_uint8),
        ("engine_blown", C.c_uint8),
        ("engine_seized", C.c_uint8),
    ]


class TyreSetData(_Struct):
    _fields_ = [
        ("actual_tyre_compound", C.c_uint8),
        ("visual_tyre_compound", C.c_uint8),
        ("wear", C.c_uint8),
        ("available", C.c_uint8),
        ("recommended_session", C.c_uint8),
        ("life_span", C.c_uint8),
        ("usable_life", C.c_uint8),
        ("lap_delta_time", C.c_int16),
        ("fitted", C.c_uint8),
    ]


# --- full packets ---------------------------------------------------------


class CarMotionData(_Struct):
    _fields_ = [
        ("world_position_x", C.c_float),
        ("world_position_y", C.c_float),
        ("world_position_z", C.c_float),
        ("world_velocity_x", C.c_float),
        ("world_velocity_y", C.c_float),
        ("world_velocity_z", C.c_float),
        ("world_forward_dir_x", C.c_int16),
        ("world_forward_dir_y", C.c_int16),
        ("world_forward_dir_z", C.c_int16),
        ("world_right_dir_x", C.c_int16),
        ("world_right_dir_y", C.c_int16),
        ("world_right_dir_z", C.c_int16),
        ("g_force_lateral", C.c_float),
        ("g_force_longitudinal", C.c_float),
        ("g_force_vertical", C.c_float),
        ("yaw", C.c_float),
        ("pitch", C.c_float),
        ("roll", C.c_float),
    ]


class PacketMotionData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_motion_data", CarMotionData * MAX_CARS),
    ]


class PacketSessionData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("data", SessionData),
    ]


class PacketLapData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("lap_data", LapData * MAX_CARS),
        ("time_trial_pb_car_idx", C.c_uint8),
        ("time_trial_rival_car_idx", C.c_uint8),
    ]


class EventDataDetails(C.Union):
    _fields_ = [
        ("vehicle_idx", C.c_uint8),
        ("lap_time", C.c_float),
        ("speed", C.c_float),
        ("num_lights", C.c_uint8),
        ("flashback_frame_identifier", C.c_uint32),
        ("flashback_session_time", C.c_float),
        ("button_status", C.c_uint32),
        ("safety_car_type", C.c_uint8),
        ("event_type", C.c_uint8),
        ("overtaking_vehicle_idx", C.c_uint8),
        ("being_overtaken_vehicle_idx", C.c_uint8),
        ("raw", C.c_uint8 * 12),
    ]


class PacketEventData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("event_string_code", C.c_char * 4),
        ("event_details", EventDataDetails),
    ]


class PacketParticipantsData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("num_active_cars", C.c_uint8),
        ("participants", ParticipantData * MAX_CARS),
    ]


class PacketCarTelemetryData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_telemetry_data", CarTelemetryData * MAX_CARS),
        ("mfd_panel_index", C.c_uint8),
        ("mfd_panel_index_secondary_player", C.c_uint8),
        ("suggested_gear", C.c_int8),
    ]


class PacketCarStatusData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_status_data", CarStatusData * MAX_CARS),
    ]


class PacketCarDamageData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_damage_data", CarDamageData * MAX_CARS),
    ]


class PacketTyreSetsData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_idx", C.c_uint8),
        ("tyre_set_data", TyreSetData * MAX_TYRE_SETS),
        ("fitted_idx", C.c_uint8),
    ]


class CarSetupData(_Struct):
    _fields_ = [
        ("front_wing", C.c_uint8),
        ("rear_wing", C.c_uint8),
        ("on_throttle", C.c_uint8),
        ("off_throttle", C.c_uint8),
        ("front_camber", C.c_float),
        ("rear_camber", C.c_float),
        ("front_toe", C.c_float),
        ("rear_toe", C.c_float),
        ("front_suspension", C.c_uint8),
        ("rear_suspension", C.c_uint8),
        ("front_anti_roll_bar", C.c_uint8),
        ("rear_anti_roll_bar", C.c_uint8),
        ("front_suspension_height", C.c_uint8),
        ("rear_suspension_height", C.c_uint8),
        ("brake_pressure", C.c_uint8),
        ("brake_bias", C.c_uint8),
        ("engine_braking", C.c_uint8),
        ("rear_left_tyre_pressure", C.c_float),
        ("rear_right_tyre_pressure", C.c_float),
        ("front_left_tyre_pressure", C.c_float),
        ("front_right_tyre_pressure", C.c_float),
        ("ballast", C.c_uint8),
        ("fuel_load", C.c_float),
    ]


class PacketCarSetupData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_setups", CarSetupData * MAX_CARS),
        ("next_front_wing_value", C.c_float),
    ]


class FinalClassificationData(_Struct):
    _fields_ = [
        ("position", C.c_uint8),
        ("num_laps", C.c_uint8),
        ("grid_position", C.c_uint8),
        ("points", C.c_uint8),
        ("num_pit_stops", C.c_uint8),
        ("result_status", C.c_uint8),
        ("best_lap_time_in_ms", C.c_uint32),
        ("total_race_time", C.c_double),
        ("penalties_time", C.c_uint8),
        ("num_penalties", C.c_uint8),
        ("num_tyre_stints", C.c_uint8),
        ("tyre_stints_actual", C.c_uint8 * 8),
        ("tyre_stints_visual", C.c_uint8 * 8),
        ("tyre_stints_end_laps", C.c_uint8 * 8),
    ]


class PacketFinalClassificationData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("num_cars", C.c_uint8),
        ("classification_data", FinalClassificationData * MAX_CARS),
    ]


class LobbyInfoData(_Struct):
    _fields_ = [
        ("ai_controlled", C.c_uint8),
        ("team_id", C.c_uint8),
        ("nationality", C.c_uint8),
        ("platform", C.c_uint8),
        ("name", C.c_char * 48),
        ("car_number", C.c_uint8),
        ("your_telemetry", C.c_uint8),
        ("show_online_names", C.c_uint8),
        ("tech_level", C.c_uint16),
        ("ready_status", C.c_uint8),
    ]


class PacketLobbyInfoData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("num_players", C.c_uint8),
        ("lobby_players", LobbyInfoData * MAX_CARS),
    ]


class LapHistoryData(_Struct):
    _fields_ = [
        ("lap_time_in_ms", C.c_uint32),
        ("sector1_time_ms_part", C.c_uint16),
        ("sector1_time_minutes_part", C.c_uint8),
        ("sector2_time_ms_part", C.c_uint16),
        ("sector2_time_minutes_part", C.c_uint8),
        ("sector3_time_ms_part", C.c_uint16),
        ("sector3_time_minutes_part", C.c_uint8),
        ("lap_valid_bit_flags", C.c_uint8),
    ]


class TyreStintHistoryData(_Struct):
    _fields_ = [
        ("end_lap", C.c_uint8),
        ("tyre_actual_compound", C.c_uint8),
        ("tyre_visual_compound", C.c_uint8),
    ]


class PacketSessionHistoryData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("car_idx", C.c_uint8),
        ("num_laps", C.c_uint8),
        ("num_tyre_stints", C.c_uint8),
        ("best_lap_time_lap_num", C.c_uint8),
        ("best_sector1_lap_num", C.c_uint8),
        ("best_sector2_lap_num", C.c_uint8),
        ("best_sector3_lap_num", C.c_uint8),
        ("lap_history_data", LapHistoryData * 100),
        ("tyre_stints_history_data", TyreStintHistoryData * 8),
    ]


class MotionExData(_Struct):
    _fields_ = [
        ("suspension_position", C.c_float * 4),
        ("suspension_velocity", C.c_float * 4),
        ("suspension_acceleration", C.c_float * 4),
        ("wheel_speed", C.c_float * 4),
        ("wheel_slip_ratio", C.c_float * 4),
        ("wheel_slip_angle", C.c_float * 4),
        ("wheel_lat_force", C.c_float * 4),
        ("wheel_long_force", C.c_float * 4),
        ("height_of_cog_above_ground", C.c_float),
        ("local_velocity_x", C.c_float),
        ("local_velocity_y", C.c_float),
        ("local_velocity_z", C.c_float),
        ("angular_velocity_x", C.c_float),
        ("angular_velocity_y", C.c_float),
        ("angular_velocity_z", C.c_float),
        ("angular_acceleration_x", C.c_float),
        ("angular_acceleration_y", C.c_float),
        ("angular_acceleration_z", C.c_float),
        ("front_wheels_angle", C.c_float),
        ("wheel_vert_force", C.c_float * 4),
        ("front_aero_height", C.c_float),
        ("rear_aero_height", C.c_float),
        ("front_roll_angle", C.c_float),
        ("rear_roll_angle", C.c_float),
        ("chassis_yaw", C.c_float),
    ]


class PacketMotionExData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("data", MotionExData),
    ]


class TimeTrialDataSet(_Struct):
    _fields_ = [
        ("car_idx", C.c_uint8),
        ("team_id", C.c_uint8),
        ("lap_time_in_ms", C.c_uint32),
        ("sector1_time_in_ms", C.c_uint32),
        ("sector2_time_in_ms", C.c_uint32),
        ("sector3_time_in_ms", C.c_uint32),
        ("traction_control", C.c_uint8),
        ("gearbox_assist", C.c_uint8),
        ("anti_lock_brakes", C.c_uint8),
        ("equal_car_performance", C.c_uint8),
        ("custom_setup", C.c_uint8),
        ("valid", C.c_uint8),
    ]


class PacketTimeTrialData(_Struct):
    _fields_ = [
        ("header", PacketHeader),
        ("player_session_best", TimeTrialDataSet),
        ("personal_best", TimeTrialDataSet),
        ("rival", TimeTrialDataSet),
    ]


# Expected wire sizes, from the F1 24 specification. Used to detect a
# mismatched UDP format (e.g. the game left on the 2023 format).
EXPECTED_SIZES = {
    MOTION: 1349,
    SESSION: 753,
    LAP_DATA: 1285,
    EVENT: 45,
    PARTICIPANTS: 1350,
    CAR_SETUPS: 1133,
    CAR_TELEMETRY: 1352,
    CAR_STATUS: 1239,
    FINAL_CLASSIFICATION: 1020,
    LOBBY_INFO: 1306,
    CAR_DAMAGE: 953,
    SESSION_HISTORY: 1460,
    TYRE_SETS: 231,
    MOTION_EX: 237,
    TIME_TRIAL: 101,
}

PACKET_CLASSES = {
    MOTION: PacketMotionData,
    SESSION: PacketSessionData,
    LAP_DATA: PacketLapData,
    EVENT: PacketEventData,
    PARTICIPANTS: PacketParticipantsData,
    CAR_SETUPS: PacketCarSetupData,
    CAR_TELEMETRY: PacketCarTelemetryData,
    CAR_STATUS: PacketCarStatusData,
    FINAL_CLASSIFICATION: PacketFinalClassificationData,
    LOBBY_INFO: PacketLobbyInfoData,
    CAR_DAMAGE: PacketCarDamageData,
    SESSION_HISTORY: PacketSessionHistoryData,
    TYRE_SETS: PacketTyreSetsData,
    MOTION_EX: PacketMotionExData,
    TIME_TRIAL: PacketTimeTrialData,
}


def _verify_layout() -> list[str]:
    """Return a list of layout problems (empty when everything matches)."""
    problems = []
    if C.sizeof(PacketHeader) != HEADER_SIZE:
        problems.append(f"header {C.sizeof(PacketHeader)} != {HEADER_SIZE}")
    for pid, expected in EXPECTED_SIZES.items():
        actual = C.sizeof(PACKET_CLASSES[pid])
        if actual != expected:
            problems.append(f"{PACKET_NAMES[pid]} {actual} != {expected}")
    return problems


LAYOUT_PROBLEMS = _verify_layout()


def parse_packet(buf: bytes):
    """Decode a datagram.

    Returns ``(packet_id, packet, header)`` or ``None`` if the buffer is too
    short to contain a header.
    """
    if len(buf) < HEADER_SIZE:
        return None
    header = PacketHeader.from_buffer_copy(buf[:HEADER_SIZE])
    cls = PACKET_CLASSES.get(header.packet_id)
    if cls is None:
        return header.packet_id, None, header
    expected = EXPECTED_SIZES.get(header.packet_id, C.sizeof(cls))
    if len(buf) < expected:
        # Truncated or wrong format: do not read past the buffer.
        return header.packet_id, None, header
    packet = cls.from_buffer_copy(buf[:expected])
    return header.packet_id, packet, header
