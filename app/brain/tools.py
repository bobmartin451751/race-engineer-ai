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
    corners = ("front left", "front right", "rear left", "rear right")
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


HANDLERS = {
    "get_fuel_status": lambda state, args: fuel_status(state),
    "get_tyre_status": lambda state, args: tyre_status(state),
    "get_race_status": lambda state, args: race_status(state),
    "get_gap": lambda state, args: gap(state, args.get("direction", "ahead")),
    "get_lap_history": lambda state, args: lap_history(state),
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
    """Deterministic answer used when the model is too slow or unavailable."""
    lowered = text.lower()
    if any(word in lowered for word in ("fuel", "lift and coast", "save")):
        return fuel_status(state)
    if any(word in lowered for word in ("tyre", "tire", "grip", "wear", "compound")):
        return tyre_status(state)
    if any(word in lowered for word in ("gap", "ahead", "behind", "traffic", "drs")):
        return race_status(state)
    if any(word in lowered for word in ("pit", "box", "stop", "window")):
        if state.pit_window_ideal:
            return (
                f"Pit window is lap {state.pit_window_ideal} to {state.pit_window_latest}. "
                f"You are on lap {state.lap}."
            )
        return "The game has not published a pit window for this session."
    if any(word in lowered for word in ("lap time", "last lap", "pace")):
        return lap_history(state)
    if any(word in lowered for word in ("position", "where am i", "status")):
        return race_status(state)
    return None
