"""Long-form video assembly: timeline maths, no I/O, no web framework.

A production plan is turned into a Timeline (scenes with absolute offsets),
which is then rendered scene by scene and concatenated. Because scenes are
independent and bounded, total length is limited only by disk and time -- a
three-hour video is just 1,350 eight-second scenes.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}

# Guardrails, not ambitions. Raise them with env vars if you really need to.
MAX_DURATION_SECONDS = int(os.getenv("COMMAND_MAX_DURATION_SECONDS", str(12 * 3600)))
MAX_SCENES = int(os.getenv("COMMAND_MAX_SCENES", "5400"))
MIN_SCENE_SECONDS = 2.0
MAX_SCENE_SECONDS = 60.0

ASPECT_ALIASES = {
    "16:9": "16:9", "landscape": "16:9", "wide": "16:9", "horizontal": "16:9",
    "9:16": "9:16", "vertical": "9:16", "portrait": "9:16", "short": "9:16",
    "shorts": "9:16", "reel": "9:16", "reels": "9:16", "tiktok": "9:16",
    "1:1": "1:1", "square": "1:1",
    "4:5": "4:5",
}


def normalise_aspect(value: str | None) -> str:
    if not value:
        return "16:9"
    return ASPECT_ALIASES.get(value.strip().lower(), "16:9")


def resolution_for(aspect_ratio: str) -> tuple[int, int]:
    return RESOLUTION_PRESETS[normalise_aspect(aspect_ratio)]


@dataclass(slots=True)
class Scene:
    index: int
    start: float
    duration: float
    narration: str = ""
    visual_prompt: str = ""
    transition: str = "cut"

    @property
    def end(self) -> float:
        return self.start + self.duration

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "narration": self.narration,
            "visual_prompt": self.visual_prompt,
            "transition": self.transition,
        }


@dataclass(slots=True)
class Timeline:
    title: str
    aspect_ratio: str
    width: int
    height: int
    fps: int
    scenes: list[Scene] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return round(sum(scene.duration for scene in self.scenes), 3)

    @property
    def frame_count(self) -> int:
        return int(round(self.duration * self.fps))

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "aspect_ratio": self.aspect_ratio,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.duration,
            "scene_count": len(self.scenes),
            "metadata": self.metadata,
            "scenes": [scene.to_dict() for scene in self.scenes],
        }


def _split_beats(beats: Iterable[str], count: int) -> list[str]:
    """Spread the supplied narration beats across `count` scenes."""
    items = [str(beat).strip() for beat in beats if str(beat).strip()]
    if not items:
        return [""] * count
    if len(items) >= count:
        # Merge the tail so nothing is dropped from the narration.
        if len(items) == count:
            return items
        head = items[: count - 1]
        head.append(" ".join(items[count - 1:]))
        return head
    # Repeat round-robin only after every beat has been used once.
    out = list(items)
    while len(out) < count:
        out.append(items[len(out) % len(items)])
    return out


def build_timeline(
    *,
    title: str,
    duration_seconds: float,
    aspect_ratio: str = "16:9",
    scene_seconds: float = 8.0,
    beats: Iterable[str] = (),
    visual_prompts: Iterable[str] = (),
    fps: int = 30,
    metadata: dict[str, Any] | None = None,
) -> Timeline:
    """Turn a duration into evenly spaced scenes with absolute offsets."""
    if not title.strip():
        raise ValueError("title must not be empty")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if duration_seconds > MAX_DURATION_SECONDS:
        raise ValueError(
            f"duration_seconds exceeds the configured maximum of {MAX_DURATION_SECONDS}s "
            "(set COMMAND_MAX_DURATION_SECONDS to raise it)"
        )
    if fps not in (24, 25, 30, 50, 60):
        raise ValueError("fps must be one of 24, 25, 30, 50, 60")

    scene_seconds = min(max(float(scene_seconds), MIN_SCENE_SECONDS), MAX_SCENE_SECONDS)
    count = max(1, math.ceil(duration_seconds / scene_seconds))
    if count > MAX_SCENES:
        raise ValueError(
            f"{count} scenes exceeds the configured maximum of {MAX_SCENES} "
            "(shorten the video or increase scene_seconds)"
        )

    ratio = normalise_aspect(aspect_ratio)
    width, height = resolution_for(ratio)

    narration = _split_beats(beats, count)
    prompts = _split_beats(visual_prompts, count)

    scenes: list[Scene] = []
    cursor = 0.0
    for index in range(count):
        # Last scene absorbs the rounding remainder so the total is exact.
        length = duration_seconds - cursor if index == count - 1 else scene_seconds
        scenes.append(
            Scene(
                index=index,
                start=round(cursor, 3),
                duration=round(length, 3),
                narration=narration[index],
                visual_prompt=prompts[index] or title,
                transition="fade" if index else "cut",
            )
        )
        cursor += length

    return Timeline(
        title=title.strip(),
        aspect_ratio=ratio,
        width=width,
        height=height,
        fps=fps,
        scenes=scenes,
        metadata={**(metadata or {}), "scene_seconds": scene_seconds},
    )


def _timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def to_srt(timeline: Timeline, *, max_words: int = 7) -> str:
    """Captions derived from narration, split into readable chunks."""
    blocks: list[str] = []
    counter = 1
    for scene in timeline.scenes:
        words = scene.narration.split()
        if not words:
            continue
        chunks = [" ".join(words[i: i + max_words]) for i in range(0, len(words), max_words)]
        span = scene.duration / len(chunks)
        for offset, chunk in enumerate(chunks):
            start = scene.start + offset * span
            end = min(start + span, scene.end)
            blocks.append(
                f"{counter}\n{_timestamp(start)} --> {_timestamp(end)}\n{chunk}\n"
            )
            counter += 1
    return "\n".join(blocks)


def chunk_ranges(timeline: Timeline, chunk_seconds: float = 600.0) -> list[tuple[int, int]]:
    """Split scene indices into batches so rendering can resume after a crash."""
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be positive")
    ranges: list[tuple[int, int]] = []
    start_index = 0
    accumulated = 0.0
    for scene in timeline.scenes:
        if accumulated and accumulated + scene.duration > chunk_seconds:
            ranges.append((start_index, scene.index))
            start_index = scene.index
            accumulated = 0.0
        accumulated += scene.duration
    ranges.append((start_index, len(timeline.scenes)))
    return ranges
