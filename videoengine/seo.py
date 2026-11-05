"""Viral-SEO packaging for a finished (or planned) video.

Works with no model: the fallback produces real titles, hashtags, chapters and a
description from the plan itself. With a model it writes platform-native copy.

Nothing here invents statistics or fake claims — the prompts forbid it, and the
fallback templates only use the topic and the video's own structure.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .timeline import Timeline

SEO_SYSTEM_PROMPT = (
    "You are a YouTube/Shorts growth strategist. From the video plan, return ONLY strict JSON "
    "with keys: titles (5 clickable titles under 70 chars, no clickbait lies), hook (one sentence "
    "spoken in the first 3 seconds), description (2 short paragraphs plus 5 hashtags), "
    "hashtags (15 lowercase tags without #), keywords (10 search phrases), "
    "thumbnail_text (3 short phrases of at most 4 words). "
    "Never invent statistics, awards, or claims about real people. Match the plan's language."
)


def _slug_words(topic: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[A-Za-z0-9']+", topic.lower())
    return words[:limit]


def _chapters(timeline: Timeline) -> list[dict[str, Any]]:
    """Roughly one chapter every 90 seconds, starting at 0:00."""
    chapters: list[dict[str, Any]] = []
    next_at = 0.0
    for scene in timeline.scenes:
        if scene.start + 1e-6 >= next_at:
            label = (scene.narration.split(".")[0].strip() or f"Part {len(chapters) + 1}")
            chapters.append({
                "start": round(scene.start, 3),
                "timestamp": _mmss(scene.start),
                "title": label[:60],
            })
            next_at = scene.start + 90
    if not chapters:
        chapters.append({"start": 0.0, "timestamp": "0:00", "title": "Intro"})
    return chapters


def _mmss(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def fallback_pack(plan: dict[str, Any], timeline: Timeline) -> dict[str, Any]:
    topic = str(plan.get("topic") or timeline.title).strip()
    pretty = topic[:1].upper() + topic[1:] if topic else "This topic"
    words = _slug_words(topic)
    tag_base = ["".join(w for w in words if w.isalnum())][:1]
    hashtags = [w for w in words if len(w) > 3]
    for extra in ("tutorial", "explained", "2026", "guide", "tips", "howto",
                  "learn", "video", "shorts", "viral", "trending", "ai", "creator", "education"):
        if extra not in hashtags:
            hashtags.append(extra)
    hashtags = hashtags[:15]
    keywords = [topic, f"{topic} explained", f"{topic} tutorial", f"how to {topic}",
                f"{topic} for beginners", f"{topic} tips", f"best {topic}",
                f"{topic} 2026", f"{topic} guide", f"learn {topic}"]

    chapters = _chapters(timeline)
    chapter_block = "\n".join(f"{c['timestamp']} {c['title']}" for c in chapters)
    hashtag_block = " ".join(f"#{tag.replace(' ', '')}" for tag in hashtags[:5])

    return {
        "title": timeline.title,
        "titles": [
            f"{pretty} — Everything You Need To Know",
            f"{pretty}: A Complete Beginner's Guide",
            f"How {pretty} Actually Works",
            f"5 Things Nobody Tells You About {pretty}",
            f"{pretty} Explained In {int(round(timeline.duration / 60)) or 1} Minutes",
        ],
        "hook": f"Most people get {pretty} wrong from the very first step — here is what actually works.",
        "description": (
            f"{pretty}, explained clearly and without filler.\n\n"
            f"This video walks through the essentials step by step so you can start today.\n\n"
            f"{hashtag_block}"
        ),
        "hashtags": hashtags,
        "keywords": keywords,
        "thumbnail_text": [pretty[:28], "Start Here", "The Real Method"],
        "chapters": chapters,
        "chapter_block": chapter_block,
        "duration": timeline.duration,
        "source": "template",
        "tag_base": tag_base,
    }


def _coerce(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    out = dict(fallback)
    out["source"] = "model"
    for key in ("titles", "hashtags", "keywords", "thumbnail_text"):
        value = payload.get(key)
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            out[key] = [item.strip() for item in value if item.strip()]
    for key in ("hook", "description", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    out["chapters"] = fallback["chapters"]
    out["chapter_block"] = fallback["chapter_block"]
    out["duration"] = fallback["duration"]
    return out


def seo_pack(
    plan: dict[str, Any],
    timeline: Timeline,
    call_model: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Package the video for discovery, degrading to templates on any failure."""
    baseline = fallback_pack(plan, timeline)
    if call_model is None:
        return baseline

    prompt = (
        f"Topic: {plan.get('topic')}\nTitle: {timeline.title}\n"
        f"Language: {plan.get('language')}\nDuration: {timeline.duration:.0f} seconds\n"
        f"Aspect ratio: {timeline.aspect_ratio}\n"
        f"Narration beats:\n" + "\n".join(f"- {beat}" for beat in plan.get("beats", [])[:12])
    )
    try:
        raw = call_model(SEO_SYSTEM_PROMPT, prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            newline = cleaned.find("\n")
            cleaned = cleaned[newline + 1:] if newline != -1 else cleaned.lstrip("`")
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3]
        import json

        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("SEO payload was not an object")
        return _coerce(payload, baseline)
    except Exception as exc:
        baseline["source"] = f"template (model failed: {type(exc).__name__})"
        return baseline
