"""Look-and-feel: colour grades, caption styles and logo overlays.

Everything here is a plain ffmpeg filter string, so a grade costs no extra
encode pass when it is applied inside the scene render.
"""

from __future__ import annotations

from pathlib import Path

from .assembly import run_ffmpeg

# Colour grading applied per scene, in the same encode as the scene itself.
GRADE_PRESETS: dict[str, str] = {
    "none": "",
    "cinematic": "eq=contrast=1.10:saturation=1.04:gamma=0.98,vignette=PI/5",
    "warm": "colortemperature=temperature=5600,eq=saturation=1.08:contrast=1.04",
    "cool": "colortemperature=temperature=7800,eq=saturation=0.96:contrast=1.06",
    "teal_orange": "colorbalance=rs=0.05:gs=-0.02:bs=-0.04:rh=-0.03:bh=0.05,eq=contrast=1.08",
    "noir": "hue=s=0,eq=contrast=1.18:brightness=-0.02,vignette=PI/4",
    "vivid": "eq=saturation=1.28:contrast=1.06",
    "film": "curves=preset=vintage,noise=alls=5:allf=t",
    "dream": "gblur=sigma=0.6,eq=saturation=1.10:brightness=0.03",
    "punch": "eq=contrast=1.14:saturation=1.16:brightness=0.01,unsharp=5:5:0.6",
}

# ASS force_style strings. Hex colours are &HAABBGGRR (alpha first).
CAPTION_STYLES: dict[str, str] = {
    "clean": (
        "FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H90000000,BorderStyle=1,Outline=1,Shadow=0,MarginV=28"
    ),
    "bold": (
        "FontName=DejaVu Sans,FontSize=22,Bold=1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&HFF000000,BorderStyle=1,Outline=3,Shadow=1,MarginV=44"
    ),
    "yellow": (
        "FontName=DejaVu Sans,FontSize=22,Bold=1,PrimaryColour=&H0000FFFF,"
        "OutlineColour=&HFF000000,BorderStyle=1,Outline=3,Shadow=1,MarginV=44"
    ),
    "boxed": (
        "FontName=DejaVu Sans,FontSize=20,Bold=1,PrimaryColour=&H00FFFFFF,"
        "BackColour=&HA0000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=36"
    ),
    "minimal": (
        "FontName=DejaVu Sans,FontSize=16,PrimaryColour=&H00F0F0F0,"
        "BorderStyle=1,Outline=0,Shadow=0,MarginV=24"
    ),
}

LOGO_POSITIONS = ("tl", "tr", "bl", "br", "center")


def grade_filter(name: str) -> str:
    """Return the filter chain for a preset, empty for unknown/none."""
    return GRADE_PRESETS.get((name or "none").strip().lower(), "")


def caption_style(name: str) -> str:
    return CAPTION_STYLES.get((name or "clean").strip().lower(), CAPTION_STYLES["clean"])


def _overlay_xy(position: str, margin: int) -> tuple[str, ...]:
    return {
        "tl": ("{m}", "{m}"),
        "tr": ("W-w-{m}", "{m}"),
        "bl": ("{m}", "H-h-{m}"),
        "br": ("W-w-{m}", "H-h-{m}"),
        "center": ("(W-w)/2", "(H-h)/2"),
    }[position]


def overlay_logo(
    video: Path,
    logo: Path,
    out: Path,
    *,
    ffmpeg: str,
    position: str = "br",
    width_ratio: float = 0.12,
    margin: int = 32,
    opacity: float = 1.0,
) -> Path:
    """Stamp a brand logo into a corner of the finished video."""
    pos = position if position in LOGO_POSITIONS else "br"
    ratio = min(max(width_ratio, 0.02), 0.5)
    alpha = min(max(opacity, 0.05), 1.0)
    x, y = _overlay_xy(pos, margin)
    x = x.replace("{m}", str(margin))
    y = y.replace("{m}", str(margin))

    run_ffmpeg(
        [
            "-y", "-i", str(video), "-loop", "1", "-i", str(logo),
            "-filter_complex",
            f"[1:v]scale=iw*{ratio:.3f}:-1,format=rgba,colorchannelmixer=aa={alpha:.2f}[lg];"
            f"[0:v][lg]overlay={x}:{y}:format=auto:shortest=1[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart",
            str(out),
        ],
        ffmpeg=ffmpeg,
    )
    return out


def effect_summary(grade: str, captions_style: str, logo: bool) -> dict[str, object]:
    """Human-readable description of what was applied, for the job payload."""
    return {
        "grade": grade if grade in GRADE_PRESETS else "none",
        "caption_style": captions_style if captions_style in CAPTION_STYLES else "clean",
        "logo": logo,
        "available_grades": sorted(GRADE_PRESETS),
        "available_caption_styles": sorted(CAPTION_STYLES),
    }
