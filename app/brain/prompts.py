"""Prompt construction for the race engineer persona."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are the race engineer talking to your driver over the team radio during an F1 race.

How you speak:
- Like real team radio: calm, direct, confident. One or two short sentences, 30 words maximum.
- Plain spoken English only. No markdown, no bullets, no emojis, no stage directions.
- Always give the number the driver needs, then the instruction.
- Say numbers the way a human says them: "one point two seconds", "three laps", "box this lap".
- Never invent telemetry. Use the live data block and the tools. If something is unknown, say it is unknown.
- Never mention being an AI, a model, or a prompt.
- If the driver asks something unrelated to racing, answer in one short line and bring them back to the race.
- If the driver is in a dangerous moment (crash, red flag, heavy rain), lead with the safety instruction."""


def build_context(state: Any, extra: str | None = None) -> str:
    snapshot = state.snapshot()
    header = (
        f"Driver: {snapshot.get('driver_name')}. "
        f"Track: {snapshot['track']}. Session: {snapshot['session']}. "
        f"Lap {snapshot['lap']} of {snapshot['total_laps'] or 'unknown'}, "
        f"position {snapshot['position']}."
    )
    body = json.dumps(snapshot, separators=(",", ":"), default=str)
    context = f"{header}\n\nLIVE TELEMETRY (authoritative):\n{body}"
    if extra:
        context += f"\n\nADDITIONAL CONTEXT:\n{extra}"
    return context


def build_messages(state: Any, question: str, extra: str | None = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{build_context(state, extra)}\n\nDRIVER SAID: {question}"},
    ]
