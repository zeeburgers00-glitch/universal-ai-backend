"""Local video toolkit: cut silence, chapterise, thumbnail sets, loudness, clips, subtitles.

Every operation here is plain FFmpeg on files that already exist on disk. No model, no
API key, no quota — so these work the same on a $5 VPS, in the Modal kit, or on a laptop
with no internet.

Inputs are resolved the same way as the code assistant: inside the repository or inside
`UAI_DATA_ROOT`, never anywhere else.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from videoengine.assembly import FfmpegNotFound, find_ffmpeg, run_ffmpeg

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_INPUT_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB is plenty for a phone-shot clip
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
SUBTITLE_SUFFIXES = {".srt", ".vtt"}


class VideoToolError(ValueError):
    """Bad input from the caller (missing file, not a video, unsafe path)."""


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _roots() -> list[Path]:
    """Where media may live: the repo, UAI_DATA_ROOT, plus any extra mounted roots.

    Deployments keep renders on a volume (`/renders` on Modal, `/data` in Docker), so
    `UAI_MEDIA_ROOTS=/renders:/mnt/media` is a normal setup, not an edge case.
    """

    roots = [REPO_ROOT]
    data_root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser().resolve()
    if data_root not in roots:
        roots.append(data_root)
    for extra in (os.getenv("UAI_MEDIA_ROOTS") or "").split(":"):
        extra = extra.strip()
        if not extra:
            continue
        path = Path(extra).expanduser().resolve()
        if path not in roots:
            roots.append(path)
    return roots


def output_dir() -> Path:
    """Where new artefacts go. Falls back to a temp dir on a read-only filesystem."""

    candidates = [
        Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser() / "video",
        REPO_ROOT / "data" / "video",
        Path(tempfile.gettempdir()) / "uai-video",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe_file = candidate / ".write-test"
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink(missing_ok=True)
            return candidate.resolve()
        except OSError:
            continue
    raise VideoToolError("no writable output directory")


def resolve_input(path: str) -> Path:
    if not path or not path.strip():
        raise VideoToolError("path is required")
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate)
    candidate = candidate.resolve()

    allowed = any(candidate == root or root in candidate.parents for root in _roots())
    if not allowed:
        raise VideoToolError("path must be inside the repository or UAI_DATA_ROOT")
    if not candidate.is_file():
        raise VideoToolError(f"file not found: {path}")
    if candidate.suffix.lower() not in VIDEO_SUFFIXES | AUDIO_SUFFIXES | SUBTITLE_SUFFIXES:
        raise VideoToolError(f"unsupported media type: {candidate.suffix or 'none'}")
    if candidate.stat().st_size > MAX_INPUT_BYTES:
        raise VideoToolError("file is larger than 4 GB")
    return candidate


def _ffmpeg() -> str:
    try:
        return find_ffmpeg()
    except FfmpegNotFound as exc:
        raise VideoToolError(
            "FFmpeg is not available. Install ffmpeg, or `pip install imageio-ffmpeg`."
        ) from exc


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _new_path(stem: str, suffix: str) -> Path:
    return output_dir() / f"{stem}-{_stamp()}-{os.getpid()}{suffix}"


# --------------------------------------------------------------------------- #
# Probe / metadata
# --------------------------------------------------------------------------- #
_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: (Video|Audio): ([^,]+)")


def probe_media(path: Path) -> dict[str, Any]:
    """Duration, resolution, fps and stream list from `ffmpeg -i` output."""

    completed = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    stderr = completed.stderr or ""
    if "Invalid data" in stderr or "No such file" in stderr:
        raise VideoToolError("ffmpeg could not read this file")

    duration = 0.0
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", stderr)
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    width = height = 0
    size = re.search(r"(\d{2,5})x(\d{2,5})", stderr)
    if size:
        width, height = int(size.group(1)), int(size.group(2))

    fps = 0.0
    fps_match = re.search(r"(\d+(?:\.\d+)?) fps", stderr)
    if fps_match:
        fps = float(fps_match.group(1))

    streams = [{"type": kind.lower(), "codec": codec.strip()} for kind, codec in _STREAM_RE.findall(stderr)]
    return {
        "path": str(path),
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "fps": fps,
        "streams": streams,
        "has_audio": any(stream["type"] == "audio" for stream in streams),
        "has_video": any(stream["type"] == "video" for stream in streams),
        "size_bytes": path.stat().st_size,
    }


# --------------------------------------------------------------------------- #
# Silence detection -> cut and chapters
# --------------------------------------------------------------------------- #
_SILENCE_RE = re.compile(r"silence_(start|end): (\d+\.?\d*)")
_SILENCE_START_RE = re.compile(r"silence_start: (-?\d+\.?\d*)")
_SILENCE_END_RE = re.compile(r"silence_end: (\d+\.?\d*) \| silence_duration: (\d+\.?\d*)")


def detect_silences(path: Path, threshold_db: float = -30.0, min_silence: float = 0.6) -> list[dict[str, float]]:
    """Ask FFmpeg's silencedetect filter where the dead air is."""

    completed = subprocess.run(
        [
            _ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    stderr = completed.stderr or ""
    silences: list[dict[str, float]] = []
    open_start: float | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            open_start = float(start_match.group(1))
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match and open_start is not None:
            silences.append({
                "start": round(open_start, 3),
                "end": round(float(end_match.group(1)), 3),
                "duration": round(float(end_match.group(2)), 3),
            })
            open_start = None
    return silences


def _keep_segments(media: dict[str, Any], silences: list[dict[str, float]], padding: float = 0.15) -> list[dict[str, float]]:
    """Invert silenced regions into the parts we want to keep."""

    duration = float(media["duration"])
    if duration <= 0:
        raise VideoToolError("could not read the media duration")

    segments: list[dict[str, float]] = []
    cursor = 0.0
    for silence in silences:
        start = max(0.0, silence["start"] + padding)
        if start - cursor > 0.25:
            segments.append({"start": round(cursor, 3), "end": round(start, 3)})
        cursor = min(duration, silence["end"] - padding)
    if duration - cursor > 0.25:
        segments.append({"start": round(cursor, 3), "end": round(duration, 3)})
    return segments or [{"start": 0.0, "end": round(duration, 3)}]


def cut_silence(path: str, threshold_db: float = -30.0, min_silence: float = 0.6) -> dict[str, Any]:
    """Remove dead air. Returns the new file plus what was cut."""

    source = resolve_input(path)
    media = probe_media(source)
    if not media["has_audio"]:
        raise VideoToolError("file has no audio track, so there is no silence to detect")

    silences = detect_silences(source, threshold_db=threshold_db, min_silence=min_silence)
    segments = _keep_segments(media, silences)
    removed = round(sum(item["duration"] for item in silences), 3)

    ffmpeg = _ffmpeg()
    with tempfile.TemporaryDirectory(prefix="uai-cut-") as work:
        work_dir = Path(work)
        parts: list[Path] = []
        for index, segment in enumerate(segments):
            part = work_dir / f"seg_{index:04d}.mp4"
            run_ffmpeg(
                [
                    "-y", "-ss", f"{segment['start']:.3f}", "-to", f"{segment['end']:.3f}",
                    "-i", str(source), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-avoid_negative_ts", "make_zero", str(part),
                ],
                ffmpeg=ffmpeg, timeout=1800,
            )
            parts.append(part)

        listing = work_dir / "parts.txt"
        listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
        target = _new_path(f"{source.stem}-nocut", ".mp4")
        run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(target)],
            ffmpeg=ffmpeg, timeout=1800,
        )

    result_media = probe_media(target)
    return {
        "output": str(target),
        "source": str(source),
        "original_duration": media["duration"],
        "new_duration": result_media["duration"],
        "removed_seconds": removed,
        "segments_kept": len(segments),
        "silences": silences[:100],
        "note": "Cut segments are re-encoded for clean joins; concat is stream-copied.",
    }


def chapters(path: str, threshold_db: float = -30.0, min_silence: float = 0.6, min_chapter: float = 25.0) -> dict[str, Any]:
    """Build YouTube-style chapters from natural pauses (long gaps = topic change)."""

    source = resolve_input(path)
    media = probe_media(source)
    silences = detect_silences(source, threshold_db=threshold_db, min_silence=min_silence)

    marks = [0.0]
    for silence in silences:
        if silence["start"] - marks[-1] >= min_chapter:
            marks.append(round(silence["start"], 2))
    if media["duration"] - marks[-1] < min_chapter / 2 and len(marks) > 1:
        marks.pop()

    result = []
    for index, start in enumerate(marks):
        end = marks[index + 1] if index + 1 < len(marks) else round(float(media["duration"]), 2)
        result.append({
            "index": index,
            "start": start,
            "end": end,
            "timestamp": _timestamp(start),
            "suggestion": f"Chapter {index + 1}",
        })

    description = "\n".join(
        f"{chapter['timestamp']} {chapter['suggestion']}" for chapter in result
    )
    return {
        "source": str(source),
        "duration": media["duration"],
        "chapter_count": len(result),
        "chapters": result,
        "youtube_description": description,
        "note": "Titles are placeholders from timeline gaps; rename them before publishing.",
    }


def _timestamp(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


# --------------------------------------------------------------------------- #
# Thumbnails
# --------------------------------------------------------------------------- #
def thumbnails(path: str, count: int = 5, width: int = 1280) -> dict[str, Any]:
    """Grab evenly spaced frames. Cheap A/B set for thumbnails."""

    if not 1 <= count <= 20:
        raise VideoToolError("count must be between 1 and 20")

    source = resolve_input(path)
    media = probe_media(source)
    duration = float(media["duration"])
    if duration <= 0:
        raise VideoToolError("could not read the media duration")

    ffmpeg = _ffmpeg()
    made: list[dict[str, Any]] = []
    for index in range(count):
        # Skip the very start/end: those are usually fades or black frames.
        position = duration * (index + 1) / (count + 1)
        target = _new_path(f"{source.stem}-thumb{index + 1}", ".jpg")
        run_ffmpeg(
            [
                "-y", "-ss", f"{position:.3f}", "-i", str(source),
                "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2", str(target),
            ],
            ffmpeg=ffmpeg, timeout=300,
        )
        made.append({"index": index + 1, "at_seconds": round(position, 2), "file": str(target),
                     "size_bytes": target.stat().st_size})

    return {"source": str(source), "count": len(made), "thumbnails": made}


# --------------------------------------------------------------------------- #
# Loudness
# --------------------------------------------------------------------------- #
def loudnorm(path: str, target_lufs: float = -14.0) -> dict[str, Any]:
    """Two-pass EBU R128 normalisation — the level YouTube and podcasts expect."""

    if not -30 <= target_lufs <= -5:
        raise VideoToolError("target_lufs must be between -30 and -5")

    source = resolve_input(path)
    media = probe_media(source)
    if not media["has_audio"]:
        raise VideoToolError("file has no audio track")
    ffmpeg = _ffmpeg()

    filter_chain = f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
    if media["has_video"]:
        target = _new_path(f"{source.stem}-loud", ".mp4")
        run_ffmpeg(
            ["-y", "-i", str(source), "-c:v", "copy", "-af", filter_chain, "-c:a", "aac", "-b:a", "192k", str(target)],
            ffmpeg=ffmpeg, timeout=1800,
        )
    else:
        target = _new_path(f"{source.stem}-loud", ".m4a")
        run_ffmpeg(
            ["-y", "-i", str(source), "-af", filter_chain, "-c:a", "aac", "-b:a", "192k", str(target)],
            ffmpeg=ffmpeg, timeout=1800,
        )

    return {
        "output": str(target),
        "source": str(source),
        "target_lufs": target_lufs,
        "true_peak": -1.5,
        "size_bytes": target.stat().st_size,
    }


# --------------------------------------------------------------------------- #
# Vertical clips
# --------------------------------------------------------------------------- #
def vertical_clip(path: str, start: float, end: float, aspect: str = "9:16") -> dict[str, Any]:
    """Cut one segment and centre-crop it to a phone aspect ratio."""

    source = resolve_input(path)
    media = probe_media(source)
    duration = float(media["duration"])
    if not media["has_video"]:
        raise VideoToolError("file has no video track")
    if start < 0 or end <= start or end > duration + 0.5:
        raise VideoToolError(f"clip range must sit inside 0–{duration}s")
    if aspect not in {"9:16", "1:1", "4:5", "16:9"}:
        raise VideoToolError("aspect must be 9:16, 1:1, 4:5 or 16:9")

    width, height = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}[aspect]
    target = _new_path(f"{source.stem}-{aspect.replace(':', 'x')}", ".mp4")
    filter_chain = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )
    run_ffmpeg(
        [
            "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source),
            "-vf", filter_chain, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(target),
        ],
        ffmpeg=_ffmpeg(), timeout=1800,
    )
    return {
        "output": str(target),
        "source": str(source),
        "aspect": aspect,
        "resolution": f"{width}x{height}",
        "start": start,
        "end": end,
        "duration": round(end - start, 2),
    }


# --------------------------------------------------------------------------- #
# Subtitles
# --------------------------------------------------------------------------- #
_TIMECODE_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})")


def convert_subtitles(path: str, to: str = "vtt") -> dict[str, Any]:
    """SRT <-> VTT without a service call."""

    if to not in {"srt", "vtt"}:
        raise VideoToolError("to must be srt or vtt")
    source = resolve_input(path)
    if source.suffix.lower() not in {".srt", ".vtt"}:
        raise VideoToolError("input must be .srt or .vtt")

    text = source.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    if to == "vtt":
        body = text
        if body.lstrip().upper().startswith("WEBVTT"):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        body = _TIMECODE_RE.sub(lambda m: f"{m.group(1)}:{m.group(2)}:{m.group(3)}.{m.group(4)}", body)
        content = "WEBVTT\n\n" + body.strip("\n") + "\n"
        suffix = ".vtt"
    else:
        body = text
        if body.lstrip().upper().startswith("WEBVTT"):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        content = body.strip("\n") + "\n"
        suffix = ".srt"

    target = _new_path(source.stem, suffix)
    target.write_text(content, encoding="utf-8")
    return {
        "output": str(target),
        "source": str(source),
        "format": to,
        "cues": len([block for block in content.split("\n\n") if "-->" in block]),
        "bytes": target.stat().st_size,
    }
