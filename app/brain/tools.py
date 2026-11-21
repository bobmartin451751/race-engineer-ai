"""Deterministic telemetry queries exposed to the language model as tools.

Every number the engineer speaks about should come from here, so the model
never invents a fuel figure or a tyre life.
"""

from __future__ import annotations

import json
from typing import Any

from ..telemetry.state import RaceState

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_fuel_status",
            "description": "Current fuel load, fuel per lap, fuel needed to finish and surplus/deficit in laps.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tyre_status",
            "description": "Tyre compound, age, per-corner wear and temperatures, wear rate and predicted remaining life.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_race_status",
            "description": "Lap, position, gaps, flags, safety car, weather and pit window.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_gap",
            "description": "Gap in seconds to the car directly ahead or behind.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["ahead", "behind"]}
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lap_history",
            "description": "The last few completed lap times with the tyre used.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_grid",
            "description": "Full running order: position, driver, gap to leader, tyre, tyre age, pit stops and status for every car.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rival",
            "description": "Detailed report on one rival, by race position or driver name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reference": {
                        "type": "string",
                        "description": "Race position as a digit, or part of the driver name",
                    }
                },
                "required": ["reference"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tyre_sets",
            "description": "Remaining tyre sets for the player: compound, wear, available, expected life and lap delta.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_history",
            "description": "All completed laps for the player with sector times, plus tyre stints.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_times",
            "description": "Best and most recent sector times for the player.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_damage_report",
            "description": "Complete damage report for the player's car, including engine component wear.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_detail",
            "description": "Weather now and the full forecast with rain probability per sample.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_setup",
            "description": "The player's current car setup.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pace",
            "description": "Lap and sector pace: best lap, last lap delta, sector deltas, rolling three-lap pace and trend.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_car_systems",
            "description": "ERS charge, deploy mode, harvested/deployed energy, fuel mix, brake bias, engine temperature, brake temperatures, DRS state.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_strategy_projection",
            "description": "Pit-stop projection: rejoin position, traffic on pit exit, gap after the stop, undercut margin.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def fuel_status(state: RaceState) -> str:
    remaining = state.laps_remaining()
    to_end = state.fuel_to_end_kg()
    surplus = state.fuel_surplus_laps()
    if remaining is None or to_end is None:
        return (
            f"Fuel in tank {_fmt(state.fuel_kg)} kilograms; "
            "not enough laps completed to project fuel to the end."
        )
    parts = [
        f"Fuel in tank {_fmt(state.fuel_kg)} kilograms",
        f"average {_fmt(state.fuel_per_lap_kg, 2)} kilograms per lap",
        f"{remaining} laps remaining",
        f"needs {_fmt(to_end)} kilograms to finish",
    ]
    if surplus is not None:
        if surplus >= 0:
            parts.append(f"surplus of {_fmt(surplus)} laps")
        else:
            parts.append(f"SHORT by {_fmt(abs(surplus))} laps")
    return "; ".join(parts) + "."


def tyre_status(state: RaceState) -> str:
    wear = state.tyre_wear
    life = state.predicted_tyre_life()
    corners = ("rear left", "rear right", "front left", "front right")
    wear_text = ", ".join(f"{c} {_fmt(w)} percent" for c, w in zip(corners, wear))
    temp_text = ", ".join(
        f"{c} {int(t)}" for c, t in zip(corners, state.tyre_surface_c)
    )
    parts = [
        f"{state.compound_name} tyres"
        + (f" ({state.compound_c_index})" if state.compound_c_index else ""),
        f"{state.tyre_age_laps} laps old",
        f"wear: {wear_text}",
        f"surface temperatures: {temp_text} celsius",
    ]
    if state.wear_per_lap:
        parts.append(f"wear rate {_fmt(state.wear_per_lap, 2)} percent per lap")
    if life is not None:
        parts.append(f"predicted {_fmt(life)} laps of life left")
    return "; ".join(parts) + "."


def race_status(state: RaceState) -> str:
    parts = [
        f"Lap {state.lap} of {state.total_laps or 'unknown'}",
        f"position {state.position}",
        f"track {state.track_name}",
        f"weather {state.weather}",
    ]
    if state.gap_ahead_s is not None:
        parts.append(f"gap ahead {_fmt(state.gap_ahead_s)} seconds")
    else:
        parts.append("no car directly ahead")
    if state.gap_behind_s is not None:
        parts.append(f"gap behind {_fmt(state.gap_behind_s)} seconds")
    if state.safety_car:
        parts.append(f"safety car status {state.safety_car}")
    if state.fia_flag:
        parts.append(f"flag {state.fia_flag}")
    if state.pit_window_ideal:
        parts.append(
            f"pit window lap {state.pit_window_ideal} to {state.pit_window_latest}"
        )
    if state.penalties_s:
        parts.append(f"{state.penalties_s} seconds of penalties")
    return "; ".join(parts) + "."


def gap(state: RaceState, direction: str) -> str:
    direction = (direction or "ahead").lower()
    if "behind" in direction:
        if state.gap_behind_s is None:
            return "No car close behind."
        return f"{_fmt(state.gap_behind_s)} seconds to the car behind."
    if state.gap_ahead_s is None:
        return "No car directly ahead."
    return f"{_fmt(state.gap_ahead_s)} seconds to the car ahead."


def lap_history(state: RaceState) -> str:
    laps = list(state.lap_history)[-5:]
    if not laps:
        return "No completed laps recorded yet."
    return "; ".join(
        f"lap {r.lap_number} {r.seconds:.3f} seconds on {r.compound}" for r in laps
    ) + "."


def grid_summary(state: RaceState) -> str:
    rows = state.grid()
    if not rows:
        return "No running order yet."
    return "; ".join(
        f"P{r['pos']} {r['driver']} {r['gap_to_leader_s']} seconds back on "
        f"{r['tyre']} tyres {r['tyre_age']} laps old, {r['stops']} stops"
        for r in rows
    ) + "."


def spoken_rival(car) -> str:
    gap = car.delta_leader_ms / 1000.0 if car.delta_leader_ms else 0.0
    if gap:
        place = f"P{car.position}, {gap:.1f} seconds off the lead"
    else:
        place = f"P{car.position}, leading"
    return (
        f"{car.name} is {place}, on {car.compound_name} tyres "
        f"{car.tyre_age_laps} laps old, {car.pit_stops} stops."
    )


def rival_report(state: RaceState, reference: str) -> str:
    car = state.rival(reference)
    if car is None:
        return f"No car found matching {reference}."
    parts = [
        f"P{car.position} {car.name}",
        f"{car.delta_leader_ms / 1000.0:.1f} seconds off the leader"
        if car.delta_leader_ms else "leading",
        f"{car.compound_name} tyres {car.tyre_age_laps} laps old",
        f"{car.pit_stops} pit stops",
        f"status {PIT_STATUS_TEXT.get(car.result_status, 'racing')}",
    ]
    if car.last_lap_ms:
        parts.append(f"last lap {car.last_lap_ms / 1000.0:.3f}")
    if car.tyre_wear:
        parts.append(f"{max(car.tyre_wear):.0f} percent tyre wear")
    life = car.predicted_tyre_life
    if life is not None:
        parts.append(
            f"about {life:.0f} laps of tyre life left, likely to stop around lap "
            f"{car.lap + round(life)}"
        )
    if car.gap_ahead_ms:
        parts.append(f"{car.gap_ahead_ms / 1000.0:.1f} seconds behind the car ahead")
    if car.penalties_s:
        parts.append(f"{car.penalties_s} seconds of penalties")
    return "; ".join(parts) + "."


def tyre_set_report(state: RaceState) -> str:
    sets = state.tyre_sets
    if not sets:
        return "No tyre set information received yet."
    available = [s for s in sets if s["available"]]
    if not available:
        return "No new tyre sets available."
    return "Available sets: " + "; ".join(
        f"{s['compound']} with {s['laps_left']} laps of life, "
        f"{s['wear']} percent wear, delta {s['delta_ms']} milliseconds"
        for s in available
    ) + "."


def session_history_report(state: RaceState) -> str:
    laps = state.session_laps
    if not laps:
        return "No session history received yet."
    recent = laps[-5:]
    lap_text = "; ".join(
        f"lap {lap['lap']} {lap['time_s']} seconds "
        f"(sectors {lap['s1_s']}, {lap['s2_s']}, {lap['s3_s']})"
        for lap in recent
    )
    stints = state.tyre_stints
    stint_text = ""
    if stints:
        stint_text = " Stints: " + ", ".join(
            f"{s['compound']} to lap {s['end_lap']}" for s in stints
        ) + "."
    return lap_text + "." + stint_text


def sector_times(state: RaceState) -> str:
    me = state.player
    if not me.session_laps:
        return "No sector data received yet."
    last = me.session_laps[-1]
    return (
        f"Last lap sectors {last['s1_s']}, {last['s2_s']}, {last['s3_s']} seconds. "
        f"Best sectors {me.best_s1_ms / 1000.0:.3f}, {me.best_s2_ms / 1000.0:.3f}, "
        f"{me.best_s3_ms / 1000.0:.3f}."
    )


def damage_report(state: RaceState) -> str:
    me = state.player
    wear = me.engine_wear or {}
    return (
        f"Front wing {me.wing_damage} percent, floor {me.floor_damage}, "
        f"diffuser {me.diffuser_damage}, sidepod {me.sidepod_damage}, "
        f"gearbox {me.gearbox_damage}, engine {me.engine_damage} percent. "
        f"Engine wear: " + ", ".join(f"{k} {v} percent" for k, v in wear.items()) + "."
    )


def weather_detail(state: RaceState) -> str:
    now = WEATHER_TEXT.get(state.weather, "unknown")
    forecast = ", ".join(
        f"in {s['minutes']} minutes {s['weather']} {s['rain_pct']} percent rain"
        for s in state.forecast[:8]
    )
    return (
        f"Now {now}, track {state.track_temp_c} celsius, air {state.air_temp_c}. "
        f"Forecast: {forecast}."
    )


def setup_report(state: RaceState) -> str:
    setup = state.setup
    if not setup:
        return "No setup data received yet."
    return "; ".join(f"{key.replace('_', ' ')} {value}" for key, value in setup.items()) + "."


def pace_report(state: RaceState) -> str:
    pace = state.pace_summary()
    if not pace:
        return "No completed laps yet."
    trend = pace["pace_trend_s"]
    if trend is None:
        trend_text = "no trend yet"
    elif trend < -0.05:
        trend_text = "improving"
    elif trend > 0.05:
        trend_text = "degrading"
    else:
        trend_text = "stable"
    sectors = pace["last_sectors_s"]
    deltas = pace["sector_deltas_s"]
    return (
        f"Best lap {pace['best_lap_s']} seconds, last lap {pace['last_lap_s']} "
        f"({pace['delta_to_best_s']:+.3f}). "
        f"Last sectors {sectors['s1']}, {sectors['s2']}, {sectors['s3']} "
        f"(deltas {deltas['s1']:+.3f}, {deltas['s2']:+.3f}, {deltas['s3']:+.3f}). "
        f"Rolling pace {pace['rolling_pace_3_s']}, {trend_text}."
    )


def systems_report(state: RaceState) -> str:
    s = state.systems()
    brakes = s.get("brake_temps_c", {})
    hottest_brake = max(brakes.values()) if brakes else 0
    return (
        f"ERS {s['ers_pct']:.0f} percent, mode {s['ers_mode']}, "
        f"harvested {s['ers_harvested_mj']} megajoules, deployed {s['ers_deployed_mj']}. "
        f"Fuel mix {s['fuel_mix']}. Brake bias {s['brake_bias_pct']} percent, "
        f"hottest brake {hottest_brake} celsius. Engine {s['engine_temp_c']} celsius. "
        f"DRS {'available' if s['drs_allowed'] else 'not available'}."
    )


def strategy_report(state: RaceState) -> str:
    s = state.pit_projection()
    if not s:
        return "No position data yet."
    traffic = ", ".join(s["traffic_on_exit"]) if s["traffic_on_exit"] else "clear air"
    return (
        f"Pit loss about {s['pit_loss_s']} seconds. You would rejoin around "
        f"P{s['projected_rejoin_position']}, {s['projected_gap_to_leader_s']} seconds "
        f"off the lead. Exit traffic: {traffic}. "
        f"Undercut margin {s['undercut_margin_s']} seconds."
    )


PIT_STATUS_TEXT = {0: "invalid", 1: "inactive", 2: "racing", 3: "finished", 4: "DNF"}
WEATHER_TEXT = {
    0: "clear", 1: "light cloud", 2: "overcast", 3: "light rain", 4: "heavy rain",
    5: "storm",
}


HANDLERS = {
    "get_fuel_status": lambda state, args: fuel_status(state),
    "get_tyre_status": lambda state, args: tyre_status(state),
    "get_race_status": lambda state, args: race_status(state),
    "get_gap": lambda state, args: gap(state, args.get("direction", "ahead")),
    "get_lap_history": lambda state, args: lap_history(state),
    "get_grid": lambda state, args: grid_summary(state),
    "get_rival": lambda state, args: rival_report(state, args.get("reference", "")),
    "get_tyre_sets": lambda state, args: tyre_set_report(state),
    "get_session_history": lambda state, args: session_history_report(state),
    "get_sector_times": lambda state, args: sector_times(state),
    "get_damage_report": lambda state, args: damage_report(state),
    "get_weather_detail": lambda state, args: weather_detail(state),
    "get_setup": lambda state, args: setup_report(state),
    "get_pace": lambda state, args: pace_report(state),
    "get_car_systems": lambda state, args: systems_report(state),
    "get_strategy_projection": lambda state, args: strategy_report(state),
}


def execute_tool(name: str, raw_args: str | dict, state: RaceState) -> str:
    handler = HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            args = {}
    else:
        args = raw_args or {}
    try:
        return handler(state, args)
    except Exception as exc:  # noqa: BLE001
        return f"Tool {name} failed: {exc}"


def quick_answer(text: str, state: RaceState) -> str | None:
    """Deterministic spoken answer used for factual questions and as a fallback."""
    lowered = text.lower()

    # A named rival always wins over the generic player-car keywords.
    for car in state.cars:
        if car.index == state.player_index or len(car.name) < 3:
            continue
        if car.name.lower() in lowered:
            return spoken_rival(car)

    if any(word in lowered for word in ("who", "which car", "what car")):
        me = state.player
        if "behind" in lowered:
            other = state.rival(me.position + 1)
            where = "behind"
        else:
            other = state.rival(me.position - 1)
            where = "ahead"
        if other is None:
            return f"No car {where}."
        gap = state.gap_behind_s if where == "behind" else state.gap_ahead_s
        gap_text = f"{gap:.1f} seconds" if gap is not None else "close by"
        return (
            f"{other.name} is {where}, {gap_text}, on {other.compound_name} tyres "
            f"{other.tyre_age_laps} laps old."
        )

    if any(word in lowered for word in ("ers", "battery", "engine temp", "brake temp", "fuel mix", "brake bias")):
        return systems_report(state)

    if any(word in lowered for word in ("pace", "sector", "delta to best")):
        return pace_report(state)

    if any(word in lowered for word in ("rejoin", "pit loss", "traffic", "undercut", "overcut")):
        return strategy_report(state)

    if any(word in lowered for word in ("fuel", "lift and coast", "save")):
        surplus = state.fuel_surplus_laps()
        base = f"{state.fuel_kg:.1f} kilograms of fuel"
        if surplus is None:
            return base + "."
        if surplus >= 0.3:
            return f"{base}, about {surplus:.1f} laps in hand. Plenty to the end."
        if surplus > -0.3:
            return f"{base}, right on the limit for the finish."
        return f"{base}, {abs(surplus):.1f} laps short. Lift and coast."
    if any(word in lowered for word in ("tyre", "tire", "grip", "wear", "compound")):
        wear = max(state.tyre_wear) if state.tyre_wear else 0.0
        life = state.predicted_tyre_life()
        text_out = (
            f"{state.compound_name.capitalize()}s, {state.tyre_age_laps} laps old, "
            f"{wear:.0f} percent wear"
        )
        if life is not None:
            text_out += f", about {life:.0f} laps of life left"
        return text_out + "."
    if any(word in lowered for word in ("gap", "ahead", "behind", "traffic", "drs")):
        if "behind" in lowered:
            if state.gap_behind_s is None:
                return "Nothing close behind."
            return f"{state.gap_behind_s:.1f} seconds to the car behind."
        if state.gap_ahead_s is None:
            return "No car directly ahead."
        return f"{state.gap_ahead_s:.1f} seconds to the car ahead."
    if any(word in lowered for word in ("pit", "box", "stop", "window")):
        if not state.pit_window_ideal:
            return "The game has not published a pit window for this session."
        ideal, latest, lap = state.pit_window_ideal, state.pit_window_latest, state.lap
        if lap < ideal:
            return (
                f"Pit window is lap {ideal} to {latest}, opens in {ideal - lap} laps. "
                "Stay out."
            )
        if lap <= latest:
            return "Pit window is open. Box this lap."
        return f"Pit window closed on lap {latest}."
    if any(word in lowered for word in ("lap time", "last lap", "pace")):
        if state.last_lap_ms:
            minutes, seconds = divmod(state.last_lap_ms / 1000.0, 60)
            lap_text = (
                f"{int(minutes)} minute {seconds:04.1f}" if minutes else f"{seconds:.1f}"
            )
            return f"Last lap {lap_text}."
        return "No completed lap yet."
    if any(word in lowered for word in ("position", "where am i", "status")):
        return (
            f"Lap {state.lap} of {state.total_laps}, position {state.position}, "
            f"{state.compound_name} tyres {state.tyre_age_laps} laps old."
        )
    return None
