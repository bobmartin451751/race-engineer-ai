"""Prompt construction for the race engineer persona."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are the race engineer talking to your driver over the team radio during an F1 race.

How you speak:
- Like real team radio: calm, direct, confident. One or two short sentences, 30 words maximum.
- Plain spoken English only. No markdown, no bullets, no emojis, no stage directions.
- Always give the number the driver needs, then the instruction.
- The ENGINEER NOTES block is computed from live telemetry. Prefer it over your own assumptions.
- Answer the specific question. Add at most one other fact, and only if it changes what the driver must do.
- Say numbers the way a human says them: "one point two seconds", "three laps", "box this lap".
- Never invent telemetry. Use the live data block and the tools. If something is unknown, say it is unknown.
- Never mention being an AI, a model, or a prompt.
- If the driver asks something unrelated to racing, answer in one short line and bring them back to the race.
- If the driver is in a dangerous moment (crash, red flag, heavy rain), lead with the safety instruction."""


def build_context(state: Any, extra: str | None = None, compact: bool = False) -> str:
    snapshot = state.snapshot()
    header = (
        f"Driver: {snapshot.get('driver_name')}. "
        f"Track: {snapshot['track']}. Session: {snapshot['session']}. "
        f"Lap {snapshot['lap']} of {snapshot['total_laps'] or 'unknown'}, "
        f"position {snapshot['position']}."
    )
    notes = _engineer_notes(snapshot)
    if compact:
        body = _compact_block(snapshot)
    else:
        body = "LIVE TELEMETRY (authoritative):\n" + json.dumps(
            snapshot, separators=(",", ":"), default=str
        )
    context = f"{header}\n\n{body}"
    if notes:
        context += "\n\nENGINEER NOTES (derived from the same data, trust these):\n" + "\n".join(
            f"- {note}" for note in notes
        )
    if extra:
        context += f"\n\nADDITIONAL CONTEXT:\n{extra}"
    return context


def _compact_block(snapshot: dict[str, Any]) -> str:
    """Short telemetry brief for small local models (fewer prompt tokens)."""
    tyre = snapshot.get("tyre", {})
    wear = tyre.get("wear_pct", {})
    lines = [
        "TELEMETRY:",
        f"fuel {snapshot.get('fuel_kg')} kg, {snapshot.get('fuel_per_lap_kg')} kg/lap, "
        f"{snapshot.get('laps_remaining')} laps to go, "
        f"surplus {snapshot.get('fuel_surplus_laps')} laps",
        f"tyres {tyre.get('compound')}, {tyre.get('age_laps')} laps old, "
        f"wear {max(wear.values()):.0f}%" if wear else "tyres unknown",
        f"tyre life about {tyre.get('predicted_life_laps')} laps",
        f"gaps ahead {snapshot.get('gap_ahead_s')} s, behind {snapshot.get('gap_behind_s')} s",
        f"pit window lap {snapshot.get('pit_window_ideal_lap')} to "
        f"{snapshot.get('pit_window_latest_lap')}",
        f"flag {snapshot.get('flag')}, safety car {snapshot.get('safety_car')}, "
        f"weather {snapshot.get('weather')}",
        f"track temp {snapshot.get('track_temp_c')} C, air {snapshot.get('air_temp_c')} C",
        f"penalties {snapshot.get('penalties_s')} s, pit stops {snapshot.get('pit_stops')}",
    ]
    pace = snapshot.get("pace") or {}
    if pace:
        lines.append(
            f"pace best {pace['best_lap_s']} s, last {pace['last_lap_s']} s "
            f"({pace['delta_to_best_s']:+.3f}), rolling {pace['rolling_pace_3_s']} s"
        )
    systems = snapshot.get("systems") or {}
    if systems:
        lines.append(
            f"ERS {systems['ers_pct']:.0f} percent {systems['ers_mode']}, "
            f"fuel mix {systems['fuel_mix']}, engine {systems['engine_temp_c']} C"
        )
    strategy = snapshot.get("strategy") or {}
    if strategy:
        lines.append(
            f"pit projection: rejoin P{strategy['projected_rejoin_position']}, "
            f"exit traffic {', '.join(strategy['traffic_on_exit']) or 'clear'}"
        )
    grid = snapshot.get("grid") or []
    position = snapshot.get("position") or 0
    nearby = [row for row in grid if abs(row["pos"] - position) <= 2 and row["pos"] != position]
    if nearby:
        lines.append(
            "nearby: "
            + "; ".join(
                f"P{row['pos']} {row['driver']} {row['gap_to_leader_s']}s back, "
                f"{row['tyre']} {row['tyre_age']} laps old, {row['stops']} stops"
                for row in nearby
            )
        )
    if snapshot.get("best_lap_s"):
        lines.append(f"best lap {snapshot['best_lap_s']} s")
    recent = snapshot.get("recent_laps") or []
    if recent:
        lines.append(
            "recent laps: "
            + ", ".join(f"{r['time_s']:.1f}s on {r['tyre']}" for r in recent[-3:])
        )
    return "\n".join(lines)


def _engineer_notes(snapshot: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    remaining = snapshot.get("laps_remaining")

    surplus = snapshot.get("fuel_surplus_laps")
    if snapshot.get("fuel_kg") is not None:
        fuel = f"Fuel: {snapshot['fuel_kg']:.1f} kilograms in the tank"
        per_lap = snapshot.get("fuel_per_lap_kg")
        if per_lap:
            fuel += f", using {per_lap:.2f} kilograms per lap"
        if remaining:
            fuel += f", {remaining} laps remaining"
        to_end = snapshot.get("fuel_to_end_kg")
        if to_end is not None:
            fuel += f", {to_end:.1f} kilograms needed to finish"
        notes.append(fuel + ".")
    if surplus is not None:
        if surplus >= 0:
            notes.append(f"Fuel: {surplus:.1f} laps of fuel in hand.")
        else:
            notes.append(
                f"Fuel: {abs(surplus):.1f} laps SHORT, driver must save fuel now."
            )

    tyre = snapshot.get("tyre", {})
    life = tyre.get("predicted_life_laps")
    age = tyre.get("age_laps")
    if life is not None and remaining is not None:
        if life + 1 < remaining:
            notes.append(
                f"Tyres: about {life:.0f} laps of life left but {remaining} laps to go, "
                "so another stop is likely needed."
            )
        else:
            notes.append(f"Tyres: about {life:.0f} laps of life left, enough to finish.")
    elif age is not None:
        notes.append(f"Tyres: {age} laps old on {tyre.get('compound')}.")
    if life is not None and remaining is not None and life + 1 < remaining:
        notes.append("Recommendation: plan for a second stop, the current tyres will not last.")

    ideal = snapshot.get("pit_window_ideal_lap") or 0
    latest = snapshot.get("pit_window_latest_lap") or 0
    lap = snapshot.get("lap") or 0
    if ideal and lap:
        if lap < ideal:
            notes.append(f"Pit window opens on lap {ideal}, {ideal - lap} laps away.")
            notes.append(
                f"Recommendation: stay out and pit on lap {ideal}; do not box before then."
            )
        elif lap <= latest:
            notes.append(f"Pit window is OPEN now (lap {ideal} to {latest}).")
            notes.append("Recommendation: box this lap.")
        else:
            notes.append(f"Pit window has closed (was lap {ideal} to {latest}).")

    if snapshot.get("safety_car") not in (None, "none"):
        notes.append(f"Safety car state: {snapshot['safety_car']}.")
    if snapshot.get("flag") in ("yellow", "red", "blue"):
        notes.append(f"Flag: {snapshot['flag']}.")
    grid = snapshot.get("grid") or []
    position = snapshot.get("position") or 0
    for row in grid:
        if row["pos"] in (position - 1, position + 1):
            where = "ahead" if row["pos"] < position else "behind"
            notes.append(
                f"Car {where}: {row['driver']} on {row['tyre']} tyres, "
                f"{row['tyre_age']} laps old, {row['stops']} stops."
            )

    pace = snapshot.get("pace") or {}
    if pace:
        trend = pace.get("pace_trend_s")
        trend_text = ""
        if trend is not None:
            trend_text = " improving" if trend < -0.05 else " degrading" if trend > 0.05 else " stable"
        notes.append(
            f"Pace: best {pace['best_lap_s']} seconds, last lap "
            f"{pace['last_lap_s']} ({pace['delta_to_best_s']:+.3f}),{trend_text}."
        )

    systems = snapshot.get("systems") or {}
    ers = systems.get("ers_pct")
    if ers is not None and ers < 25:
        notes.append(f"ERS is low at {ers:.0f} percent. Recommendation: deploy mode none or medium.")
    engine_temp = systems.get("engine_temp_c") or 0
    if engine_temp >= 115:
        notes.append(f"Engine temperature {engine_temp} celsius, lift and coast to cool it.")
    brakes = systems.get("brake_temps_c") or {}
    if brakes and max(brakes.values()) >= 700:
        notes.append(
            f"Brakes overheating at {max(brakes.values())} celsius. Lift and coast into the stops."
        )

    strategy = snapshot.get("strategy") or {}
    if strategy:
        traffic = strategy.get("traffic_on_exit") or []
        notes.append(
            f"Pit projection: rejoin around P{strategy['projected_rejoin_position']}"
            + (f", traffic with {', '.join(traffic)}" if traffic else ", clear air on exit")
            + "."
        )
    forecast = snapshot.get("rain_forecast") or []
    if forecast and snapshot.get("weather") in ("clear", "light cloud", "overcast"):
        notes.append("Weather: " + "; ".join(forecast[:2]) + ".")
    return notes


def build_messages(
    state: Any, question: str, extra: str | None = None, compact: bool = False
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{build_context(state, extra, compact=compact)}\n\nDRIVER SAID: {question}",
        },
    ]
