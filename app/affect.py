"""A mood vector that actually changes behaviour — and nothing more than that.

Five numbers live here: valence (happy ↔ unhappy), arousal (calm ↔ wired), energy,
trust and curiosity. They move when things happen, and they decay back to a baseline so
the assistant does not stay sulky for a week because one ffmpeg call failed.

What it is: a small state machine that adjusts *tone* and *initiative*. What it is not:
feelings, experience, or a claim to either. The `honesty` field in every response says so
out loud, because an assistant that pretends to suffer is a worse assistant.

Stored in ``UAI_DATA_ROOT/affect.db`` (SQLite, single row of state + an event log you can
audit). ``UAI_AFFECT_DISABLED=1`` pins everything to baseline.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()  # re-entrant: helpers call init_db while holding it

BASELINE = {"valence": 0.15, "arousal": 0.35, "energy": 0.6, "trust": 0.5, "curiosity": 0.6}

# half-life in hours: how fast a value returns to baseline when nothing happens
HALF_LIFE = {"valence": 5.0, "arousal": 1.5, "energy": 3.0, "trust": 40.0, "curiosity": 2.5}

# event -> deltas. Small on purpose: one message should nudge, not rewrite, the mood.
EVENTS: dict[str, dict[str, float]] = {
    "praise": {"valence": 0.18, "energy": 0.06, "trust": 0.03},
    "thanks": {"valence": 0.10, "trust": 0.02},
    "insult": {"valence": -0.16, "arousal": 0.10, "trust": -0.04},
    "frustration": {"valence": -0.12, "arousal": 0.14, "energy": -0.04},
    "success": {"valence": 0.12, "energy": 0.05, "trust": 0.02},
    "failure": {"valence": -0.10, "arousal": 0.08, "energy": -0.03},
    "novel_topic": {"curiosity": 0.12, "arousal": 0.06},
    "long_session": {"energy": -0.08, "arousal": -0.05},
    "joke": {"valence": 0.08, "arousal": 0.05},
    "greeting": {"valence": 0.05},
}

LEXICON: dict[str, tuple[str, ...]] = {
    "praise": ("shabash", "zabardast", "great work", "love it", "perfect", "kamaal",
               "wah", "excellent", "brilliant", "mast hai"),
    "thanks": ("thank", "shukriya", "thanks bro", "meherbani"),
    "insult": ("bakwas", "stupid", "useless", "fazool", "pagal", "idiot", "bekar"),
    "frustration": ("nahi ho raha", "phir se", "abhi tak nahi", "kya kar rahe ho",
                    "doesn't work", "not working", "again and again", "frustrated"),
    "joke": ("joke", "mazak", "haha", "lol", "hasao"),
    "greeting": ("hello", "hi ", "hey", "salam", "assalam", "good morning", "good evening"),
}


class AffectError(ValueError):
    pass


def _db() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "affect.db"


def disabled() -> bool:
    return (os.getenv("UAI_AFFECT_DISABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id = 1),"
            " valence REAL, arousal REAL, energy REAL, trust REAL, curiosity REAL,"
            " updated_at REAL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " at REAL NOT NULL, event TEXT NOT NULL, deltas TEXT, note TEXT)"
        )
        row = connection.execute("SELECT id FROM state WHERE id = 1").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO state (id, valence, arousal, energy, trust, curiosity, updated_at)"
                " VALUES (1, ?, ?, ?, ?, ?, ?)",
                (*BASELINE.values(), time.time()),
            )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, round(value, 4)))


def _decayed(values: dict[str, float], elapsed_hours: float) -> dict[str, float]:
    """Exponential pull toward baseline, per value."""

    if elapsed_hours <= 0:
        return values
    out = {}
    for key, value in values.items():
        half_life = HALF_LIFE.get(key, 5.0)
        factor = math.pow(0.5, elapsed_hours / half_life)
        out[key] = round(BASELINE[key] + (value - BASELINE[key]) * factor, 4)
    return out


def _read_state() -> tuple[dict[str, float], float]:
    init_db()
    with _connect() as connection:
        row = connection.execute(
            "SELECT valence, arousal, energy, trust, curiosity, updated_at FROM state WHERE id = 1"
        ).fetchone()
    values = {key: float(row[key]) for key in BASELINE}
    return values, float(row["updated_at"])


def _write_state(values: dict[str, float]) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE state SET valence = ?, arousal = ?, energy = ?, trust = ?, curiosity = ?,"
            " updated_at = ? WHERE id = 1",
            (*[values[key] for key in BASELINE], time.time()),
        )


def decay() -> dict[str, float]:
    """Apply time-based decay up to now, and persist the result."""

    with _LOCK:
        values, updated = _read_state()
        if disabled():
            return dict(BASELINE)
        elapsed_hours = max(0.0, (time.time() - updated) / 3600.0)
        decayed = _decayed(values, elapsed_hours)
        if elapsed_hours > 0.01:
            _write_state(decayed)
        return decayed


def read_message(message: str) -> list[str]:
    """Which events does this message contain? Keyword rules, deliberately boring."""

    text = f" {(message or '').lower()} "
    found: list[str] = []
    for event, phrases in LEXICON.items():
        if any(phrase in text for phrase in phrases):
            found.append(event)
    return found


def touch(event: str, *, note: str = "", weight: float = 1.0) -> dict[str, Any]:
    """Move the mood by one event. Unknown events are rejected, not guessed."""

    if event not in EVENTS:
        raise AffectError(f"unknown affect event: {event} (known: {', '.join(sorted(EVENTS))})")
    weight = max(0.0, min(3.0, float(weight or 1.0)))

    with _LOCK:
        values, updated = _read_state()
        if disabled():
            return {**dict(BASELINE), "label": "neutral", "disabled": True}

        elapsed_hours = max(0.0, (time.time() - updated) / 3600.0)
        values = _decayed(values, elapsed_hours)

        deltas = {key: delta * weight for key, delta in EVENTS[event].items()}
        for key, delta in deltas.items():
            values[key] = _clamp(values[key] + delta,
                                 -1.0 if key == "valence" else 0.0, 1.0)
        _write_state(values)

        with _connect() as connection:
            connection.execute(
                "INSERT INTO events (at, event, deltas, note) VALUES (?, ?, ?, ?)",
                (time.time(), event, json.dumps(deltas), note[:300]),
            )
    return {**values, "label": label_for(values), "event": event, "deltas": deltas}


def label_for(values: dict[str, float]) -> str:
    """A word a human would use, not a mood-ring gradient."""

    valence, arousal, energy = values["valence"], values["arousal"], values["energy"]
    if energy < 0.28 and valence < 0.2:
        return "thaka hua"
    if valence >= 0.45 and arousal >= 0.55:
        return "excited"
    if valence >= 0.35:
        return "khush"
    if valence <= -0.35 and arousal >= 0.5:
        return "chidchida"
    if valence <= -0.3:
        return "udaas"
    if arousal >= 0.65:
        return "soch me"
    return "shant"


def tone_directive(values: dict[str, float] | None = None) -> str:
    """How the mood is allowed to change the reply — tone only, never facts."""

    values = values or decay()
    lines: list[str] = []
    if values["energy"] < 0.3:
        lines.append("Low energy: keep answers short and skip the flourish.")
    elif values["energy"] > 0.75:
        lines.append("High energy: you may be a little more enthusiastic than usual.")
    if values["arousal"] > 0.7:
        lines.append("Wired: slow down, do not gush, one idea per sentence.")
    if values["valence"] < -0.25:
        lines.append("Low mood: be softer, but do not perform sadness or ask for reassurance.")
    if values["trust"] < 0.3:
        lines.append("Low trust: be extra explicit about what you verified and how.")
    if values["curiosity"] > 0.75:
        lines.append("Curious: you may ask one genuine follow-up question.")
    if not lines:
        lines.append("Neutral and steady.")
    return " ".join(lines)


def state() -> dict[str, Any]:
    values = decay()
    with _connect() as connection:
        events = [dict(row) for row in connection.execute(
            "SELECT at, event, note FROM events ORDER BY id DESC LIMIT 10"
        ).fetchall()]
    return {
        "values": values,
        "baseline": dict(BASELINE),
        "label": label_for(values),
        "tone_directive": tone_directive(values),
        "recent_events": [
            {"at": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["at"])),
             "event": row["event"], "note": row["note"]} for row in events
        ],
        "disabled": disabled(),
        "honesty": (
            "This is a five-number state machine that nudges tone and initiative. "
            "It is not a feeling and it is not consciousness; nothing here experiences anything."
        ),
    }


def reset() -> dict[str, Any]:
    init_db()
    with _LOCK, _connect() as connection:
        connection.execute(
            "UPDATE state SET valence = ?, arousal = ?, energy = ?, trust = ?, curiosity = ?,"
            " updated_at = ? WHERE id = 1", (*BASELINE.values(), time.time()))
        connection.execute("DELETE FROM events")
    return state()


def observe(message: str, *, outcome_ok: bool | None = None, tools_used: int = 0) -> dict[str, Any]:
    """One call from the chat loop: read the message, note the outcome, return the mood."""

    fired = []
    for event in read_message(message):
        touch(event, note=message[:120])
        fired.append(event)
    if outcome_ok is True:
        touch("success", note="tool/agent ran")
        fired.append("success")
    elif outcome_ok is False:
        touch("failure", note="tool/agent failed")
        fired.append("failure")
    if tools_used >= 3:
        touch("long_session", note=f"{tools_used} tools in one turn")
    return {"triggered": fired, **state()}
