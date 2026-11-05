"""ffmpeg-driven assembly of a Timeline into a single long video.

No third-party Python packages: only the ffmpeg binary. Every invocation passes
an argument list (never a shell string), so paths cannot inject commands.

The render is done scene by scene into small segments that are concatenated at
the end. That keeps peak memory flat no matter how long the video is, and lets a
crashed render resume by reusing segments that already exist.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Protocol

from .timeline import Scene, Timeline, to_srt

ProgressFn = Callable[[float, str], None]


class SceneAssets(Protocol):
    def __call__(self, scene: Scene) -> dict[str, Any]:
        ...


class FfmpegNotFound(RuntimeError):
    pass


def find_ffmpeg() -> str:
    """Locate an ffmpeg binary: explicit env var, then PATH, then bundled wheel."""
    import os

    explicit = os.getenv("FFMPEG_BINARY", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # optional convenience for bare sandboxes / CI
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on environment
        raise FfmpegNotFound(
            "ffmpeg was not found. Install it (apt-get install ffmpeg) or set "
            "FFMPEG_BINARY to its path."
        ) from exc


def run_ffmpeg(args: list[str], *, ffmpeg: str, timeout: int = 3600) -> str:
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-12:]
        raise RuntimeError("ffmpeg failed: " + " | ".join(tail))
    return completed.stderr or ""


def probe(path: Path, *, ffmpeg: str) -> dict[str, float | int]:
    """Read duration and resolution without needing ffprobe."""
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    text = completed.stderr or ""
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    size_match = re.search(r",\s(\d{2,5})x(\d{2,5})", text)
    duration = 0.0
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return {
        "duration": round(duration, 3),
        "width": int(size_match.group(1)) if size_match else 0,
        "height": int(size_match.group(2)) if size_match else 0,
    }


def _fit_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )


def _zoom_filter(width: int, height: int, fps: int, frames: int) -> str:
    # Render at 2x then pan, so the slow zoom stays sharp.
    return (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='min(zoom+0.0009,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={width}x{height}:fps={fps},setsar=1"
    )


def render_scene(
    *,
    out: Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    ffmpeg: str,
    image: Path | None = None,
    video: Path | None = None,
    audio: Path | None = None,
    ken_burns: bool = True,
    fade: bool = False,
    grade: str = "",
) -> Path:
    """Render one scene to an mp4 with video and audio streams of equal length."""
    if duration <= 0:
        raise ValueError("duration must be positive")
    if image is None and video is None:
        # A colour card keeps the timeline renderable before media exists.
        image = None

    frames = max(1, int(round(duration * fps)))
    args: list[str] = ["-y"]

    if video is not None:
        args += ["-stream_loop", "-1", "-i", str(video)]
        filters = [_fit_filter(width, height)]
    elif image is not None:
        args += ["-loop", "1", "-i", str(image)]
        filters = [_zoom_filter(width, height, fps, frames) if ken_burns else _fit_filter(width, height)]
    else:
        args += ["-f", "lavfi", "-i", f"color=c=0x101820:s={width}x{height}:r={fps}:d={duration}"]
        filters = [_fit_filter(width, height)]

    if audio is not None:
        args += ["-i", str(audio)]
        audio_map = ["-map", "1:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        # Index 0 is always the visual input, so the audio source is always 1.
        audio_map = ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]

    if grade:
        filters.append(grade)
    if fade:
        filters.append(f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0.0, duration - 0.4):.3f}:d=0.4")

    filters.append("format=yuv420p")
    args += [
        "-map", "0:v:0",
        "-vf", ",".join(filters),
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-video_track_timescale", "90000",
        *audio_map,
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(out),
    ]
    run_ffmpeg(args, ffmpeg=ffmpeg, timeout=max(300, int(duration * 30)))
    return out


def concat(segments: list[Path], out: Path, *, ffmpeg: str, work_dir: Path) -> Path:
    """Concatenate segments without re-encoding (they share encoder settings)."""
    if not segments:
        raise ValueError("no segments to concatenate")
    listing = work_dir / "segments.txt"
    listing.write_text(
        "".join(f"file '{segment.resolve().as_posix()}'\n" for segment in segments),
        encoding="utf-8",
    )
    try:
        run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
            ffmpeg=ffmpeg,
        )
    except RuntimeError:
        # Older builds sometimes reject stream-copy concat; re-encode instead.
        run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", str(out)],
            ffmpeg=ffmpeg,
        )
    return out


def mix_music(video: Path, music: Path, out: Path, *, ffmpeg: str, music_volume: float = 0.18) -> Path:
    """Lay a music bed under the narration without drowning it out."""
    volume = min(max(music_volume, 0.0), 1.0)
    run_ffmpeg(
        [
            "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(music),
            "-filter_complex",
            f"[1:a]volume={volume:.2f}[bed];[0:a][bed]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out),
        ],
        ffmpeg=ffmpeg,
    )
    return out


def burn_captions(
    video: Path, subtitles: Path, out: Path, *, ffmpeg: str, force_style: str | None = None
) -> Path:
    escaped = str(subtitles.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    subtitle_filter = f"subtitles='{escaped}'"
    if force_style:
        subtitle_filter += f":force_style='{force_style}'"
    run_ffmpeg(
        ["-y", "-i", str(video), "-vf", subtitle_filter,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "copy", str(out)],
        ffmpeg=ffmpeg,
    )
    return out


def render_timeline(
    timeline: Timeline,
    assets_for_scene: SceneAssets,
    output: Path,
    *,
    work_dir: Path,
    ffmpeg: str | None = None,
    music: Path | None = None,
    captions: bool = False,
    caption_style: str | None = None,
    grade: str = "",
    logo: Path | None = None,
    logo_position: str = "br",
    resume: bool = True,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Render every scene, join them, then add music and captions."""
    binary = ffmpeg or find_ffmpeg()
    work_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    total = len(timeline.scenes)
    for position, scene in enumerate(timeline.scenes, start=1):
        segment = work_dir / f"seg_{scene.index:05d}.mp4"
        if not (resume and segment.exists() and segment.stat().st_size > 1024):
            assets = assets_for_scene(scene) or {}
            render_scene(
                out=segment,
                duration=scene.duration,
                width=timeline.width,
                height=timeline.height,
                fps=timeline.fps,
                ffmpeg=binary,
                image=assets.get("image"),
                video=assets.get("video"),
                audio=assets.get("audio"),
                ken_burns=bool(assets.get("ken_burns", True)),
                fade=scene.transition == "fade",
                grade=grade,
            )
        segments.append(segment)
        if progress:
            progress(position / total * 0.85, f"scene {position}/{total}")

    joined = work_dir / "joined.mp4"
    concat(segments, joined, ffmpeg=binary, work_dir=work_dir)

    current = joined
    if music is not None:
        if progress:
            progress(0.9, "mixing music")
        current = mix_music(current, music, work_dir / "with_music.mp4", ffmpeg=binary)
    if captions:
        subtitle_text = to_srt(timeline)
        if subtitle_text.strip():
            if progress:
                progress(0.95, "burning captions")
            srt_path = work_dir / "captions.srt"
            srt_path.write_text(subtitle_text, encoding="utf-8")
            current = burn_captions(
                current, srt_path, work_dir / "with_captions.mp4", ffmpeg=binary, force_style=caption_style
            )

    if logo is not None and logo.is_file():
        if progress:
            progress(0.98, "stamping logo")
        from .effects import overlay_logo

        current = overlay_logo(
            current, logo, work_dir / "with_logo.mp4", ffmpeg=binary, position=logo_position
        )

    if current != output:
        shutil.move(str(current), str(output))
    if progress:
        progress(1.0, "done")
    return {
        "output": str(output),
        "duration": probe(output, ffmpeg=binary)["duration"],
        "segments": len(segments),
        "size_bytes": output.stat().st_size,
    }
