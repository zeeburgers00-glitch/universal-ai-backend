"""Rule-based task router: a plain sentence becomes a skill + arguments.

No model key needed. The router only speaks when it can name a real skill id from the
catalogue; when it is unsure it returns ``None`` and JARVIS says so instead of guessing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import skills

# File extensions we recognise inside a sentence.
VIDEO_EXT = {"mp4", "mov", "mkv", "webm", "avi", "m4v"}
AUDIO_EXT = {"mp3", "wav", "m4a", "flac", "ogg", "aac"}
IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}
TABLE_EXT = {"csv", "tsv", "json", "jsonl"}

TARGET_CONTAINERS = ("webm", "mp4", "mkv", "mov", "avi", "m4v", "mp3", "wav", "flac", "ogg",
                     "m4a", "jpg", "jpeg", "png", "webp", "gif", "pdf")

PLATFORM_WORDS = {
    "shorts": "shorts-1080x1920",
    "reels": "reels-1080x1920",
    "tiktok": "tiktok-1080x1920",
    "youtube": "youtube-1080p",
    "instagram": "instagram-feed",
    "whatsapp": "whatsapp-status",
    "linkedin": "linkedin-feed",
    "twitter": "twitter-feed",
}

RESIZE_WORDS = {
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
    "360p": "360p",
    "vertical": "vertical-1080x1920",
    "square": "square-1080",
    "story": "feed-1080x1350",
}

TABLE_OPS = {
    "dedupe": ("dedupe", "duplicate", "duplicates", "repeat"),
    "sort": ("sort",),
    "head": ("first rows", "pehli rows", "top rows"),
    "tail": ("last rows", "aakhri rows"),
    "drop-empty": ("empty rows", "khali rows"),
    "unique-values": ("unique", "distinct", "alag alag"),
    "sum-column": ("sum", "total", "jama"),
    "group-count": ("group", "ginti", "count by"),
}

TEXT_OPS = {
    "word-frequency": ("word frequency", "sabse zyada words", "word count by word", "frequent words"),
    "extract-emails": ("emails", "email addresses", "e-mail"),
    "extract-urls": ("urls", "links", "link nikaal"),
    "extract-hashtags": ("hashtags", "hashtag"),
    "stats": ("word count", "kitne words", "kitne characters", "text stats", "characters"),
    "slugify": ("slug",),
    "case-upper": ("uppercase", "upper case", "bade letters"),
    "case-lower": ("lowercase", "chhote letters"),
    "dedupe-lines": ("duplicate lines", "repeat lines"),
    "sort-lines": ("sort lines", "lines sort"),
    "trim-whitespace": ("extra spaces", "whitespace"),
    "json-validate": ("json valid", "validate json", "json check"),
    "text-hash": ("hash", "checksum"),
}

CODE_OPS = {
    "todos": ("todo", "todos", "pending work", "baaki kaam"),
    "secret-scan": ("secret", "password", "api key", "leak"),
    "symbols": ("function", "functions", "class", "classes", "symbol", "symbols"),
    "imports": ("import", "imports", "dependencies"),
    "complexity-hint": ("complexity", "mushkil code", "refactor"),
}

LANG_EXT = {"py": "python", "js": "javascript", "ts": "typescript", "go": "go", "rs": "rust",
            "java": "java", "rb": "ruby", "php": "php", "cs": "csharp", "swift": "swift",
            "kt": "kotlin", "sql": "sql", "sh": "bash"}

DOC_TOOLS = {
    "pdf": ("pdf", "pdf banao", "pdf bana do"),
    "docx": ("docx", "word file"),
    "html": ("html",),
    "xlsx": ("excel", "xlsx", "spreadsheet"),
    "txt": ("text file", "txt"),
}

RECIPE_WORDS = {
    "video-to-shorts-pack": ("shorts pack", "shorts ke liye pack", "shorts banao"),
    "podcast-pack": ("podcast pack", "podcast ke liye"),
    "release-check": ("release check", "release se pehle", "pre-release"),
    "repo-brief": ("repo brief", "repo ka brief", "repository brief"),
    "content-repurpose": ("repurpose", "caption", "titles banao", "hashtag banao"),
    "health-report": ("health report", "health batao", "system health", "sab theek hai"),
}


def _norm(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").lower()).strip()


def find_path(message: str) -> str | None:
    """Any file-looking token: absolute path, or name with a known extension."""

    known = sorted(VIDEO_EXT | AUDIO_EXT | IMAGE_EXT | TABLE_EXT |
                   {"py", "js", "ts", "go", "rs", "java", "rb", "php", "cs", "swift", "kt",
                    "sql", "sh", "md", "html", "txt", "docx", "pdf", "xlsx", "pptx"},
                   key=len, reverse=True)
    pattern = r"[~./\w\-]+\.(?:%s)\b" % "|".join(known)
    for match in re.finditer(pattern, message, re.IGNORECASE):
        candidate = match.group(0)
        if any(part in candidate for part in ("/", "\\", "~")) or Path(candidate).suffix:
            return candidate
    return None


def find_quoted_text(message: str) -> str | None:
    match = re.search(r"[`\"'](.+?)[`\"']", message, re.DOTALL)
    return match.group(1) if match else None


def _resolve(skill_id: str, args: dict[str, Any], confidence: float,
             why: str) -> dict[str, Any] | None:
    try:
        skills.get(skill_id)
    except KeyError:
        hits = skills.search(why, limit=1)["results"]
        if not hits or float(hits[0].get("score") or 0) < 8:
            return None
        skill_id = hits[0]["id"]
    return {"skill": skill_id, "args": args, "confidence": round(confidence, 2), "why": why}


def _words(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def plan(message: str) -> dict[str, Any] | None:
    """Sentence -> {skill, args, confidence, why} or None when nothing fits."""

    text = _norm(message)
    path = find_path(message)
    suffix = Path(path).suffix.lstrip(".").lower() if path else ""
    quoted = find_quoted_text(message)
    hit: dict[str, Any] | None = None

    # --- recipes first: they are the "do the whole job" answers --------------
    for recipe_id, words in RECIPE_WORDS.items():
        if _words(text, words):
            args: dict[str, Any] = {}
            if path:
                args["path"] = path
            found = _resolve(f"recipe.{recipe_id}", args, 0.9, words[0])
            if found:
                return found

    # --- video ---------------------------------------------------------------
    if suffix in VIDEO_EXT or _words(text, ("video", "clip", "film", "movie")):
        if suffix in VIDEO_EXT:
            source = suffix
            for platform_word, preset in PLATFORM_WORDS.items():
                if platform_word in text:
                    return _resolve(f"media.video.platform.{source}-to-{preset}",
                                    {"path": path, "platform": preset}, 0.9, platform_word)
            for word, preset in RESIZE_WORDS.items():
                if word in text:
                    return _resolve(f"media.video.resize.{source}-to-{preset}",
                                    {"path": path, "preset": preset}, 0.9, word)
            if _words(text, ("gif",)):
                return _resolve(f"media.video.gif.{source}", {"path": path}, 0.9, "gif")
            for op in ("mute", "grayscale", "reverse"):
                if op in text:
                    return _resolve(f"media.video.op.{source}.{op}", {"path": path, "op": op},
                                    0.85, op)
            if _words(text, ("rotate 90", "ghuma")):
                return _resolve(f"media.video.op.{source}.rotate-90",
                                {"path": path, "op": "rotate-90"}, 0.8, "rotate")
            if _words(text, ("trim", "cut", "kaat")):
                return _resolve(f"media.video.trim.{source}", {"path": path}, 0.8, "trim")
            if _words(text, ("probe", "info", "details", "resolution", "kitna bada")):
                return _resolve(f"media.probe.{source}", {"path": path}, 0.85, "probe")
            for target in TARGET_CONTAINERS:
                if re.search(rf"\b{target}\b", text) and target != source:
                    if target in AUDIO_EXT:
                        bitrate = "320k" if "320" in text else "192k"
                        return _resolve(f"media.audio.convert.{source}-to-{target}-{bitrate}",
                                        {"path": path, "target": target, "bitrate": bitrate},
                                        0.9, f"{source} to {target}")
                    codec = "vp9" if target in {"webm", "mkv"} and "av1" not in text else None
                    if "h265" in text or "hevc" in text:
                        codec = "h265"
                    if "av1" in text:
                        codec = "av1"
                    codec = codec or ("vp9" if target == "webm" else "h264")
                    return _resolve(
                        f"media.video.convert.{source}-to-{target}-{codec}",
                        {"path": path, "target": target, "codec": codec}, 0.9,
                        f"{source} to {target}")

    # --- audio ---------------------------------------------------------------
    if suffix in AUDIO_EXT:
        if _words(text, ("mono",)):
            return _resolve(f"media.audio.op.{suffix}.mono", {"path": path, "op": "mono"}, 0.85, "mono")
        if _words(text, ("normalize", "loud", "awaaz barabar")):
            return _resolve(f"media.audio.op.{suffix}.normalize",
                            {"path": path, "op": "normalize"}, 0.85, "normalize")
        if _words(text, ("trim silence", "khamoshi", "silence")):
            return _resolve(f"media.audio.op.{suffix}.trim-silence",
                            {"path": path, "op": "trim-silence"}, 0.85, "silence")
        for target in ("mp3", "wav", "m4a", "flac", "ogg"):
            if re.search(rf"\b{target}\b", text) and target != suffix:
                bitrate = "320k" if "320" in text else "192k"
                return _resolve(f"media.audio.convert.{suffix}-to-{target}-{bitrate}",
                                {"path": path, "target": target, "bitrate": bitrate}, 0.9,
                                f"{suffix} to {target}")

    # --- image ---------------------------------------------------------------
    if suffix in IMAGE_EXT:
        for width in (320, 512, 720, 1080, 1440, 1920):
            if str(width) in text and _words(text, ("resize", "chhota", "bada", "width", "px")):
                return _resolve(f"media.image.resize.{suffix}-to-{width}",
                                {"path": path, "width": width}, 0.9, f"resize {width}")
        for op in ("grayscale", "blur", "sharpen", "flip-horizontal", "rotate-90"):
            if op.split("-")[0] in text:
                return _resolve(f"media.image.op.{suffix}.{op}", {"path": path, "op": op},
                                0.85, op)
        for target in ("jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "pdf"):
            if re.search(rf"\b{target}\b", text) and target != suffix:
                quality = 70 if _words(text, ("compress", "chhota size", "kam size")) else 85
                return _resolve(f"media.image.convert.{suffix}-to-{target}-q{quality}",
                                {"path": path, "target": target, "quality": quality}, 0.9,
                                f"{suffix} to {target}")

    # --- tables --------------------------------------------------------------
    if suffix in TABLE_EXT or (quoted and "," in (quoted or "")) or speech_csv(text):
        fmt = suffix if suffix in TABLE_EXT else "csv"
        data = None if path else (quoted or speech_csv(text))
        base: dict[str, Any] = {"path": path} if path else ({"data": data} if data else {})
        base["format"] = fmt
        if _words(text, ("sql", "query", "select")):
            analysis = "count" if _words(text, ("count", "kitni rows", "ginti")) else "sample"
            return _resolve(f"data.table.sql.{analysis}.{fmt}", {**base, "analysis": analysis},
                            0.8, "sql")
        for op, words in TABLE_OPS.items():
            if _words(text, words):
                return _resolve(f"data.table.op.{op}.{fmt}", {**base, "op": op}, 0.85, words[0])
        for target in ("json", "jsonl", "tsv", "sqlite", "csv"):
            if re.search(rf"\b{target}\b", text) and target != fmt:
                return _resolve(f"data.table.convert.{fmt}-to-{target}",
                                {**base, "to": target}, 0.85, f"{fmt} to {target}")

    # --- text ----------------------------------------------------------------
    if quoted or _words(text, ("text", "likha", "paragraph", "sentence")):
        payload: dict[str, Any] = {}
        if quoted:
            payload["text"] = quoted
        elif path:
            payload["path"] = path
        mode = "inline" if quoted else ("file" if path else "inline")
        if payload:
            for op, words in TEXT_OPS.items():
                if _words(text, words):
                    return _resolve(f"text.{op}.{mode}", payload, 0.8, words[0])

    # --- code ----------------------------------------------------------------
    lang = LANG_EXT.get(suffix)
    if lang and (_words(text, ("file", "code", "check", "scan", "dekh")) or
                 _words(text, tuple(w for words in CODE_OPS.values() for w in words))):
        for op, words in CODE_OPS.items():
            if _words(text, words):
                return _resolve(f"code.{lang}.{op}", {"path": path, "op": op}, 0.85, words[0])

    # --- docs ----------------------------------------------------------------
    if _words(text, ("pdf", "docx", "word file", "html", "excel", "xlsx")):
        for target in ("pdf", "docx", "html", "xlsx", "txt", "md"):
            if re.search(rf"\b{target}\b", text):
                source = suffix or "md"
                if source != target:
                    return _resolve(f"docs.convert.{source}-to-{target}",
                                    {"path": path, "target": target}, 0.75, f"{source} to {target}")

    return hit


def speech_csv(text: str) -> str | None:
    """'a,b\\nc,d' typed straight into the chat — treat it as CSV data."""

    match = re.search(r"((?:[^\s,]+,){1,}[^\s,]+\s*\n\s*(?:[^\s,]+,)+[^\s,]+)", text)
    return match.group(1).strip() if match else None


def describe(plan_dict: dict[str, Any] | None) -> str:
    if not plan_dict:
        return "koi skill match nahi hui"
    return f"{plan_dict['skill']} ({int(plan_dict['confidence'] * 100)}% match — {plan_dict['why']})"
