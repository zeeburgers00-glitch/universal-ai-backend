"""Executors behind the skill catalogue.

Each function here is a *real* operation: ffmpeg runs, ImageMagick runs, stdlib parsing, a
provider call. Skills that would need something absent (pandoc, LibreOffice, a GPU model)
have no runner and answer ``unavailable: ...`` instead of pretending.

Conventions
-----------
* take ``args: dict``, return a JSON-able dict
* raise ``SkillInputError`` for bad user input (422)
* raise ``SkillUnavailable`` for a missing dependency (503)
* never write outside the repo or ``UAI_DATA_ROOT``
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from videoengine.assembly import FfmpegNotFound, find_ffmpeg, run_ffmpeg

from . import video_tools


class SkillInputError(ValueError):
    """The caller's arguments do not make sense."""


class SkillUnavailable(RuntimeError):
    """A dependency or credential is genuinely missing."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _need(args: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if args.get(key) in (None, "")]
    if missing:
        raise SkillInputError(f"missing argument(s): {', '.join(missing)}")


def _input_path(value: str) -> Path:
    try:
        return video_tools.resolve_input(str(value))
    except video_tools.VideoToolError as exc:
        raise SkillInputError(str(exc)) from exc


def _fs_path(value: str) -> Path:
    """Any existing file (code, text, config).

    Relative names are tried against CWD, then the repo, then UAI_DATA_ROOT — the same
    order a person means when they say "photo.png".
    """

    raw = str(value)
    if not raw.strip():
        raise SkillInputError("path is required")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        attempts = [candidate]
    else:
        roots = [Path.cwd(), Path(video_tools.REPO_ROOT), *video_tools._roots()]
        attempts = [root / candidate for root in roots]
        attempts.append(candidate)
    for attempt in attempts:
        if attempt.is_file():
            return attempt.resolve()
    if candidate.exists() and not candidate.is_file():
        raise SkillInputError(f"not a file: {value}")
    raise SkillInputError(f"file not found: {value}")


def _output(stem: str, suffix: str) -> Path:
    directory = video_tools.output_dir()
    safe = re.sub(r"[^\w.-]+", "_", stem)[:60] or "out"
    return directory / f"{safe}-{time.strftime('%H%M%S')}{suffix}"


def _ff() -> str:
    try:
        return find_ffmpeg()
    except FfmpegNotFound as exc:
        raise SkillUnavailable("unavailable: ffmpeg — pip install imageio-ffmpeg") from exc


def _run_ff(args: list[str], *, timeout: int = 1800) -> None:
    try:
        run_ffmpeg(args, ffmpeg=_ff(), timeout=timeout)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - message shape varies
        raise SkillInputError(f"ffmpeg failed: {(exc.stderr or '')[-300:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SkillInputError(f"ffmpeg timed out after {exc.timeout}s") from exc


def _imagemagick() -> str:
    binary = shutil.which("convert") or shutil.which("magick")
    if not binary:
        raise SkillUnavailable("unavailable: apt-get install imagemagick")
    return binary


def _magick(source: Path, out: Path, operations: list[str]) -> dict[str, Any]:
    completed = subprocess.run([_imagemagick(), str(source), *operations, str(out)],
                               capture_output=True, text=True, timeout=300, check=False)
    if completed.returncode != 0:
        raise SkillInputError(f"imagemagick failed: {(completed.stderr or '').strip()[:300]}")
    return {"output": str(out), "size_bytes": out.stat().st_size}


def _text_of(args: dict[str, Any], key: str = "text") -> str:
    """Inline text wins; otherwise read a small file from the allowed roots."""

    if args.get(key):
        return str(args[key])
    if args.get("path"):
        path = _fs_path(str(args["path"]))
        if path.stat().st_size > 8 * 1024 * 1024:
            raise SkillInputError("file is larger than 8 MB — pass inline text instead")
        return path.read_text(encoding="utf-8", errors="replace")
    raise SkillInputError("provide 'text' or 'path'")


def _records(args: dict[str, Any], fmt: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a table from csv/tsv/json/jsonl into rows + fieldnames."""

    fmt = (fmt or args.get("format") or "").lower()
    if args.get("data"):
        raw = args["data"]
    elif args.get("path"):
        path = _fs_path(str(args["path"]))
        raw = path.read_text(encoding="utf-8", errors="replace")
        if not fmt:
            fmt = path.suffix.lstrip(".").lower()
    else:
        raise SkillInputError("provide 'path' or 'data'")

    if fmt in {"json", ""} and raw.strip().startswith(("{", "[")):
        parsed = json.loads(raw)
        rows = parsed if isinstance(parsed, list) else [parsed]
        rows = [row for row in rows if isinstance(row, dict)]
        fields = list(dict.fromkeys(key for row in rows for key in row))
        return rows, fields
    if fmt == "jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        fields = list(dict.fromkeys(key for row in rows for key in row))
        return rows, fields

    delimiter = "\t" if fmt == "tsv" else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
    rows = list(reader)
    return rows, list(reader.fieldnames or [])


def _write_rows(rows: list[dict[str, Any]], fields: list[str], fmt: str,
                args: dict[str, Any]) -> tuple[str, int]:
    if args.get("out"):
        out = Path(str(args["out"]))
    else:
        out = _output("table", "." + {"jsonl": "jsonl", "json": "json", "tsv": "tsv",
                                      "sqlite": "sqlite"}.get(fmt, "csv"))

    if fmt == "sqlite":
        import sqlite3

        if out.exists():
            out.unlink()
        connection = sqlite3.connect(str(out))
        try:
            columns = ", ".join(f'"{field}" TEXT' for field in fields) or '"value" TEXT'
            connection.execute("CREATE TABLE data (%s)" % columns)
            if rows and fields:
                placeholders = ", ".join("?" for _ in fields)
                connection.executemany(
                    f"INSERT INTO data VALUES ({placeholders})",
                    [[str(row.get(field, "")) for field in fields] for row in rows])
            connection.commit()
        finally:
            connection.close()
        return str(out), out.stat().st_size
    if fmt == "json":
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    elif fmt == "jsonl":
        out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                       encoding="utf-8")
    else:
        delimiter = "\t" if fmt == "tsv" else ","
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=delimiter,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        out.write_text(buffer.getvalue(), encoding="utf-8")
    return str(out), out.stat().st_size


# --------------------------------------------------------------------------- #
# Video / audio
# --------------------------------------------------------------------------- #

VIDEO_CODEC_ARGS = {
    "h264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"],
    "h265": ["-c:v", "libx265", "-preset", "veryfast", "-crf", "28"],
    "vp9": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0"],
    "av1": ["-c:v", "libaom-av1", "-crf", "34", "-b:v", "0"],
}

RESOLUTIONS = {
    "1080p": "scale=-2:1080",
    "720p": "scale=-2:720",
    "480p": "scale=-2:480",
    "360p": "scale=-2:360",
    "vertical-1080x1920": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
    "square-1080": "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2",
    "feed-1080x1350": "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2",
}

PLATFORM_PRESETS = {
    "youtube-1080p": {"vf": "scale=-2:1080", "extra": ["-c:v", "libx264", "-crf", "21", "-c:a", "aac", "-b:a", "192k"], "suffix": ".mp4"},
    "youtube-720p": {"vf": "scale=-2:720", "extra": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac", "-b:a", "160k"], "suffix": ".mp4"},
    "shorts-1080x1920": {"vf": RESOLUTIONS["vertical-1080x1920"], "extra": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac"], "suffix": ".mp4"},
    "reels-1080x1920": {"vf": RESOLUTIONS["vertical-1080x1920"], "extra": ["-c:v", "libx264", "-crf", "24", "-c:a", "aac"], "suffix": ".mp4"},
    "tiktok-1080x1920": {"vf": RESOLUTIONS["vertical-1080x1920"], "extra": ["-c:v", "libx264", "-crf", "24", "-c:a", "aac"], "suffix": ".mp4"},
    "instagram-feed": {"vf": RESOLUTIONS["feed-1080x1350"], "extra": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac"], "suffix": ".mp4"},
    "whatsapp-status": {"vf": "scale=-2:720", "extra": ["-t", "30", "-c:v", "libx264", "-crf", "28", "-c:a", "aac"], "suffix": ".mp4"},
    "linkedin-feed": {"vf": RESOLUTIONS["square-1080"], "extra": ["-c:v", "libx264", "-crf", "24", "-c:a", "aac"], "suffix": ".mp4"},
    "twitter-feed": {"vf": "scale=-2:720", "extra": ["-c:v", "libx264", "-crf", "26", "-c:a", "aac"], "suffix": ".mp4"},
}


AUDIO_CODEC_FOR_CONTAINER = {
    "webm": ["-c:a", "libopus", "-b:a", "128k"],
    "ogg": ["-c:a", "libopus", "-b:a", "128k"],
    "mp4": ["-c:a", "aac", "-b:a", "160k"],
    "m4v": ["-c:a", "aac", "-b:a", "160k"],
    "mov": ["-c:a", "aac", "-b:a", "160k"],
    "mkv": ["-c:a", "aac", "-b:a", "160k"],
    "avi": ["-c:a", "libmp3lame", "-b:a", "192k"],
}


def _audio_args(container: str) -> list[str]:
    return AUDIO_CODEC_FOR_CONTAINER.get(container, ["-c:a", "aac", "-b:a", "160k"])


def run_video_convert(args: dict[str, Any]) -> dict[str, Any]:
    _need_with_source(args)
    source = _input_path(args["path"])
    target = str(args.get("target") or "mp4").lstrip(".").lower()
    codec = str(args.get("codec") or "h264").lower()
    out = Path(args["out"]) if args.get("out") else _output(source.stem, f".{target}")
    codec_args = VIDEO_CODEC_ARGS.get(codec, VIDEO_CODEC_ARGS["h264"])
    _run_ff(["-i", str(source), *codec_args, *_audio_args(target), str(out)])
    return {"output": str(out), "target": target, "codec": codec,
            "size_bytes": out.stat().st_size}


def run_video_resize(args: dict[str, Any]) -> dict[str, Any]:
    _need_with_source(args)
    source = _input_path(args["path"])
    preset = str(args.get("preset") or "720p")
    scale = RESOLUTIONS.get(preset)
    if scale is None:
        raise SkillInputError(f"unknown preset: {preset} (choose {', '.join(RESOLUTIONS)})")
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-{preset}", ".mp4")
    _run_ff(["-i", str(source), "-vf", scale, *VIDEO_CODEC_ARGS["h264"],
             "-c:a", "aac", "-b:a", "160k", str(out)])
    return {"output": str(out), "preset": preset, "size_bytes": out.stat().st_size}


def run_video_platform(args: dict[str, Any]) -> dict[str, Any]:
    _need_with_source(args)
    source = _input_path(args["path"])
    preset = str(args.get("platform") or "youtube-1080p")
    spec = PLATFORM_PRESETS.get(preset)
    if spec is None:
        raise SkillInputError(f"unknown platform preset: {preset} "
                              f"(choose {', '.join(PLATFORM_PRESETS)})")
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-{preset}", spec["suffix"])
    _run_ff(["-i", str(source), "-vf", spec["vf"], *spec["extra"], str(out)])
    return {"output": str(out), "platform": preset, "size_bytes": out.stat().st_size}


def run_video_op(args: dict[str, Any]) -> dict[str, Any]:
    _need_with_source(args)
    op = str(args.get("op") or "mute")
    source = _input_path(args["path"])
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-{op}", ".mp4")

    if op == "mute":
        _run_ff(["-i", str(source), "-an", "-c:v", "copy", str(out)])
    elif op == "speed-0.5":
        _run_ff(["-i", str(source), "-filter_complex",
                 "[0:v]setpts=2.0*PTS[v];[0:a]atempo=0.5[a]", "-map", "[v]", "-map", "[a]", str(out)])
    elif op == "speed-2":
        _run_ff(["-i", str(source), "-filter_complex",
                 "[0:v]setpts=0.5*PTS[v];[0:a]atempo=2.0[a]", "-map", "[v]", "-map", "[a]", str(out)])
    elif op == "reverse":
        _run_ff(["-i", str(source), "-vf", "reverse", "-af", "areverse",
                 "-preset", "veryfast", str(out)])
    elif op in {"rotate-90", "rotate-180", "rotate-270"}:
        transpose = {"rotate-90": "transpose=1", "rotate-180": "transpose=1,transpose=1",
                     "rotate-270": "transpose=2"}[op]
        _run_ff(["-i", str(source), "-vf", transpose, str(out)])
    elif op == "grayscale":
        _run_ff(["-i", str(source), "-vf", "format=gray", str(out)])
    elif op == "flip-horizontal":
        _run_ff(["-i", str(source), "-vf", "hflip", str(out)])
    elif op == "flip-vertical":
        _run_ff(["-i", str(source), "-vf", "vflip", str(out)])
    elif op == "web-optimize":
        _run_ff(["-i", str(source), "-movflags", "+faststart", *VIDEO_CODEC_ARGS["h264"],
                 "-c:a", "aac", str(out)])
    elif op == "strip-metadata":
        _run_ff(["-i", str(source), "-map_metadata", "-1", "-c", "copy", str(out)])
    elif op == "first-frame":
        out = _output(f"{source.stem}-frame", ".png")
        _run_ff(["-i", str(source), "-frames:v", "1", str(out)])
    elif op == "storyboard":
        return video_tools.thumbnails(str(source), count=int(args.get("count") or 9), width=480)
    elif op == "chapters":
        return video_tools.chapters(str(source))
    elif op == "cut-silence":
        return video_tools.cut_silence(str(source))
    elif op == "loudnorm":
        return video_tools.loudnorm(str(source))
    else:
        raise SkillInputError(f"unsupported video op: {op}")
    return {"output": str(out), "op": op, "size_bytes": out.stat().st_size}


def _need_with_source(args: dict[str, Any]) -> None:
    _need(args, "path")


def _require_audio(source: Path) -> None:
    probe = video_tools.probe_media(source) or {}
    streams = probe.get("streams") or []
    if streams and not any(str(stream.get("type")) == "audio" for stream in streams):
        raise SkillInputError(f"no audio track in {source.name} — extract or record audio first")


def run_audio_convert(args: dict[str, Any]) -> dict[str, Any]:
    _need_with_source(args)
    source = _input_path(args["path"])
    _require_audio(source)
    target = str(args.get("target") or "mp3").lstrip(".").lower()
    out = Path(args["out"]) if args.get("out") else _output(source.stem, f".{target}")
    bitrate = str(args.get("bitrate") or "192k")
    _run_ff(["-i", str(source), "-vn", "-b:a", bitrate, str(out)])
    return {"output": str(out), "target": target, "bitrate": bitrate,
            "size_bytes": out.stat().st_size}


def run_audio_op(args: dict[str, Any]) -> dict[str, Any]:
    _need_with_source(args)
    op = str(args.get("op") or "normalize")
    source = _input_path(args["path"])
    _require_audio(source)
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-{op}", ".mp3")

    if op == "normalize":
        _run_ff(["-i", str(source), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", str(out)])
    elif op == "mono":
        _run_ff(["-i", str(source), "-ac", "1", str(out)])
    elif op == "resample-44100":
        _run_ff(["-i", str(source), "-ar", "44100", str(out)])
    elif op == "resample-48000":
        _run_ff(["-i", str(source), "-ar", "48000", str(out)])
    elif op == "fade-in":
        _run_ff(["-i", str(source), "-af", "afade=t=in:st=0:d=2", str(out)])
    elif op == "fade-out":
        _run_ff(["-i", str(source), "-af", "areverse,afade=t=in:st=0:d=2,areverse", str(out)])
    elif op == "trim-silence":
        _run_ff(["-i", str(source), "-af",
                 "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:"
                 "stop_threshold=-45dB:stop_silence=0.6", str(out)])
    elif op == "speed-1.25":
        _run_ff(["-i", str(source), "-af", "atempo=1.25", str(out)])
    elif op == "speed-0.8":
        _run_ff(["-i", str(source), "-af", "atempo=0.8", str(out)])
    elif op == "reverse":
        _run_ff(["-i", str(source), "-af", "areverse", str(out)])
    else:
        raise SkillInputError(f"unsupported audio op: {op}")
    return {"output": str(out), "op": op, "size_bytes": out.stat().st_size}


def _clip_bounds(args: dict[str, Any], source: Path) -> tuple[float, float]:
    _need(args, "path")
    start = float(args.get("start") or 0.0)
    if args.get("end") not in (None, ""):
        end = float(args["end"])
    else:
        duration = float((video_tools.probe_media(source) or {}).get("duration") or 0.0)
        if duration <= 0:
            raise SkillInputError("could not read duration — pass end=<seconds>")
        end = duration
    if end <= start:
        raise SkillInputError("end must be greater than start")
    return start, end


def run_video_gif(args: dict[str, Any]) -> dict[str, Any]:
    source = _input_path(args["path"])
    start, end = _clip_bounds(args, source)
    out = Path(args["out"]) if args.get("out") else _output(source.stem, ".gif")
    width = int(args.get("width") or 480)
    fps = int(args.get("fps") or 12)
    _run_ff(["-ss", str(start), "-to", str(end), "-i", str(source),
             "-vf", f"fps={fps},scale={width}:-1:flags=lanczos", str(out)])
    return {"output": str(out), "width": width, "fps": fps, "size_bytes": out.stat().st_size}


def run_video_trim(args: dict[str, Any]) -> dict[str, Any]:
    source = _input_path(args["path"])
    start, end = _clip_bounds(args, source)
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-clip", source.suffix)
    _run_ff(["-ss", str(start), "-to", str(end), "-i", str(source), "-c", "copy", str(out)])
    return {"output": str(out), "start": start, "end": end, "size_bytes": out.stat().st_size}


def run_media_probe(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "path")
    return {"probe": video_tools.probe_media(_input_path(args["path"]))}


# --------------------------------------------------------------------------- #
# Image
# --------------------------------------------------------------------------- #

IMAGE_FORMATS = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}


def run_image_convert(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "path")
    source = _fs_path(args["path"])
    target = str(args.get("target") or "png").lstrip(".").lower()
    if target not in IMAGE_FORMATS:
        raise SkillInputError(f"unsupported image format: {target}")
    out = Path(args["out"]) if args.get("out") else _output(source.stem, f".{target}")
    quality = int(args.get("quality") or 85)
    return _magick(source, out, ["-strip", "-quality", str(quality)])


def run_image_resize(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "path")
    source = _fs_path(args["path"])
    width = int(args.get("width") or 1280)
    suffix = Path(str(args.get("out") or "")).suffix or source.suffix or ".png"
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-{width}", suffix)
    return _magick(source, out, ["-resize", f"{width}x"])


def run_image_op(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "path")
    op = str(args.get("op") or "grayscale")
    source = _fs_path(args["path"])
    suffix = Path(str(args.get("out") or "")).suffix or source.suffix or ".png"
    out = Path(args["out"]) if args.get("out") else _output(f"{source.stem}-{op}", suffix)

    operations = {
        "grayscale": ["-colorspace", "Gray"],
        "rotate-90": ["-rotate", "90"],
        "rotate-180": ["-rotate", "180"],
        "rotate-270": ["-rotate", "270"],
        "flip-horizontal": ["-flop"],
        "flip-vertical": ["-flip"],
        "crop-square": ["-gravity", "center", "-crop", "1:1"],
        "strip-metadata": ["-strip"],
        "blur": ["-blur", "0x6"],
        "sharpen": ["-sharpen", "0x1"],
        "border-20": ["-bordercolor", "white", "-border", "20"],
        "thumbnail-bw": ["-thumbnail", "320x320", "-colorspace", "Gray"],
    }.get(op)
    if operations is None:
        raise SkillInputError(f"unsupported image op: {op}")
    return _magick(source, out, operations)


# --------------------------------------------------------------------------- #
# Data (stdlib only — works offline, no pandas)
# --------------------------------------------------------------------------- #

def _apply_table_op(rows: list[dict[str, Any]], fields: list[str], args: dict[str, Any]) -> list[dict[str, Any]]:
    op = str(args.get("op") or "head")

    if op == "head":
        return rows[: int(args.get("n") or 20)]
    if op == "tail":
        return rows[-int(args.get("n") or 20):]
    if op == "column-select":
        _need(args, "columns")
        wanted = [part.strip() for part in str(args["columns"]).split(",")]
        return [{key: row.get(key, "") for key in wanted} for row in rows]
    if op == "column-rename":
        _need(args, "columns")  # "old=new,old2=new2"
        mapping = dict(part.split("=", 1) for part in str(args["columns"]).split(",") if "=" in part)
        return [{mapping.get(key, key): value for key, value in row.items()} for row in rows]
    if op == "drop-empty":
        return [row for row in rows if any(str(value).strip() for value in row.values())]
    if op == "dedupe":
        seen, out = set(), []
        for row in rows:
            key = json.dumps(row, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                out.append(row)
        return out
    if op == "sort":
        _need(args, "by")
        reverse = bool(args.get("desc"))
        return sorted(rows, key=lambda row: str(row.get(str(args["by"]), "")), reverse=reverse)
    if op == "filter-contains":
        _need(args, "column", "value")
        needle = str(args["value"]).lower()
        return [row for row in rows
                if needle in str(row.get(str(args["column"]), "")).lower()]
    if op == "group-count":
        _need(args, "column")
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get(str(args["column"]), ""))
            counts[key] = counts.get(key, 0) + 1
        return [{str(args["column"]): key, "count": count}
                for key, count in sorted(counts.items(), key=lambda pair: -pair[1])]
    if op == "sum-column":
        _need(args, "column")
        total = 0.0
        for row in rows:
            try:
                total += float(row.get(str(args["column"]), 0) or 0)
            except (TypeError, ValueError):
                continue
        return [{"column": str(args["column"]), "sum": round(total, 4), "rows": len(rows)}]
    if op == "unique-values":
        _need(args, "column")
        values = sorted({str(row.get(str(args["column"]), "")) for row in rows})
        return [{"value": value} for value in values]
    raise SkillInputError(f"unsupported table op: {op}")


def run_table_op(args: dict[str, Any]) -> dict[str, Any]:
    rows, fields = _records(args)
    out_rows = _apply_table_op(rows, fields, args)
    out_fields = list(dict.fromkeys(key for row in out_rows for key in row)) or fields
    fmt = str(args.get("to") or args.get("format") or "csv").lower()
    out, size = _write_rows(out_rows, out_fields, fmt, args)
    return {"output": out, "rows_in": len(rows), "rows_out": len(out_rows),
            "columns": out_fields, "format": fmt, "size_bytes": size}


def run_table_convert(args: dict[str, Any]) -> dict[str, Any]:
    rows, fields = _records(args)
    fmt = str(args.get("to") or "json").lower()
    out, size = _write_rows(rows, fields, fmt, args)
    return {"output": out, "rows": len(rows), "format": fmt, "size_bytes": size,
            "columns": fields}


def run_table_query(args: dict[str, Any]) -> dict[str, Any]:
    """SQL over an in-memory SQLite copy of the file — real SQL, no server."""

    import sqlite3

    rows, fields = _records(args)
    _need(args, "sql")
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(f'"{field}" TEXT' for field in fields) or '"value" TEXT'
    connection.execute(f'CREATE TABLE data ({columns})')
    placeholders = ", ".join("?" for _ in fields)
    connection.executemany(
        f'INSERT INTO data VALUES ({placeholders})',
        [[str(row.get(field, "")) for field in fields] for row in rows],
    )
    try:
        cursor = connection.execute(str(args["sql"]))
        result = [dict(row) for row in cursor.fetchmany(int(args.get("limit") or 500))]
    except sqlite3.Error as exc:
        raise SkillInputError(f"SQL error: {exc}") from exc
    finally:
        connection.close()
    out_fields = list(result[0].keys()) if result else []
    fmt = str(args.get("to") or "csv").lower()
    out, size = _write_rows(result, out_fields, fmt, args)
    return {"output": out, "rows_in": len(rows), "rows_out": len(result),
            "format": fmt, "size_bytes": size}


# --------------------------------------------------------------------------- #
# Text (offline, deterministic)
# --------------------------------------------------------------------------- #

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "been", "it", "this", "that", "as", "at", "by", "from",
    "hai", "hain", "aur", "ka", "ki", "ke", "ko", "me", "mein", "se", "par", "ye", "wo",
}


def run_text_op(args: dict[str, Any]) -> dict[str, Any]:
    op = str(args.get("op") or "stats")
    text = _text_of(args)

    if op == "stats":
        words = re.findall(r"\S+", text)
        sentences = [part for part in re.split(r"[.!?।]+", text) if part.strip()]
        return {"characters": len(text), "words": len(words), "sentences": len(sentences),
                "lines": len(text.splitlines()),
                "reading_time_minutes": round(len(words) / 200, 1)}

    if op == "word-frequency":
        words = [word.lower() for word in re.findall(r"[A-Za-z\u0600-\u06FF]{2,}", text)]
        counts: dict[str, int] = {}
        for word in words:
            if word in STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
        top = sorted(counts.items(), key=lambda pair: -pair[1])[: int(args.get("n") or 20)]
        return {"top": [{"word": word, "count": count} for word, count in top],
                "unique_words": len(counts)}

    if op == "extract-emails":
        return {"emails": sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)))}
    if op == "extract-urls":
        return {"urls": sorted(set(re.findall(r"https?://[^\s<>\"]+", text)))}
    if op == "extract-hashtags":
        return {"hashtags": sorted(set(re.findall(r"#\w+", text)))}
    if op == "extract-numbers":
        return {"numbers": re.findall(r"-?\d+(?:\.\d+)?", text)}
    if op == "slugify":
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:120]
        return {"slug": slug}
    if op == "case-upper":
        return {"text": text.upper()}
    if op == "case-lower":
        return {"text": text.lower()}
    if op == "case-title":
        return {"text": " ".join(word.capitalize() for word in text.split())}
    if op == "dedupe-lines":
        seen, out = set(), []
        for line in text.splitlines():
            if line.strip() and line not in seen:
                seen.add(line)
                out.append(line)
        return {"text": "\n".join(out), "removed": len(text.splitlines()) - len(out)}
    if op == "sort-lines":
        return {"text": "\n".join(sorted(text.splitlines()))}
    if op == "remove-empty-lines":
        return {"text": "\n".join(line for line in text.splitlines() if line.strip())}
    if op == "trim-whitespace":
        return {"text": re.sub(r'[ \t]+', " ", text).strip()}
    if op == "markdown-links":
        return {"links": re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text)}
    if op == "json-validate":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return {"valid": False, "error": str(exc)}
        return {"valid": True, "type": type(parsed).__name__,
                "keys": list(parsed)[:20] if isinstance(parsed, dict) else None}
    if op == "csv-preview":
        rows, fields = _records({"data": text, "format": "csv"})
        return {"columns": fields, "rows": len(rows), "preview": rows[:5]}
    if op == "lines-to-markdown-list":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return {"text": "\n".join(f"- {line}" for line in lines)}
    if op == "text-hash":
        return {"sha256": hashlib.sha256(text.encode()).hexdigest()}
    raise SkillInputError(f"unsupported text op: {op}")


# --------------------------------------------------------------------------- #
# Code inspection
# --------------------------------------------------------------------------- #

LANG_EXTENSIONS = {
    "python": ".py", "javascript": ".js", "typescript": ".ts", "go": ".go", "rust": ".rs",
    "java": ".java", "php": ".php", "ruby": ".rb", "csharp": ".cs", "swift": ".swift",
    "kotlin": ".kt", "sql": ".sql", "bash": ".sh",
}

SYMBOL_PATTERNS = {
    "python": r"^(?:async\s+)?(?:def|class)\s+(\w+)",
    "javascript": r"^(?:export\s+)?(?:async\s+)?(?:function|class|const)\s+(\w+)",
    "typescript": r"^(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|const)\s+(\w+)",
    "go": r"^func\s+(?:\([^)]*\)\s*)?(\w+)",
    "rust": r"^(?:pub\s+)?(?:fn|struct|enum|trait)\s+(\w+)",
    "java": r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|void|\w+)\s+(\w+)\s*\(",
    "php": r"^(?:function|class)\s+(\w+)",
    "ruby": r"^(?:def|class|module)\s+(\w+)",
    "csharp": r"^\s*(?:public|private|internal)?\s*(?:static\s+)?(?:class|void|\w+)\s+(\w+)\s*\(",
    "swift": r"^(?:func|class|struct|enum)\s+(\w+)",
    "kotlin": r"^(?:fun|class|object)\s+(\w+)",
    "sql": r"(?i)^\s*create\s+(?:table|view|function)\s+(\w+)",
    "bash": r"^(\w+)\s*\(\)\s*\{",
}


def run_code_inspect(args: dict[str, Any]) -> dict[str, Any]:
    _need(args, "path")
    path = _fs_path(args["path"])
    text = path.read_text(encoding="utf-8", errors="replace")
    language = str(args.get("language") or path.suffix.lstrip(".") or "python").lower()
    op = str(args.get("op") or "symbols")
    lines = text.splitlines()

    if op == "symbols":
        pattern = SYMBOL_PATTERNS.get(language)
        if pattern is None:
            raise SkillInputError(f"no symbol pattern for language: {language}")
        found = []
        for number, line in enumerate(lines, 1):
            match = re.match(pattern, line)
            if match:
                found.append({"name": match.group(1), "line": number})
        return {"language": language, "file": path.name, "count": len(found),
                "symbols": found[:200]}

    if op == "todos":
        hits = [{"line": number, "text": line.strip()[:160]}
                for number, line in enumerate(lines, 1)
                if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", line)]
        return {"file": path.name, "count": len(hits), "todos": hits[:100]}

    if op == "secret-scan":
        suspicious = [{"line": number, "hint": "possible hardcoded secret"}
                      for number, line in enumerate(lines, 1)
                      if re.search(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{12,}", line)]
        return {"file": path.name, "count": len(suspicious), "findings": suspicious[:50],
                "note": "heuristic only: read each hit before believing it"}

    if op == "imports":
        found = re.findall(r"^\s*(?:import|from|require\(|use\s)\s+([\w./@-]+)", text, re.MULTILINE)
        return {"file": path.name, "imports": sorted(set(found))[:200]}

    if op == "complexity-hint":
        branches = len(re.findall(r"\b(if|elif|else|for|while|case|catch|switch)\b", text))
        return {"file": path.name, "lines": len(lines), "branch_keywords": branches,
                "lines_per_branch": round(len(lines) / max(1, branches), 1),
                "note": "a hint, not a measured complexity metric"}

    raise SkillInputError(f"unsupported code op: {op}")


# --------------------------------------------------------------------------- #
# Delegates
# --------------------------------------------------------------------------- #

def run_toolbelt(args: dict[str, Any]) -> dict[str, Any]:
    from . import toolbelt

    tool = str(args.get("tool") or "")
    if not tool:
        raise SkillInputError("this skill needs args.tool and args.args")
    return toolbelt.run(tool, args.get("args") or {})


def run_verify_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import toolbelt

    return toolbelt.verify(str(args.get("tool") or ""))


def run_provider(args: dict[str, Any]) -> dict[str, Any]:
    from . import ai_router, quota

    provider = str(args.get("provider") or "").strip().lower()
    prompt = str(args.get("prompt") or args.get("text") or "").strip()
    if not prompt:
        raise SkillInputError("prompt is required")
    quota.reset() if args.get("reset_quota") else None
    previous = os.environ.get("AI_PROVIDER_ORDER")
    os.environ["AI_PROVIDER_ORDER"] = provider
    try:
        answer = ai_router.complete(str(args.get("system") or "You are a helpful assistant."),
                                    prompt, max_tokens=int(args.get("max_tokens") or 800))
    except RuntimeError as exc:
        raise SkillUnavailable(f"unavailable: {exc}") from exc
    finally:
        if previous is None:
            os.environ.pop("AI_PROVIDER_ORDER", None)
        else:
            os.environ["AI_PROVIDER_ORDER"] = previous
    return {"text": answer["text"], "provider": answer["provider"], "model": answer["model"]}


def run_shell_recipe(args: dict[str, Any]) -> dict[str, Any]:
    """Recipe skills are multi-step; they run through the agent registry, not ad-hoc shell."""

    from . import agents

    steps = args.get("steps") or []
    if not steps and args.get("agent"):
        payload = args.get("input")
        if not payload:
            payload = {key: value for key, value in args.items()
                       if key not in {"agent", "steps", "input"}}
        steps = [{"agent": str(args["agent"]), "input": payload}]
    if not steps:
        raise SkillInputError("recipe skills need steps (agent ids + payload) or an agent id")
    results = []
    for step in steps:
        agent_id = str(step.get("agent") or "")
        try:
            results.append(agents.run(agent_id, step.get("input") or {}))
        except KeyError as exc:
            raise SkillInputError(f"unknown agent: {agent_id}") from exc
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422, never a 500
            raise SkillInputError(f"agent {agent_id} failed: {exc}") from exc
    return {"steps": len(results), "results": results}


MODULE_ACTIONS: dict[str, Callable[..., Any]] = {}


def _register_modules() -> None:
    """A whitelist, not a dispatcher: only these dotted names can be called."""

    from . import affect, jarvis, mind, supabase_db

    MODULE_ACTIONS.update({
        "supabase.status": supabase_db.status,
        "supabase.schema": supabase_db.schema_report,
        "supabase.sync": supabase_db.push_jarvis,
        "supabase.pull": supabase_db.pull_facts,
        "jarvis.status": jarvis.status,
        "jarvis.facts": lambda: {"facts": jarvis.facts(200)},
        "mind.self": mind.self_model,
        "mind.reflect": mind.reflect,
        "mind.lessons": lambda: {"lessons": mind.lessons(50)},
        "mind.proposals": lambda: {"proposals": mind.proposals("open", 50)},
        "affect.state": affect.state,
        "character.status": lambda: __import__("app.character", fromlist=["status"]).status(),
    })


def run_module_action(args: dict[str, Any]) -> dict[str, Any]:
    if not MODULE_ACTIONS:
        _register_modules()
    name = str(args.get("action") or "")
    action = MODULE_ACTIONS.get(name)
    if action is None:
        raise SkillUnavailable(
            f"unavailable: unknown module action '{name}' — allowed: {', '.join(sorted(MODULE_ACTIONS))}"
        )
    try:
        return {"action": name, "result": action()}
    except Exception as exc:  # noqa: BLE001 - report the real reason
        text = str(exc)
        if text.startswith("unavailable:"):
            raise SkillUnavailable(text) from exc
        raise SkillInputError(f"{type(exc).__name__}: {text}") from exc


RUNNERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "video_convert": run_video_convert,
    "video_resize": run_video_resize,
    "video_platform": run_video_platform,
    "video_op": run_video_op,
    "video_gif": run_video_gif,
    "video_trim": run_video_trim,
    "media_probe": run_media_probe,
    "audio_convert": run_audio_convert,
    "audio_op": run_audio_op,
    "image_convert": run_image_convert,
    "image_resize": run_image_resize,
    "image_op": run_image_op,
    "table_op": run_table_op,
    "table_convert": run_table_convert,
    "table_query": run_table_query,
    "text_op": run_text_op,
    "code_inspect": run_code_inspect,
    "toolbelt": run_toolbelt,
    "verify_tool": run_verify_tool,
    "provider": run_provider,
    "recipe": run_shell_recipe,
    "modules": run_module_action,
}
