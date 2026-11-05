"""Turn one plain-language command into a production plan.

The heuristic parser always works (no API key needed) so the pipeline is never
dead. When a model key is configured, the same command is upgraded into a real
script with bespoke narration beats.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .timeline import MAX_DURATION_SECONDS, normalise_aspect

DEFAULT_DURATION = 60.0
FILLER = {
    "banao", "bana", "banado", "bana", "do", "de", "dedo", "dijiye", "karo", "kar",
    "create", "make", "generate", "build", "produce", "please", "pls", "kindly",
    "mujhe", "muje", "ek", "aik", "eik", "mera", "meri", "main", "mein",
    "chahiye", "chahta", "chahti", "hoon", "hu", "video", "videos", "reel", "reels",
    "short", "shorts", "clip", "film", "movie", "a", "an", "the", "for", "about",
    "on", "of", "par", "pe", "ke", "ka", "ki", "se", "aur", "and", "with",
    "full", "complete", "long", "unlimited", "ka", "wala", "wali",
}

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "secondon": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "minut": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "ghanta": 3600, "ghante": 3600, "ghanton": 3600,
}

_DURATION_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(seconds?|secondon|secs?|s|minutes?|minut|mins?|m|hours?|hrs?|h|ghanta|ghante|ghanton)\b",
    re.IGNORECASE,
)

_ASPECT_HINTS = {
    "9:16": ("short", "shorts", "reel", "reels", "vertical", "portrait", "tiktok", "phone"),
    "1:1": ("square", "1:1", "instagram feed"),
    "4:5": ("4:5",),
}


def parse_duration(command: str) -> tuple[float | None, str | None]:
    """Return (seconds, matched_text) for the first duration in the command."""
    match = _DURATION_RE.search(command)
    if not match:
        return None, None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower().rstrip(".")
    multiplier = _UNIT_SECONDS.get(unit)
    if multiplier is None:
        return None, match.group(0)
    return value * multiplier, match.group(0)


def detect_aspect(command: str) -> str:
    lowered = command.lower()
    for ratio, hints in _ASPECT_HINTS.items():
        if any(hint in lowered for hint in hints):
            return ratio
    return "16:9"


def detect_language(command: str) -> str:
    lowered = command.lower()
    if "roman urdu" in lowered or "hinglish" in lowered:
        return "roman-urdu"
    if re.search(r"[\u0600-\u06ff]", command):
        return "ur"
    if re.search(r"[\u0900-\u097f]", command):
        return "hi"
    for token, code in (("urdu", "ur"), ("hindi", "hi"), ("english", "en"), ("arabic", "ar")):
        if token in lowered:
            return code
    return "en"


def extract_topic(command: str, matched: str | None = None) -> str:
    text = command
    if matched:
        text = text.replace(matched, " ")
    text = _DURATION_RE.sub(" ", text)
    words = re.findall(r"[^\s,.;:!?]+", text)
    kept = [w for w in words if w.strip("'\"()").lower() not in FILLER]
    topic = " ".join(kept).strip(" -–—,.")
    return topic or "your idea"


def template_beats(topic: str, language: str = "en") -> list[str]:
    """Structured narration used when no model is configured."""
    if language == "ur":
        return [
            f"Aaj hum baat karenge {topic} ke baare mein.",
            f"Sab se pehle ye samajhna zaroori hai ke {topic} kya hai.",
            f"{topic} ka asal faida tab milta hai jab ise sahi tareeqe se use kiya jaye.",
            "Iske teen main pehlu hain jo har kisi ko jaanna chahiye.",
            "Pehla pehlu hai samajh, doosra hai amal, aur teesra hai musalsal mehnat.",
            f"Log {topic} se isliye door rehte hain kyunke wo shuruaat ka tareeqa nahi jaante.",
            "Shuruaat chhoti rakhein aur har din thoda behtar karein.",
            "Sab se aam ghalti hai intezaar karna. Aaj hi pehla qadam uthayein.",
            f"Yaad rakhiye: {topic} ek safar hai, manzil nahi.",
            "Agar ye video madadgar lagi to share karein aur agla hissa zaroor dekhen.",
        ]
    return [
        f"Today we are going to talk about {topic}.",
        f"First, let us understand what {topic} actually means.",
        f"The real value of {topic} only appears when it is applied properly.",
        "There are three things that matter most here.",
        "The first is understanding, the second is action, and the third is consistency.",
        f"Most people avoid {topic} because they do not know where to begin.",
        "Start small, and improve a little every day.",
        "The most common mistake is waiting for the perfect moment.",
        f"Remember: {topic} is a journey, not a finish line.",
        "If this helped, share it and watch the next part.",
    ]


def template_prompts(topic: str, count: int) -> list[str]:
    styles = [
        "cinematic wide establishing shot", "close-up detail shot", "over-the-shoulder shot",
        "aerial drone shot", "slow dolly-in", "macro texture shot", "documentary b-roll",
        "golden-hour silhouette", "studio product shot", "atmospheric environment shot",
    ]
    return [f"{topic}, {styles[i % len(styles)]}, high detail, 35mm, natural light" for i in range(count)]


def heuristic_plan(command: str) -> dict[str, Any]:
    seconds, matched = parse_duration(command)
    notes: list[str] = []
    if seconds is None:
        seconds = DEFAULT_DURATION
        notes.append(f"No duration found; defaulted to {int(DEFAULT_DURATION)}s.")
    if seconds > MAX_DURATION_SECONDS:
        seconds = float(MAX_DURATION_SECONDS)
        notes.append("Duration clamped to the configured maximum.")

    aspect = detect_aspect(command)
    language = detect_language(command)
    topic = extract_topic(command, matched)
    scene_seconds = 8.0 if seconds >= 180 else (5.0 if aspect == "9:16" else 6.0)
    count = max(1, int(-(-seconds // scene_seconds)))

    beats = template_beats(topic, language)
    notes.append("Narration is templated; configure a model key for a real script.")

    return {
        "title": topic[:80].capitalize(),
        "topic": topic,
        "duration_seconds": seconds,
        "aspect_ratio": aspect,
        "language": language,
        "scene_seconds": scene_seconds,
        "captions": True,
        "beats": beats,
        "visual_prompts": template_prompts(topic, count),
        "source": "heuristic",
        "notes": notes,
    }


PLAN_SYSTEM_PROMPT = (
    "You are a video producer. Convert the user's command into a strict JSON object with "
    "keys: title (string), topic (string), duration_seconds (number), aspect_ratio "
    "(one of 16:9, 9:16, 1:1, 4:5), language (BCP-47-ish code), scene_seconds (number 2-30), "
    "captions (boolean), beats (array of narration sentences in the requested language), "
    "visual_prompts (array of English image-generation prompts). "
    "Return ONLY the JSON object, no prose, no markdown fences. Never invent facts about "
    "real people or claim unverified statistics."
)


def _coerce_plan(data: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Accept model output only where it is valid; fall back field by field."""
    plan = dict(fallback)
    plan["source"] = "model"
    plan["notes"] = ["Narration written by the configured model."]

    if isinstance(data.get("title"), str) and data["title"].strip():
        plan["title"] = data["title"].strip()[:120]
    if isinstance(data.get("topic"), str) and data["topic"].strip():
        plan["topic"] = data["topic"].strip()[:200]
    for key in ("duration_seconds", "scene_seconds"):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            plan[key] = float(value)
    if isinstance(data.get("aspect_ratio"), str):
        plan["aspect_ratio"] = normalise_aspect(data["aspect_ratio"])
    if isinstance(data.get("language"), str) and data["language"].strip():
        plan["language"] = data["language"].strip()[:12]
    if isinstance(data.get("captions"), bool):
        plan["captions"] = data["captions"]
    for key in ("beats", "visual_prompts"):
        value = data.get(key)
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            plan[key] = [item.strip() for item in value if item.strip()]
    plan["duration_seconds"] = min(float(plan["duration_seconds"]), float(MAX_DURATION_SECONDS))
    return plan


def model_plan(command: str, call_model: Callable[[str, str], str]) -> dict[str, Any]:
    """Upgrade a command using an LLM; raise if the model output is unusable."""
    raw = call_model(PLAN_SYSTEM_PROMPT, command)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("model did not return a JSON object")
    return _coerce_plan(data, heuristic_plan(command))


def plan(command: str, call_model: Callable[[str, str], str] | None = None) -> dict[str, Any]:
    """Plan a command, preferring the model and degrading gracefully."""
    if not command or not command.strip():
        raise ValueError("command must not be empty")
    if call_model is not None:
        try:
            return model_plan(command, call_model)
        except Exception as exc:  # keep the pipeline alive on any model failure
            fallback = heuristic_plan(command)
            fallback["notes"].append(f"Model planning failed ({type(exc).__name__}); used the built-in planner.")
            return fallback
    return heuristic_plan(command)
