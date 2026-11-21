# Data reference

Everything the engineer knows, where it comes from, and what it means.
The live version is written to `.temp/live_state.json` four times a second and
shown in the overlay; type `status` in the engineer window to print it.

## Where it comes from

All data is read from F1 24's UDP telemetry (2024 format, port 20777). No memory
reading, no injection. Each packet is decoded in `app/telemetry/packets.py` and
folded into `app/telemetry/state.py`.

| Packet | Data used |
|---|---|
| Session | track, session type, weather, air/track temps, total laps, pit window, safety car, 64-sample forecast |
| Lap Data | position, lap, gaps, sector, pit status, penalties, last lap, speed trap — all 22 cars |
| Car Telemetry | speed, gear, RPM, throttle, brake, DRS, tyre/brake/engine temperatures, pressures — all cars |
| Car Status | fuel, fuel mix, ERS charge and deploy mode, compound, tyre age, flags — all cars |
| Car Damage | tyre wear/damage, wing/floor/diffuser/sidepod, engine component wear — all cars |
| Participants | driver names, teams, AI/human |
| Car Setups | wings, suspension, ride height, camber, toe, pressures, brake bias, fuel load |
| Session History | every completed lap with three sector times, validity, tyre stints |
| Tyre Sets | remaining sets: compound, wear, expected life, lap delta |
| Final Classification | finishing order, points, race time, penalties, stints |
| Lobby Info | lobby players and ready state |
| Motion / Motion Ex | g-forces, yaw/pitch/roll, suspension travel, ride heights, wheel forces |
| Time Trial | personal best and rival deltas (time trial only) |
| Event | overtakes, penalties, safety car, flags, fastest lap |

## Session

| Field | Unit | Notes |
|---|---|---|
| `track` | name | from the track id |
| `session` | text | practice/qualifying/race |
| `weather` | text | clear → storm |
| `air_temp_c`, `track_temp_c` | °C | |
| `lap`, `total_laps`, `laps_remaining` | laps | |
| `safety_car` | text | none / safety car / VSC / formation lap |
| `flag` | text | green / yellow / blue / red |
| `pit_window_ideal_lap`, `pit_window_latest_lap` | lap | published by the game |
| `pit_rejoin_position` | position | game's prediction |
| `rain_forecast` | list | `+10m light rain 65%` samples |

## Your car

| Field | Unit | Notes |
|---|---|---|
| `position`, `grid_position` | place | |
| `last_lap_s`, `current_lap_s`, `best_lap_s` | s | |
| `gap_ahead_s`, `gap_behind_s`, `gap_to_leader_s` | s | `gap_behind` is the follower's own delta |
| `gap_trend_s` | s | + = gap ahead opening, − = closing |
| `speed_kph`, `gear`, `rpm`, `drs` | | |
| `fuel_kg`, `fuel_laps_remaining` | kg / laps | |
| `fuel_per_lap_kg` | kg | learned from lap-over-lap fuel drop |
| `fuel_to_end_kg` | kg | fuel needed for the remaining distance |
| `fuel_surplus_laps` | laps | + in hand, − short |
| `ers_pct` | % | 0–100 of the 4 MJ store |
| `penalties_s`, `pit_stops`, `pit_status` | | |

## Tyres

| Field | Unit | Notes |
|---|---|---|
| `tyre.compound`, `tyre.c_index` | text | e.g. medium, C4 |
| `tyre.age_laps` | laps | |
| `tyre.wear_pct` | % per corner | order: rear-left, rear-right, front-left, front-right |
| `tyre.damage_pct` | % per corner | |
| `tyre.surface_c`, `tyre.inner_c` | °C | carcass delta = inner − surface |
| `tyre.pressure_psi` | psi | |
| `tyre.wear_rate_per_lap` | %/lap | learned from damage packets across laps |
| `tyre.predicted_life_laps` | laps | based on wear rate, 15 % safety margin |

The life estimate is a linear projection of recent wear. It is a guide, not a
guarantee — the game's own tyre model is not exposed.

## Systems

| Field | Unit |
|---|---|
| `systems.ers_pct`, `ers_mode` | %, none/medium/hotlap/overtake |
| `systems.ers_harvested_mj`, `ers_deployed_mj` | MJ this lap |
| `systems.fuel_mix` | lean/standard/rich/max |
| `systems.brake_bias_pct` | % front |
| `systems.engine_temp_c` | °C |
| `systems.brake_temps_c` | °C per corner |
| `systems.drs_allowed`, `drs_activation_distance_m` | |

## Pace

Built from Session History, only valid laps count.

| Field | Unit |
|---|---|
| `pace.best_lap_s`, `pace.last_lap_s`, `pace.delta_to_best_s` | s |
| `pace.best_sectors_s`, `pace.last_sectors_s`, `pace.sector_deltas_s` | s |
| `pace.rolling_pace_3_s` | s (average of last 3 valid laps) |
| `pace.pace_trend_s` | s (positive = slower than three laps ago) |

## Strategy

| Field | Unit | Notes |
|---|---|---|
| `strategy.pit_loss_s` | s | configurable, default 21 |
| `strategy.projected_rejoin_position` | place | where you would come out |
| `strategy.projected_gap_to_leader_s` | s | after the stop |
| `strategy.traffic_on_exit` | names | cars within `traffic_window_s` of your rejoin |
| `strategy.undercut_margin_s` | s | pit loss − gap to the car behind |
| `strategy.car_ahead`, `car_behind` | names | |

This is a projection from gaps and a fixed pit loss, not a simulation. Tune
`pit_loss_s` per track in `config.yaml`.

## The grid

`grid` is a list, sorted by position:

| Field | Notes |
|---|---|
| `pos`, `driver`, `lap` | |
| `gap_to_leader_s` | |
| `tyre`, `tyre_age` | compound and age |
| `wear_pct` | worst corner |
| `tyre_life` | predicted laps left |
| `predicted_pit_lap` | lap + predicted life |
| `last_lap_s` | |
| `stops`, `status`, `result`, `penalties_s`, `is_ai` | |

## History and setup

- `session_laps`: last 10 laps with `time_s`, `s1_s`, `s2_s`, `s3_s`, `valid`.
- `tyre_stints`: compound and end lap per stint.
- `tyre_sets`: every set with compound, wear, available, laps left, delta.
- `setup`: wings, suspension, ride heights, camber, toe, pressures, brake bias,
  engine braking, ballast, fuel load, next front wing.
- `final_classification`: finishing order, points, race time, penalties, stints.
- `motion`: g-forces, yaw/pitch/roll, ride heights, suspension, wheel forces.

## Tools the model can call

| Tool | Returns |
|---|---|
| `get_fuel_status` | fuel, per-lap use, to-end, surplus |
| `get_tyre_status` | compound, age, per-corner wear and temps, life |
| `get_race_status` | lap, position, gaps, flags, weather, pit window |
| `get_gap` | seconds to the car ahead/behind |
| `get_lap_history` | last completed laps |
| `get_grid` | full 22-car running order |
| `get_rival` | one rival's tyres, pace, stops, predicted stop lap |
| `get_tyre_sets` | remaining sets |
| `get_session_history` | laps, sectors, stints |
| `get_sector_times` | best and last sectors |
| `get_damage_report` | damage and engine wear |
| `get_weather_detail` | now and the full forecast |
| `get_setup` | current setup |
| `get_pace` | best/last lap, sector deltas, rolling pace, trend |
| `get_car_systems` | ERS, fuel mix, brake bias, temperatures, DRS |
| `get_strategy_projection` | rejoin position, exit traffic, undercut margin |

Factual questions are answered directly from these values without a model, so
the numbers cannot be hallucinated.
