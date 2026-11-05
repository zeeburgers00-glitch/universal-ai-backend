"""HTTP routes for the local FFmpeg toolkit (`/v1/video/*`).

No key from any provider is involved: these run FFmpeg on files that already exist.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import require_api_key
from . import video_tools
from .video_tools import VideoToolError

router = APIRouter(prefix="/v1/video", tags=["video-tools"], dependencies=[Depends(require_api_key)])


class MediaRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000, description="Repo-relative or UAI_DATA_ROOT path")


class SilenceRequest(MediaRequest):
    threshold_db: float = Field(default=-30.0, ge=-80.0, le=-5.0)
    min_silence: float = Field(default=0.6, ge=0.1, le=10.0)


class ChapterRequest(SilenceRequest):
    min_chapter: float = Field(default=25.0, ge=5.0, le=600.0)


class ThumbnailRequest(MediaRequest):
    count: int = Field(default=5, ge=1, le=20)
    width: int = Field(default=1280, ge=320, le=3840)


class LoudnessRequest(MediaRequest):
    target_lufs: float = Field(default=-14.0, ge=-30.0, le=-5.0)


class ClipRequest(MediaRequest):
    start: float = Field(ge=0.0, le=86_400.0)
    end: float = Field(gt=0.0, le=86_400.0)
    aspect: Literal["9:16", "1:1", "4:5", "16:9"] = "9:16"


class SubtitleRequest(MediaRequest):
    to: Literal["srt", "vtt"] = "vtt"


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, VideoToolError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.post("/probe")
def video_probe(request: MediaRequest) -> dict[str, Any]:
    """Duration, resolution, fps, streams and size."""

    try:
        return video_tools.probe_media(video_tools.resolve_input(request.path))
    except Exception as exc:
        raise _fail(exc)


@router.post("/cut-silence")
def video_cut_silence(request: SilenceRequest) -> dict[str, Any]:
    """Remove dead air (silencedetect + concat). Returns before/after durations."""

    try:
        return video_tools.cut_silence(request.path, request.threshold_db, request.min_silence)
    except Exception as exc:
        raise _fail(exc)


@router.post("/chapters")
def video_chapters(request: ChapterRequest) -> dict[str, Any]:
    """Chapters from natural pauses, plus a ready-to-paste description block."""

    try:
        return video_tools.chapters(
            request.path, request.threshold_db, request.min_silence, request.min_chapter,
        )
    except Exception as exc:
        raise _fail(exc)


@router.post("/thumbnails")
def video_thumbnails(request: ThumbnailRequest) -> dict[str, Any]:
    """Evenly spaced frames — a cheap thumbnail A/B set."""

    try:
        return video_tools.thumbnails(request.path, request.count, request.width)
    except Exception as exc:
        raise _fail(exc)


@router.post("/loudnorm")
def video_loudnorm(request: LoudnessRequest) -> dict[str, Any]:
    """EBU R128 loudness normalisation (default -14 LUFS)."""

    try:
        return video_tools.loudnorm(request.path, request.target_lufs)
    except Exception as exc:
        raise _fail(exc)


@router.post("/clip")
def video_clip(request: ClipRequest) -> dict[str, Any]:
    """Cut a segment and centre-crop it to a phone aspect ratio."""

    try:
        return video_tools.vertical_clip(request.path, request.start, request.end, request.aspect)
    except Exception as exc:
        raise _fail(exc)


@router.post("/subtitles")
def video_subtitles(request: SubtitleRequest) -> dict[str, Any]:
    """Convert SRT <-> VTT locally."""

    try:
        return video_tools.convert_subtitles(request.path, request.to)
    except Exception as exc:
        raise _fail(exc)
