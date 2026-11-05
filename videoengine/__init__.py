"""Long-form video production engine: plan -> timeline -> ffmpeg assembly."""

from .timeline import (
    MAX_DURATION_SECONDS,
    MAX_SCENES,
    RESOLUTION_PRESETS,
    Scene,
    Timeline,
    build_timeline,
    chunk_ranges,
    normalise_aspect,
    resolution_for,
    to_srt,
)
from .planner import heuristic_plan, plan

__all__ = [
    "MAX_DURATION_SECONDS", "MAX_SCENES", "RESOLUTION_PRESETS", "Scene", "Timeline",
    "build_timeline", "chunk_ranges", "normalise_aspect", "resolution_for", "to_srt",
    "heuristic_plan", "plan",
]
