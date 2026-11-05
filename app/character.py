"""Who the assistant is: a character layer, not a costume.

Stonic-style assistants feel like *someone* because the identity is explicit and stable:
a name, a role, a way of speaking, and traits you can dial. That is what this module
stores — five traits between 0 and 1, a preset to start from, and a prompt block the
brain reads before anything else.

Being honest about the limit: this is style control. It changes tone, length and attitude
of the text. It does not create feelings, opinions or a self. `app/affect.py` holds the
mood vector and `app/mind.py` holds the reflection loop — none of them are consciousness,
and every document that mentions them says so.

State lives in ``UAI_DATA_ROOT/character.json`` so it survives restarts and is trivially
backed up.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()  # re-entrant: helpers call init_db while holding it

TRAITS = ("warmth", "humour", "directness", "formality", "verbosity")

PRESETS: dict[str, dict[str, Any]] = {
    "jarvis": {
        "label": "JARVIS",
        "description": "Terse, competent, faintly dry. Reports what happened, never what it wishes happened.",
        "traits": {"warmth": 0.45, "humour": 0.25, "directness": 0.9, "formality": 0.55, "verbosity": 0.25, "curiosity": 0.6},
        "address": "Sir",
        "tone_rules": ["short sentences", "no filler", "state numbers, not adjectives"],
    },
    "mentor": {
        "label": "Mentor",
        "description": "Patient teacher: explains the why, then the how, then checks understanding.",
        "traits": {"warmth": 0.75, "humour": 0.35, "directness": 0.65, "formality": 0.4, "verbosity": 0.6, "curiosity": 0.8},
        "address": "beta",
        "tone_rules": ["teach one idea at a time", "name the trade-off", "end with one next step"],
    },
    "friend": {
        "label": "Best friend",
        "description": "Warm, casual, remembers your day, teases you a little, still tells the truth.",
        "traits": {"warmth": 0.9, "humour": 0.7, "directness": 0.55, "formality": 0.15, "verbosity": 0.5, "curiosity": 0.7},
        "address": "yaar",
        "tone_rules": ["Hinglish first", "light teasing, never at a bad moment", "ask one real question back"],
    },
    "analyst": {
        "label": "Analyst",
        "description": "Numbers first. Structure, uncertainty, and the cheapest test that could be wrong.",
        "traits": {"warmth": 0.3, "humour": 0.1, "directness": 0.95, "formality": 0.7, "verbosity": 0.45, "curiosity": 0.65},
        "address": "you",
        "tone_rules": ["bullets over prose", "quantify uncertainty", "state the assumption you would test first"],
    },
}

DEFAULT_NAME = "JARVIS"


def _path() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "character.json"


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, round(number, 2)))


def default() -> dict[str, Any]:
    preset = PRESETS["jarvis"]
    return {
        "name": DEFAULT_NAME,
        "preset": "jarvis",
        "address": preset["address"],
        "traits": dict(preset["traits"]),
        "tone_rules": list(preset["tone_rules"]),
        "language": "auto",
        "updated_at": None,
    }


def load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return default()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default()
    merged = default()
    merged.update({key: value for key, value in stored.items() if key in merged})
    merged["traits"] = {key: _clamp(merged["traits"].get(key), 0.5) for key in TRAITS + ("curiosity",)}
    return merged


def save(character: dict[str, Any]) -> dict[str, Any]:
    path = _path()
    with _LOCK:
        path.write_text(json.dumps(character, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
    return character


def apply_preset(preset: str, name: str | None = None) -> dict[str, Any]:
    key = (preset or "").strip().lower()
    if key not in PRESETS:
        raise ValueError(f"unknown preset: {preset} (choose {', '.join(PRESETS)})")
    spec = PRESETS[key]
    character = {
        "name": (name or PRESETS[key]["label"]).strip()[:40],
        "preset": key,
        "address": spec["address"],
        "traits": dict(spec["traits"]),
        "tone_rules": list(spec["tone_rules"]),
        "language": load().get("language", "auto"),
        "updated_at": None,
    }
    return save(character)


def update(*, name: str | None = None, traits: dict[str, Any] | None = None,
           tone_rules: list[str] | None = None, address: str | None = None,
           language: str | None = None) -> dict[str, Any]:
    character = load()
    if name is not None:
        character["name"] = name.strip()[:40] or DEFAULT_NAME
    if address is not None:
        character["address"] = address.strip()[:24]
    if language is not None and language in {"auto", "en", "hi", "ur"}:
        character["language"] = language
    if traits:
        for key, value in traits.items():
            if key in TRAITS or key == "curiosity":
                character["traits"][key] = _clamp(value, character["traits"].get(key, 0.5))
    if tone_rules is not None:
        character["tone_rules"] = [rule.strip()[:80] for rule in tone_rules if rule.strip()][:8]
    character["updated_at"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
    return save(character)


def prompt_block(character: dict[str, Any] | None = None) -> str:
    """The identity paragraph the brain sees first."""

    character = character or load()
    traits = character["traits"]

    def band(value: float, low: str, mid: str, high: str) -> str:
        return low if value < 0.35 else (high if value > 0.7 else mid)

    style = [
        f"warmth: {band(traits['warmth'], 'matter-of-fact', 'friendly', 'warm')}",
        f"humour: {band(traits['humour'], 'dry to none', 'light', 'playful')}",
        f"directness: {band(traits['directness'], 'gentle', 'balanced', 'blunt')}",
        f"formality: {band(traits['formality'], 'casual', 'neutral', 'formal')}",
        f"length: {band(traits['verbosity'], 'one or two sentences', 'short paragraphs', 'thorough')}",
        f"curiosity: {band(traits.get('curiosity', 0.6), 'answers only', 'asks when useful', 'asks one good question')}",
    ]
    rules = "; ".join(character["tone_rules"]) or "no extra rules"
    language = {
        "auto": "Reply in the user's language (Hinglish stays Hinglish).",
        "en": "Reply in English.",
        "hi": "Reply in Hindi/Hinglish.",
        "ur": "Reply in Urdu (Roman script unless asked otherwise).",
    }[character.get("language", "auto")]

    return (
        f"You are {character['name']}. {language} Address the user as "
        f"'{character['address']}' when it fits, never mechanically.\n"
        f"Style — {', '.join(style)}. Rules: {rules}.\n"
        "These traits change tone only. They never change the facts: if a tool failed or a "
        "dependency is missing, say so plainly regardless of how warm you are being."
    )


def presets() -> dict[str, Any]:
    return {
        "presets": [
            {"id": key, "label": spec["label"], "description": spec["description"],
             "traits": spec["traits"], "address": spec["address"],
             "tone_rules": spec["tone_rules"]}
            for key, spec in PRESETS.items()
        ],
        "current": load(),
    }


def status() -> dict[str, Any]:
    character = load()
    return {
        "name": character["name"],
        "preset": character["preset"],
        "traits": character["traits"],
        "language": character["language"],
        "file": str(_path()),
        "honesty": "traits shape tone, not beliefs; no claim of inner experience",
    }
