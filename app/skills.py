"""The skill catalogue: thousands of concrete capabilities, each one honest.

Two kinds of skill, never mixed up in the counts:

* **native** — generated from real primitives that exist in this repo (ffmpeg, ImageMagick,
  stdlib text/table/code inspection, the tool belt, the model router, the mind/supabase
  modules). Each has a runner; ``available`` says whether the dependency is on this machine.
* **external** — derived from the 1,763 servers in ``catalog/mcp_ecosystem.json``. They are
  real projects with install instructions, but nothing runs until you install one, so
  ``available`` is always false and the reason is stated.

A skill id is a sentence you can read: ``media.video.convert.mp4-to-webm-vp9``,
``data.table.op.dedupe.json``, ``code.python.todos``. Every entry declares inputs, outputs
and one example, so an agent (or you) can call it without reading the source.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import governance, skill_runners

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_CATALOG = REPO_ROOT / "catalog" / "mcp_ecosystem.json"


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    subcategory: str
    description: str
    engine: str                     # runner key: video_convert, text_op, toolbelt, modules…
    level: str = "basic"
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    offline: bool = True
    example: str = ""
    defaults: dict[str, Any] = field(default_factory=dict)
    source: str = "native"          # native | external
    external_reason: str = ""
    risk: str = ""
    docs: str = ""

    def to_dict(self) -> dict[str, Any]:
        available, detail = availability(self.id)
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "level": self.level,
            "engine": self.engine,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "needs": list(self.needs),
            "offline": self.offline,
            "example": self.example,
            "source": self.source,
            "risk": self.risk,
            "docs": self.docs,
            "available": available,
            "detail": detail,
            "runnable": self.engine in skill_runners.RUNNERS,
        }


# --------------------------------------------------------------------------- #
# Native catalogue generators
# --------------------------------------------------------------------------- #

VIDEO_SOURCES = ("mp4", "mov", "mkv", "webm", "avi", "m4v")
AUDIO_SOURCES = ("mp3", "wav", "m4a", "flac", "ogg", "aac", "mp4", "mov", "mkv")
IMAGE_SOURCES = ("png", "jpg", "webp", "gif", "bmp", "tiff")

CONTAINERS = {
    "mp4": ("h264", "h265"),
    "mkv": ("h264", "h265", "vp9", "av1"),
    "webm": ("vp9", "av1"),
    "mov": ("h264", "h265"),
    "avi": ("h264",),
    "m4v": ("h264",),
    "gif": (),
}

RESIZE_PRESETS = ("1080p", "720p", "480p", "360p", "vertical-1080x1920",
                  "square-1080", "feed-1080x1350")
PLATFORMS = tuple(sorted(skill_runners.PLATFORM_PRESETS))
VIDEO_OPS = ("mute", "speed-0.5", "speed-2", "reverse", "rotate-90", "rotate-180",
             "rotate-270", "grayscale", "flip-horizontal", "flip-vertical", "web-optimize",
             "strip-metadata", "first-frame", "storyboard", "chapters", "cut-silence",
             "loudnorm")
AUDIO_TARGETS = ("mp3", "wav", "m4a", "flac", "ogg")
AUDIO_BITRATES = ("128k", "192k", "320k")
AUDIO_OPS = ("normalize", "mono", "resample-44100", "resample-48000", "fade-in", "fade-out",
             "trim-silence", "speed-1.25", "speed-0.8", "reverse")
IMAGE_TARGETS = ("png", "jpg", "webp", "gif", "bmp", "tiff", "pdf")
IMAGE_QUALITY = (70, 85, 95)
IMAGE_WIDTHS = (320, 512, 720, 1080, 1440, 1920)
IMAGE_OPS = ("grayscale", "rotate-90", "rotate-180", "rotate-270", "flip-horizontal",
             "flip-vertical", "crop-square", "strip-metadata", "blur", "sharpen",
             "border-20", "thumbnail-bw")
TABLE_FORMATS = ("csv", "json", "jsonl", "tsv")
TABLE_OPS = ("head", "tail", "column-select", "column-rename", "drop-empty", "dedupe",
             "sort", "filter-contains", "group-count", "sum-column", "unique-values")
TABLE_TARGETS = ("csv", "json", "jsonl", "tsv", "sqlite")
SQL_ANALYSES = {
    "count": "select count(*) as rows from data",
    "distinct": "select distinct * from data limit 100",
    "group": 'select "{column}", count(*) as n from data group by 1 order by n desc',
    "top": 'select * from data order by "{column}" desc limit 20',
    "sample": "select * from data limit 10",
}
TEXT_OPS = ("stats", "word-frequency", "extract-emails", "extract-urls", "extract-hashtags",
            "extract-numbers", "slugify", "case-upper", "case-lower", "case-title",
            "dedupe-lines", "sort-lines", "remove-empty-lines", "trim-whitespace",
            "markdown-links", "json-validate", "csv-preview", "lines-to-markdown-list",
            "text-hash")
CODE_LANGS = tuple(sorted(skill_runners.LANG_EXTENSIONS))
CODE_OPS = ("symbols", "todos", "secret-scan", "imports", "complexity-hint")

DOC_FORMATS = ("md", "html", "txt", "docx", "pdf", "xlsx", "pptx", "csv")
DOC_TOOL_FOR = {
    ("md", "pdf"): "pandoc", ("md", "docx"): "pandoc", ("md", "html"): "pandoc",
    ("html", "pdf"): "weasyprint", ("docx", "pdf"): "libreoffice",
    ("docx", "md"): "pandoc", ("pptx", "pdf"): "libreoffice",
    ("xlsx", "csv"): "openpyxl", ("csv", "xlsx"): "openpyxl",
    ("pdf", "txt"): "pymupdf", ("pdf", "md"): "pymupdf",
    ("pptx", "md"): "python-pptx", ("docx", "txt"): "python-docx",
}

RECIPES: tuple[tuple[str, str, str, str, str], ...] = (
    ("video-to-shorts-pack", "Video → shorts pack", "Probe, chapters, thumbnails and a vertical cut from one file.",
     "probe → chapters → thumbnails → vertical clip", "agent:clip-maker"),
    ("podcast-pack", "Podcast pack", "Chapters, transcript and show notes for one audio file.",
     "chapters → transcript → notes", "agent:chapter-writer"),
    ("release-check", "Pre-release check", "Run the test suite, report failures, then summarise.",
     "pytest → summary", "agent:test-planner"),
    ("repo-brief", "Repository brief", "Code index plus structure summary for a repo.",
     "index → structure", "agent:repo-scout"),
    ("content-repurpose", "Content repurpose", "Turn one long video into titles, hashtags and a caption block.",
     "chapters → titles → hashtags", "agent:title-suggester"),
    ("health-report", "Health report", "Deep health, queue depth and provider status in one answer.",
     "health → queue → providers", "agent:health-warden"),
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _native() -> list[Skill]:
    skills: list[Skill] = []

    # --- video -------------------------------------------------------------
    for source in VIDEO_SOURCES:
        for target, codecs in CONTAINERS.items():
            for codec in codecs:
                if target == source:
                    continue  # same container = a re-encode, not a conversion skill
                skills.append(Skill(
                    id=f"media.video.convert.{source}-to-{target}-{codec}",
                    name=f"Convert {source.upper()} → {target.upper()} ({codec})",
                    category="media", subcategory="video.convert", level="basic",
                    description=f"Re-encode a {source} video into {target} using the {codec} codec.",
                    engine="video_convert", inputs=("path",), outputs=("output",),
                    needs=("ffmpeg",), offline=True,
                    example=f'tool ffmpeg op=convert path=clip.{source} target={target} codec={codec}',
                    defaults={"target": target, "codec": codec},
                ))
        for preset in RESIZE_PRESETS:
            skills.append(Skill(
                id=f"media.video.resize.{source}-to-{preset}",
                name=f"Resize {source.upper()} → {preset}",
                category="media", subcategory="video.resize", level="basic",
                description=f"Scale a {source} video to the {preset} frame, keeping aspect ratio.",
                engine="video_resize", inputs=("path",), outputs=("output",),
                needs=("ffmpeg",), example=f"path=clip.{source} preset={preset}",
                defaults={"preset": preset},
            ))
        for platform in PLATFORMS:
            skills.append(Skill(
                id=f"media.video.platform.{source}-to-{platform}",
                name=f"{platform} export from {source.upper()}",
                category="media", subcategory="video.platform", level="intermediate",
                description=f"Export a {source} video using the {platform} frame size and bitrate.",
                engine="video_platform", inputs=("path",), outputs=("output",),
                needs=("ffmpeg",), example=f"path=clip.{source} platform={platform}",
                defaults={"platform": platform},
            ))
        for op in VIDEO_OPS:
            skills.append(Skill(
                id=f"media.video.op.{source}.{_slug(op)}",
                name=f"{op} on {source.upper()}",
                category="media", subcategory="video.op", level="basic",
                description=f"Apply the '{op}' operation to a {source} video with ffmpeg.",
                engine="video_op", inputs=("path",), outputs=("output", "report"),
                needs=("ffmpeg",), example=f"path=clip.{source} op={op}",
                defaults={"op": op},
            ))
        skills.append(Skill(
            id=f"media.video.trim.{source}", name=f"Trim {source.upper()}",
            category="media", subcategory="video.trim", level="basic",
            description="Cut a start→end range out of a video without re-encoding.",
            engine="video_trim", inputs=("path", "start", "end"), outputs=("output",),
            needs=("ffmpeg",), example="path=clip.mp4 start=12 end=48",
        ))
        skills.append(Skill(
            id=f"media.video.gif.{source}", name=f"GIF from {source.upper()}",
            category="media", subcategory="video.gif", level="basic",
            description="Turn a short range of a video into a looping GIF.",
            engine="video_gif", inputs=("path", "start", "end"), outputs=("output",),
            needs=("ffmpeg",), example="path=clip.mp4 start=3 end=6 width=480",
        ))
        skills.append(Skill(
            id=f"media.probe.{source}", name=f"Inspect {source.upper()}",
            category="media", subcategory="probe", level="basic",
            description="Duration, resolution, fps and stream list for a media file.",
            engine="media_probe", inputs=("path",), outputs=("report",),
            needs=("ffmpeg",), example=f"path=clip.{source}",
        ))

    # --- audio -------------------------------------------------------------
    for source in AUDIO_SOURCES:
        for target in AUDIO_TARGETS:
            for bitrate in AUDIO_BITRATES:
                if target == source and bitrate == "192k":
                    continue
                skills.append(Skill(
                    id=f"media.audio.convert.{source}-to-{target}-{bitrate}",
                    name=f"Convert {source.upper()} → {target.upper()} @ {bitrate}",
                    category="media", subcategory="audio.convert", level="basic",
                    description=f"Transcode audio to {target} at {bitrate}.",
                    engine="audio_convert", inputs=("path",), outputs=("output",),
                    needs=("ffmpeg",), example=f"path=voice.{source} target={target} bitrate={bitrate}",
                    defaults={"target": target, "bitrate": bitrate},
                ))
        for op in AUDIO_OPS:
            skills.append(Skill(
                id=f"media.audio.op.{source}.{_slug(op)}", name=f"{op} on {source.upper()}",
                category="media", subcategory="audio.op", level="basic",
                description=f"Apply '{op}' to an audio file (loudness, speed, silence, channels).",
                engine="audio_op", inputs=("path",), outputs=("output",),
                needs=("ffmpeg",), example=f"path=voice.{source} op={op}",
                defaults={"op": op},
            ))

    # --- image -------------------------------------------------------------
    for source in IMAGE_SOURCES:
        for target in IMAGE_TARGETS:
            for quality in IMAGE_QUALITY:
                if target == source:
                    continue  # same format at another quality is not a conversion
                skills.append(Skill(
                    id=f"media.image.convert.{source}-to-{target}-q{quality}",
                    name=f"Convert {source.upper()} → {target.upper()} (q{quality})",
                    category="media", subcategory="image.convert", level="basic",
                    description=f"Convert an image to {target} at quality {quality}, metadata stripped.",
                    engine="image_convert", inputs=("path",), outputs=("output",),
                    needs=("imagemagick",), example=f"path=photo.{source} target={target} quality={quality}",
                    defaults={"target": target, "quality": quality},
                ))
        for width in IMAGE_WIDTHS:
            skills.append(Skill(
                id=f"media.image.resize.{source}-to-{width}",
                name=f"Resize {source.upper()} → {width}px",
                category="media", subcategory="image.resize", level="basic",
                description=f"Resize an image to {width}px wide, aspect ratio preserved.",
                engine="image_resize", inputs=("path",), outputs=("output",),
                needs=("imagemagick",), example=f"path=photo.{source} width={width}",
                defaults={"width": width},
            ))
        for op in IMAGE_OPS:
            skills.append(Skill(
                id=f"media.image.op.{source}.{_slug(op)}", name=f"{op} on {source.upper()}",
                category="media", subcategory="image.op", level="basic",
                description=f"Apply '{op}' to an image.",
                engine="image_op", inputs=("path",), outputs=("output",),
                needs=("imagemagick",), example=f"path=photo.{source} op={op}",
                defaults={"op": op},
            ))

    # --- data --------------------------------------------------------------
    for fmt in TABLE_FORMATS:
        for op in TABLE_OPS:
            skills.append(Skill(
                id=f"data.table.op.{_slug(op)}.{fmt}",
                name=f"{op} on a {fmt.upper()} table",
                category="data", subcategory="table.op",
                level="basic" if op in {"head", "tail", "dedupe"} else "intermediate",
                description=f"Apply '{op}' to a {fmt} file and write the result back out.",
                engine="table_op", inputs=("path",), outputs=("output", "summary"),
                offline=True, example=f"path=rows.{fmt} op={op}",
                defaults={"op": op, "format": fmt},
            ))
        for target in TABLE_TARGETS:
            if target == fmt:
                continue
            skills.append(Skill(
                id=f"data.table.convert.{fmt}-to-{target}",
                name=f"{fmt.upper()} → {target.upper()}",
                category="data", subcategory="table.convert", level="basic",
                description=f"Convert a {fmt} file to {target} (stdlib only).",
                engine="table_convert", inputs=("path",), outputs=("output",),
                example=f"path=rows.{fmt} to={target}",
                defaults={"to": target, "format": fmt},
            ))
        for name, sql in SQL_ANALYSES.items():
            skills.append(Skill(
                id=f"data.table.sql.{name}.{fmt}",
                name=f"SQL {name} over {fmt.upper()}",
                category="data", subcategory="table.sql", level="intermediate",
                description=f"Run a real SQLite query for '{name}' over a {fmt} file.",
                engine="table_query", inputs=("path", "sql"), outputs=("output",),
                example=f"path=rows.{fmt} sql=\"{sql}\"",
                defaults={"format": fmt, "sql": sql},
            ))

    # --- text --------------------------------------------------------------
    for op in TEXT_OPS:
        for mode in ("inline", "file"):
            skills.append(Skill(
                id=f"text.{_slug(op)}.{mode}", name=f"{op} ({mode})",
                category="text", subcategory="text", level="basic",
                description=("Run '" + op + "' on inline text." if mode == "inline"
                             else "Run '" + op + "' on a text file in the repo or data root."),
                engine="text_op", inputs=(("text",) if mode == "inline" else ("path",)),
                outputs=("report",), offline=True,
                example=("text=\"hello world\"" if mode == "inline" else "path=notes.txt"),
                defaults={"op": op},
            ))

    # --- code --------------------------------------------------------------
    for language in CODE_LANGS:
        for op in CODE_OPS:
            skills.append(Skill(
                id=f"code.{language}.{_slug(op)}", name=f"{op} in {language}",
                category="code", subcategory="code.inspect", level="basic",
                description=f"Inspect a {language} file for {op}.",
                engine="code_inspect", inputs=("path",), outputs=("report",),
                offline=True, example=f"path=main{skill_runners.LANG_EXTENSIONS[language]}",
                defaults={"language": language, "op": op},
            ))

    # --- documents (declared, dependency-gated) ----------------------------
    for (source, target), tool in DOC_TOOL_FOR.items():
        skills.append(Skill(
            id=f"docs.convert.{source}-to-{target}",
            name=f"{source.upper()} → {target.upper()}",
            category="docs", subcategory="docs.convert", level="basic",
            description=f"Convert {source} to {target} using {tool}.",
            engine=f"docs:{tool}", inputs=("path",), outputs=("output",),
            needs=(tool,), offline=(tool != "weasyprint"),
            example=f"path=report.{source}",
            external_reason=f"needs {tool} installed",
        ))

    # --- tool belt ---------------------------------------------------------
    try:
        from . import toolbelt

        for tool in toolbelt.list_tools()["tools"]:
            skills.append(Skill(
                id=f"tool.{tool['id']}.run", name=f"Run {tool['name']}",
                category="tools", subcategory=tool["category"], level="basic",
                description=tool["does"], engine="toolbelt",
                inputs=("args",), outputs=("result",),
                needs=tuple(tool["needs"]), offline=bool(tool["offline"]),
                example=f"args={{'tool': '{tool['id']}', 'args': {{}}}}",
                defaults={"tool": tool["id"]},
            ))
            skills.append(Skill(
                id=f"tool.{tool['id']}.verify", name=f"Verify {tool['name']}",
                category="tools", subcategory="verify", level="basic",
                description=f"Run the catalogue's own proof command for {tool['name']}.",
                engine="verify_tool", inputs=(), outputs=("report",),
                needs=tuple(tool["needs"]), offline=bool(tool["offline"]),
                example=f"tool={tool['id']}", defaults={"tool": tool["id"]},
            ))
    except Exception:  # noqa: BLE001 - the belt is optional for this module to import
        pass

    # --- model providers ---------------------------------------------------
    try:
        from . import ai_router

        for provider_id in sorted(ai_router.PROVIDERS):
            label = ai_router.PROVIDERS[provider_id].label
            skills.append(Skill(
                id=f"ai.{provider_id}.chat", name=f"Chat via {label}",
                category="ai", subcategory="provider.chat", level="basic",
                description=f"Send one prompt to {label} through the router.",
                engine="provider", inputs=("prompt",), outputs=("text",),
                needs=(ai_router.PROVIDERS[provider_id].key_env,),
                offline=ai_router.PROVIDERS[provider_id].local,
                example=f"prompt=\"summarise this\" provider={provider_id}",
                defaults={"provider": provider_id},
            ))
            skills.append(Skill(
                id=f"ai.{provider_id}.json", name=f"JSON answer via {label}",
                category="ai", subcategory="provider.json", level="intermediate",
                description=f"Ask {label} for a JSON object and return it parsed.",
                engine="provider", inputs=("prompt",), outputs=("json",),
                needs=(ai_router.PROVIDERS[provider_id].key_env,),
                offline=ai_router.PROVIDERS[provider_id].local,
                example=f"prompt=\"return {{}} with keys a,b\" provider={provider_id}",
                defaults={"provider": provider_id,
                          "system": "Reply with valid JSON only, no prose."},
            ))
    except Exception:  # noqa: BLE001
        pass

    # --- module actions (mind, supabase, jarvis) ---------------------------
    module_skills = (
        ("supabase.status", "Supabase status", "Is the database configured and reachable?"),
        ("supabase.schema", "Supabase schema check", "Which uaib_* tables actually answer."),
        ("supabase.sync", "Push memory to Supabase", "Upsert facts, lessons and journal."),
        ("supabase.pull", "Pull memory from Supabase", "Restore facts onto a fresh machine."),
        ("jarvis.status", "JARVIS status", "Brain, belt, character and mood in one payload."),
        ("jarvis.facts", "List remembered facts", "Everything JARVIS remembers about you."),
        ("mind.self", "Self model", "Measured capability and known gaps."),
        ("mind.reflect", "Reflect", "Read the turn log and write lessons + proposals."),
        ("mind.lessons", "List lessons", "What reflection has learned so far."),
        ("mind.proposals", "List proposals", "Open improvement proposals."),
        ("affect.state", "Mood state", "The five-number mood vector and its tone directive."),
        ("character.status", "Character status", "Current persona preset and traits."),
    )
    for action, name, description in module_skills:
        skills.append(Skill(
            id=f"system.{action.replace('.', '-')}", name=name,
            category="system", subcategory="module", level="basic",
            description=description, engine="modules", inputs=(), outputs=("result",),
            offline=not action.startswith("supabase"),
            example=f"action={action}", defaults={"action": action},
        ))

    # --- recipes -----------------------------------------------------------
    for recipe_id, name, description, steps, agent in RECIPES:
        skills.append(Skill(
            id=f"recipe.{recipe_id}", name=name, category="recipe", subcategory="workflow",
            level="advanced", description=f"{description} Steps: {steps}",
            engine="recipe", inputs=("agent", "input"), outputs=("results",),
            defaults={"agent": agent.split(":", 1)[-1]},
            example=f"agent={agent.split(':', 1)[-1]}",
        ))

    return skills


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, Skill] | None = None
_EXTERNAL: dict[str, Skill] | None = None
_AVAILABILITY: dict[str, tuple[float, tuple[bool, str]]] = {}
CACHE_TTL = 30.0


def _load_native() -> dict[str, Skill]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {}
        for skill in _native():
            _REGISTRY.setdefault(skill.id, skill)
    return _REGISTRY


def _load_external(limit: int | None = None) -> dict[str, Skill]:
    """MCP servers from the repo catalogue, as importable (not installed) skills."""

    global _EXTERNAL
    if _EXTERNAL is None:
        _EXTERNAL = {}
        if MCP_CATALOG.exists():
            try:
                entries = json.loads(MCP_CATALOG.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                entries = []
            for entry in entries:
                identifier = str(entry.get("id") or "").strip()
                if not identifier:
                    continue
                capabilities = entry.get("capabilities") or []
                skills_list = [str(item) for item in capabilities[:6]]
                _EXTERNAL[identifier] = Skill(
                    id=identifier,
                    name=str(entry.get("name") or identifier)[:120],
                    category="external",
                    subcategory=str(entry.get("subcategory") or "mcp")[:40],
                    description=str(entry.get("description") or "")[:400],
                    engine="external",
                    level="advanced",
                    inputs=(),
                    outputs=(),
                    needs=(str(entry.get("integration_type") or "mcp-server"),),
                    offline=False,
                    example=f"install: {entry.get('repository_url') or entry.get('docs_url') or ''}",
                    source="external",
                    external_reason=(
                        "MCP server from catalog/mcp_ecosystem.json — install it and register "
                        "the tools before anything can run"
                    ),
                    risk=str(entry.get("risk_level") or ""),
                    docs=str(entry.get("repository_url") or entry.get("docs_url") or ""),
                )
    if limit is not None:
        return dict(list(_EXTERNAL.items())[:limit])
    return _EXTERNAL


def refresh() -> dict[str, int]:
    global _REGISTRY, _EXTERNAL
    _REGISTRY = None
    _EXTERNAL = None
    _AVAILABILITY.clear()
    native = len(_load_native())
    external = len(_load_external())
    return {"native": native, "external": external, "total": native + external}


def get(skill_id: str) -> Skill:
    key = (skill_id or "").strip()
    native = _load_native()
    if key in native:
        return native[key]
    external = _load_external()
    if key in external:
        return external[key]
    suggestions = [item["id"] for item in search(key, limit=3)["results"]]
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    raise KeyError(f"unknown skill: {skill_id}.{hint}")


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #

def availability(skill_id: str) -> tuple[bool, str]:
    cached = _AVAILABILITY.get(skill_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    verdict = _evaluate(skill_id)
    _AVAILABILITY[skill_id] = (now, verdict)
    return verdict


def _evaluate(skill_id: str) -> tuple[bool, str]:
    try:
        skill = get(skill_id)
    except KeyError as exc:
        return False, str(exc)

    if skill.source == "external":
        return False, f"unavailable: {skill.external_reason}"

    if skill.engine.startswith("docs:"):
        tool = skill.engine.split(":", 1)[1]
        lookup = {"libreoffice": "soffice", "pymupdf": None, "python-docx": None,
                  "python-pptx": None, "openpyxl": None, "weasyprint": None,
                  "pandoc": "pandoc"}.get(tool, tool)
        if lookup and shutil.which(lookup):
            return True, f"{tool} present"
        try:
            module = {"pymupdf": "fitz", "python-docx": "docx", "python-pptx": "pptx",
                      "openpyxl": "openpyxl", "weasyprint": "weasyprint",
                      "pandoc": None}.get(tool)
            if module:
                import importlib.util

                if importlib.util.find_spec(module) is not None:
                    return True, f"{tool} module present"
        except (ImportError, ValueError):
            pass
        return False, f"unavailable: install {tool}"

    if skill.engine in {"video_convert", "video_resize", "video_platform", "video_op",
                        "video_gif", "video_trim", "media_probe", "audio_convert", "audio_op"}:
        try:
            from videoengine.assembly import find_ffmpeg

            find_ffmpeg()
            return True, "ffmpeg ready"
        except Exception:  # noqa: BLE001
            return False, "unavailable: pip install imageio-ffmpeg"

    if skill.engine.startswith("image_"):
        binary = shutil.which("convert") or shutil.which("magick")
        return (True, f"imagemagick at {binary}") if binary else (
            False, "unavailable: apt-get install imagemagick")

    if skill.engine in {"provider"}:
        from . import ai_router

        provider = str(skill.defaults.get("provider") or "")
        routes = ai_router.resolve_all(provider) if provider else []
        return (True, f"{provider} configured") if routes else (
            False, f"unavailable: set {skill.needs[0] if skill.needs else 'a provider key'}")

    if skill.engine in {"toolbelt", "verify_tool"}:
        from . import toolbelt

        tool_id = str(skill.defaults.get("tool") or "")
        try:
            return toolbelt.availability(tool_id)
        except Exception as exc:  # noqa: BLE001
            return False, f"unavailable: {exc}"

    if skill.engine == "recipe":
        from . import agents

        return True, f"{len(agents.AGENTS)} agents available"

    if skill.engine == "modules":
        return True, "in-process module"

    # stdlib engines: table_op, table_convert, table_query, text_op, code_inspect
    return True, "std lib only"


# --------------------------------------------------------------------------- #
# Listing and search
# --------------------------------------------------------------------------- #

def list_skills(*, category: str | None = None, subcategory: str | None = None,
                source: str | None = None, level: str | None = None,
                available: bool | None = None, limit: int = 50, offset: int = 0,
                include_external: bool = True) -> dict[str, Any]:
    pool: Iterable[Skill] = list(_load_native().values())
    if include_external:
        pool = list(pool) + list(_load_external().values())

    selected: list[Skill] = []
    for skill in pool:
        if source and skill.source != source:
            continue
        if category and skill.category != category:
            continue
        if subcategory and skill.subcategory != subcategory:
            continue
        if level and skill.level != level:
            continue
        if available is not None:
            ok, _ = availability(skill.id)
            if ok != available:
                continue
        selected.append(skill)

    selected.sort(key=lambda item: (item.source != "native", item.category, item.id))
    window = selected[offset: offset + max(1, min(limit, 200))]
    return {
        "total": len(selected),
        "offset": offset,
        "count": len(window),
        "skills": [skill.to_dict() for skill in window],
    }


def stats() -> dict[str, Any]:
    native = _load_native()
    external = _load_external()
    by_category: dict[str, int] = {}
    by_subcategory: dict[str, int] = {}
    available = 0
    for skill in native.values():
        by_category[skill.category] = by_category.get(skill.category, 0) + 1
        by_subcategory[skill.subcategory] = by_subcategory.get(skill.subcategory, 0) + 1
        ok, _ = availability(skill.id)
        available += 1 if ok else 0
    return {
        "total": len(native) + len(external),
        "native": len(native),
        "external": len(external),
        "available_now": available,
        "native_runnable": sum(1 for skill in native.values()
                               if skill.engine in skill_runners.RUNNERS),
        "by_category": dict(sorted(by_category.items(), key=lambda pair: -pair[1])),
        "by_subcategory": dict(sorted(by_subcategory.items(), key=lambda pair: -pair[1])[:20]),
        "examples": [skill.id for skill in list(native.values())[:8]],
        "honesty": (
            "Native skills run here when their dependency exists. External skills come from "
            "catalog/mcp_ecosystem.json: real projects, not installed, so they report "
            "available=false until you install them."
        ),
    }


def categories() -> dict[str, Any]:
    native = _load_native()
    groups: dict[str, dict[str, int]] = {}
    for skill in native.values():
        bucket = groups.setdefault(skill.category, {})
        bucket[skill.subcategory] = bucket.get(skill.subcategory, 0) + 1
    return {"categories": groups, "external": len(_load_external()),
            "source": "native skills grouped by category → subcategory"}


# --- BM25 --------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _target_tokens(skill_id: str) -> list[str]:
    """`media.video.convert.mp4-to-webm-vp9` -> tokens of the target half (`webm`, `vp9`).

    "convert to X" should rank X-targeted skills above X-sourced ones, so the target half
    of an id is weighted heavier in the index.
    """

    tail = skill_id.rsplit(".", 1)[-1]
    for marker in ("-to-", "-into-"):
        if marker in tail:
            return _tokens(tail.split(marker, 1)[1].replace("-", " "))
    return []


def search(query: str, limit: int = 10, *, include_external: bool = True) -> dict[str, Any]:
    entries: list[Skill] = list(_load_native().values())
    if include_external:
        entries.extend(_load_external().values())
    documents = {
        skill.id: _tokens(f"{skill.id} {skill.name} {skill.category} {skill.subcategory} "
                          f"{skill.description} {' '.join(skill.needs)}")
        + _target_tokens(skill.id) * 3
        for skill in entries
    }
    query_tokens = _tokens(query or "")
    if not query_tokens:
        return {"query": query, "count": 0, "results": []}

    total = len(documents)
    average = sum(len(tokens) for tokens in documents.values()) / max(1, total)
    idf = {}
    for token in set(query_tokens):
        seen = sum(1 for tokens in documents.values() if token in tokens)
        idf[token] = math.log(1 + (total - seen + 0.5) / (seen + 0.5))

    k1, b = 1.5, 0.75
    scored: list[tuple[float, str]] = []
    for skill_id, tokens in documents.items():
        length = len(tokens) or 1
        score = 0.0
        for token in query_tokens:
            frequency = tokens.count(token)
            if not frequency:
                continue
            score += idf[token] * (frequency * (k1 + 1)) / (
                frequency + k1 * (1 - b + b * length / max(1.0, average))
            )
        if score > 0:
            scored.append((score, skill_id))

    scored.sort(reverse=True)
    results = []
    for score, skill_id in scored[: max(1, min(limit, 50))]:
        skill = entries[[entry.id for entry in entries].index(skill_id)]
        results.append({**skill.to_dict(), "score": round(score, 3)})
    return {"query": query, "count": len(results), "results": results}


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #

def run(skill_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        skill = get(skill_id)
    except KeyError as exc:
        raise skill_runners.SkillInputError(str(exc).replace("KeyError: ", "")) from exc

    ok, detail = availability(skill.id)
    if not ok:
        raise skill_runners.SkillUnavailable(
            detail if detail.startswith("unavailable:") else f"unavailable: {detail}")

    runner = skill_runners.RUNNERS.get(skill.engine)
    if runner is None:
        raise skill_runners.SkillUnavailable(
            f"unavailable: no runner for engine '{skill.engine}' "
            f"(needs {', '.join(skill.needs) or 'external tooling'})")

    payload = {**skill.defaults, **(args or {})}
    started = time.perf_counter()
    try:
        result = runner(payload)
    except (skill_runners.SkillInputError, skill_runners.SkillUnavailable):
        raise
    except Exception as exc:  # noqa: BLE001 - surface it, keep the API alive
        governance.record("skill.failed", target=skill.id, outcome="error",
                          detail={"error": f"{type(exc).__name__}: {exc}"[:300]})
        raise skill_runners.SkillInputError(f"{type(exc).__name__}: {exc}") from exc

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    governance.record("skill.run", target=skill.id, outcome="ok",
                      detail={"ms": elapsed, "engine": skill.engine})
    return {"ok": True, "skill": skill.id, "name": skill.name, "engine": skill.engine,
            "elapsed_ms": elapsed, "result": result}
