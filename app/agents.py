"""Runnable agents: deterministic specialists that work with zero keys, plus a few
model-backed ones that fail honestly when no model is configured.

The 42 entries in ``catalog/agents.json`` are *blueprints* — they describe what an agent
would do and which worker service would execute it. Nothing in that file can run here.
This module is the other half: agents that actually execute, in-process, using the
toolkit this backend already ships (ffmpeg, the code index, BM25, metrics, backups).

Two rules kept throughout:

* **No pretending.** A rule-based agent says it is rule-based in ``engine``. An agent that
  needs a model reports that clearly instead of emitting filler text.
* **No hidden writes.** Agents that touch disk or git are marked ``write`` and are also
  listed in the approval-gated set when ``UAI_REQUIRE_APPROVAL=1``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import backup, code_assistant, deps_audit, git_tools, governance, health_deep, jobs, obs
from . import tool_search, video_tools

REPO_ROOT = Path(__file__).resolve().parent.parent


class AgentError(RuntimeError):
    """Bad input, unavailable dependency, or an honest 'cannot do that here'."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Agent:
    id: str
    name: str
    category: str
    description: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    inputs: dict[str, str] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    risk: str = "low"            # low | medium | high
    engine: str = "rules"        # rules | ffmpeg | index | model
    writes: bool = False         # touches disk/git
    async_safe: bool = True      # ok to run through the job queue


AGENTS: dict[str, Agent] = {}


def agent(**meta: Any) -> Callable[[Callable], Callable]:
    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]):
        entry = Agent(handler=func, **meta)
        AGENTS[entry.id] = entry
        return func

    return decorator


def _need(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise AgentError(f"'{key}' is required for this agent")
    return value


def _model(system: str, user: str) -> dict[str, Any]:
    """Ask the configured model, or explain honestly why nothing can be answered."""

    from . import ai_router

    try:
        result = ai_router.complete(system=system, user=user)
    except RuntimeError as exc:
        raise AgentError(
            f"this agent needs a model and none is configured — {exc}", status=422
        ) from exc
    return {"text": result.get("text", ""), "provider": result.get("provider"), "model": result.get("model")}


# --------------------------------------------------------------------------- #
# Code & repository agents
# --------------------------------------------------------------------------- #

@agent(
    id="repo-scout",
    name="Repo Scout",
    category="code",
    description="Maps the repository: file counts, languages, largest files, entry points.",
    inputs={"prefix": "optional path prefix, e.g. app/"},
    engine="index",
    tools=["/v1/code/tree", "/v1/code/index"],
)
def repo_scout(payload: dict[str, Any]) -> dict[str, Any]:
    tree = code_assistant.tree(prefix=payload.get("prefix") or None, max_entries=5000)
    files = tree["files"]
    languages: dict[str, int] = {}
    biggest: list[dict[str, Any]] = []
    for entry in files:
        languages[entry.get("language") or "other"] = languages.get(entry.get("language") or "other", 0) + 1
        biggest.append({"path": entry["path"], "bytes": entry.get("bytes", 0)})
    biggest.sort(key=lambda item: -item["bytes"])
    return {
        "total_files": tree["total_files"],
        "languages": dict(sorted(languages.items(), key=lambda pair: -pair[1])[:10]),
        "largest": biggest[:5],
        "entry_points": [p for p in ("app/main.py", "api/index.py", "workers/", "deploy/")
                         if (REPO_ROOT / p).exists()],
    }


@agent(
    id="code-reviewer",
    name="Code Reviewer",
    category="code",
    description="Static review of a file or the whole tree: unused imports, long lines, TODOs, risky patterns.",
    inputs={"path": "file or directory (default: app/)"},
    engine="rules",
    tools=["/v1/code/review"],
)
def code_reviewer(payload: dict[str, Any]) -> dict[str, Any]:
    path = str(payload.get("path") or "app/")
    result = code_assistant.review(paths=[path], limit=400)
    return {
        "path": path,
        "findings": result["findings"][:25],
        "total_findings": len(result["findings"]),
        "by_severity": result.get("by_severity", {}),
    }


@agent(
    id="test-planner",
    name="Test Planner",
    category="code",
    description="Suggests concrete pytest cases for a module by reading its public functions.",
    inputs={"path": "python file, e.g. app/video_tools.py"},
    required=["path"],
    engine="rules",
    tools=["/v1/code/tests"],
)
def test_planner(payload: dict[str, Any]) -> dict[str, Any]:
    return code_assistant.test_scaffold(_need(payload, "path"))


@agent(
    id="refactor-planner",
    name="Refactor Planner",
    category="code",
    description="Turns a goal into ordered, testable steps grounded in the repo's own files.",
    inputs={"goal": "what you want to change"},
    required=["goal"],
    engine="rules",
    tools=["/v1/code/plan"],
)
def refactor_planner(payload: dict[str, Any]) -> dict[str, Any]:
    return code_assistant.plan(_need(payload, "goal"))


@agent(
    id="python-compiler",
    name="Python Compiler",
    category="code",
    description="Compiles every module to catch syntax errors before a deploy.",
    engine="rules",
    tools=["compileall"],
)
def python_compiler(payload: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [os.sys.executable, "-m", "compileall", "-q", str(REPO_ROOT / "app"),
         str(REPO_ROOT / "api"), str(REPO_ROOT / "videoengine")],
        capture_output=True, text=True, timeout=120,
    )
    return {
        "ok": result.returncode == 0,
        "errors": (result.stderr or result.stdout).strip().splitlines()[:10],
    }


@agent(
    id="changelog-writer",
    name="Changelog Writer",
    category="code",
    description="Builds a changelog grouped by feat/fix/docs from real git history.",
    inputs={"limit": "how many commits (default 20)"},
    engine="rules",
    tools=["/v1/git/log"],
)
def changelog_writer(payload: dict[str, Any]) -> dict[str, Any]:
    limit = min(int(payload.get("limit") or 20), 100)
    commits = git_tools.log(limit=limit)["commits"]
    buckets: dict[str, list[str]] = {}
    for commit in commits:
        subject = commit["subject"]
        kind = subject.split(":", 1)[0].strip() if ":" in subject else "other"
        kind = kind if kind in {"feat", "fix", "docs", "test", "chore", "refactor", "perf"} else "other"
        buckets.setdefault(kind, []).append(f"- {subject} ({commit['sha']})")
    markdown = "\n".join(
        f"### {name}\n" + "\n".join(items) for name, items in sorted(buckets.items())
    )
    return {"commits": len(commits), "buckets": {k: len(v) for k, v in buckets.items()}, "markdown": markdown}


@agent(
    id="release-notes",
    name="Release Notes",
    category="code",
    description="Customer-facing release notes from the last N commits, with a version stamp.",
    inputs={"version": "optional label, e.g. 0.7.0"},
    engine="rules",
    tools=["/v1/git/log"],
)
def release_notes(payload: dict[str, Any]) -> dict[str, Any]:
    version = str(payload.get("version") or time.strftime("%Y.%m.%d"))
    commits = git_tools.log(limit=25)["commits"]
    highlights = [c["subject"] for c in commits if c["subject"].startswith(("feat", "fix"))][:10]
    return {
        "version": version,
        "highlights": highlights,
        "markdown": f"## {version}\n\n" + "\n".join(f"* {item}" for item in highlights),
    }


@agent(
    id="import-auditor",
    name="Import Auditor",
    category="code",
    description="Compares requirements.txt with what the source actually imports.",
    engine="rules",
    tools=["/v1/audit/dependencies"],
)
def import_auditor(payload: dict[str, Any]) -> dict[str, Any]:
    report = deps_audit.audit(REPO_ROOT, REPO_ROOT / "requirements.txt")
    return {
        "declared": report["declared"],
        "unused": [entry["name"] for entry in report["declared_but_not_imported"]],
        "undeclared": [entry["module"] for entry in report["imported_but_not_declared"]],
        "verdict": deps_audit.verdict(report),
    }


@agent(
    id="route-guard",
    name="Route Guard",
    category="code",
    description="Checks that every endpoint the editor UI calls really exists in the schema.",
    engine="rules",
    tools=["/openapi.json", "app/editor_assets.py"],
)
def route_guard(payload: dict[str, Any]) -> dict[str, Any]:
    from .editor_assets import EDITOR_HTML
    from .main import app

    known = {path.rstrip("/") for path in app.openapi()["paths"]}
    raw_calls = set(re.findall(r"['\"`](/v1/[a-zA-Z0-9_\-/{}.]+)", EDITOR_HTML))

    def normalise(path: str) -> str:
        """UI builds URLs by concatenation, so strip ids, template tails and slashes."""

        cleaned = path.split("?")[0]
        for marker in ("{", "$"):
            cleaned = cleaned.split(marker)[0]
        return cleaned.rstrip("/")

    called = {normalise(path) for path in raw_calls}
    missing = sorted(path for path in called if path and path not in known)
    return {
        "ui_calls": len(called),
        "schema_paths": len(known),
        "missing": missing,
        "ok": not missing,
    }


@agent(
    id="doc-writer",
    name="Doc Writer",
    category="code",
    description="Generates a Markdown reference for one route group from the live schema.",
    inputs={"prefix": "route prefix, e.g. /v1/video"},
    engine="index",
    tools=["/openapi.json"],
)
def doc_writer(payload: dict[str, Any]) -> dict[str, Any]:
    from .main import app

    prefix = str(payload.get("prefix") or "/v1")
    lines = [f"# {prefix}", ""]
    count = 0
    for path, operations in sorted(app.openapi()["paths"].items()):
        if not path.startswith(prefix):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            summary = operation.get("summary") or ""
            lines.append(f"- `{method.upper()} {path}` — {summary}")
            count += 1
    return {"routes": count, "markdown": "\n".join(lines)}


# --------------------------------------------------------------------------- #
# Video & media agents (ffmpeg, zero keys)
# --------------------------------------------------------------------------- #

@agent(
    id="media-prober",
    name="Media Prober",
    category="video",
    description="Reads true metadata: duration, resolution, codecs, bitrate, tracks.",
    inputs={"path": "media file"},
    required=["path"],
    engine="ffmpeg",
    tools=["/v1/video/probe"],
)
def media_prober(payload: dict[str, Any]) -> dict[str, Any]:
    return video_tools.probe_media(video_tools.resolve_input(_need(payload, "path")))


@agent(
    id="video-editor",
    name="Video Editor",
    category="video",
    description="Cuts silence out of a recording and reports exactly how much was removed.",
    inputs={"path": "video file", "threshold": "optional dB threshold"},
    required=["path"],
    engine="ffmpeg",
    tools=["/v1/video/cut-silence"],
    risk="medium",
)
def video_editor(payload: dict[str, Any]) -> dict[str, Any]:
    # video_tools resolves and validates the path itself, so hand it the raw string.
    threshold = payload.get("threshold")
    return video_tools.cut_silence(
        _need(payload, "path"),
        threshold_db=float(threshold) if threshold is not None else -30.0,
    )


@agent(
    id="chapter-writer",
    name="Chapter Writer",
    category="video",
    description="Detects scene changes and writes YouTube-style chapters as Markdown.",
    inputs={"path": "video file"},
    required=["path"],
    engine="ffmpeg",
    tools=["/v1/video/chapters"],
)
def chapter_writer(payload: dict[str, Any]) -> dict[str, Any]:
    result = video_tools.chapters(_need(payload, "path"))
    markdown = "\n".join(
        f"{chapter['timestamp']} {chapter.get('title') or chapter.get('suggestion') or 'Chapter'}"
        for chapter in result["chapters"]
    )
    return {**result, "markdown": markdown}


@agent(
    id="thumbnail-designer",
    name="Thumbnail Designer",
    category="video",
    description="Extracts candidate thumbnails from the busiest parts of a video.",
    inputs={"path": "video file", "count": "how many (default 3)"},
    required=["path"],
    engine="ffmpeg",
    tools=["/v1/video/thumbnails"],
)
def thumbnail_designer(payload: dict[str, Any]) -> dict[str, Any]:
    return video_tools.thumbnails(_need(payload, "path"), count=min(int(payload.get("count") or 3), 12))


@agent(
    id="loudness-master",
    name="Loudness Master",
    category="video",
    description="Normalises audio to broadcast loudness (-16 LUFS) for consistent uploads.",
    inputs={"path": "audio/video file"},
    required=["path"],
    engine="ffmpeg",
    tools=["/v1/video/loudnorm"],
)
def loudness_master(payload: dict[str, Any]) -> dict[str, Any]:
    return video_tools.loudnorm(_need(payload, "path"))


@agent(
    id="clip-maker",
    name="Clip Maker",
    category="video",
    description="Exports a vertical 9:16 clip for Shorts/Reels from a time range.",
    inputs={"path": "video file", "start": "seconds", "end": "seconds"},
    required=["path", "start", "end"],
    engine="ffmpeg",
    tools=["/v1/video/clip"],
    risk="medium",
)
def clip_maker(payload: dict[str, Any]) -> dict[str, Any]:
    start = _need(payload, "start")
    end = _need(payload, "end")
    if float(end) <= float(start):
        raise AgentError("'end' must be greater than 'start'")
    return video_tools.vertical_clip(_need(payload, "path"), float(start), float(end))


@agent(
    id="subtitle-smith",
    name="Subtitle Smith",
    category="video",
    description="Converts subtitles between SRT and WebVTT without losing timing.",
    inputs={"path": "subtitle file", "to": "srt or vtt"},
    required=["path"],
    engine="rules",
    tools=["/v1/video/subtitles"],
)
def subtitle_smith(payload: dict[str, Any]) -> dict[str, Any]:
    return video_tools.convert_subtitles(_need(payload, "path"), target=str(payload.get("to") or "vtt"))


@agent(
    id="publish-packager",
    name="Publish Packager",
    category="video",
    description="Builds one upload manifest: metadata, chapters, thumbnail, subtitle, loudness.",
    inputs={"path": "video file", "title": "optional working title"},
    required=["path"],
    engine="ffmpeg",
    tools=["/v1/video/probe", "/v1/video/chapters", "/v1/video/thumbnails"],
)
def publish_packager(payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = _need(payload, "path")
    source = video_tools.resolve_input(raw_path)
    info = video_tools.probe_media(source)
    chapters = video_tools.chapters(raw_path)["chapters"]
    thumbs = video_tools.thumbnails(raw_path, count=2)["thumbnails"]
    title = str(payload.get("title") or source.stem.replace("_", " ").title())
    return {
        "title": title,
        "duration": info["duration"],
        "resolution": f"{info.get('width')}x{info.get('height')}",
        "chapters": chapters,
        "thumbnails": thumbs,
        "manifest": {
            "title": title,
            "duration_seconds": info["duration"],
            "chapter_markdown": "\n".join(
                f"{chapter['timestamp']} {chapter.get('title') or chapter.get('suggestion') or 'Chapter'}"
                for chapter in chapters
            ),
        },
    }


# --------------------------------------------------------------------------- #
# Ops agents
# --------------------------------------------------------------------------- #

@agent(
    id="health-warden",
    name="Health Warden",
    category="ops",
    description="Runs the deep probe and explains anything degraded in plain language.",
    engine="rules",
    tools=["/health/deep"],
)
def health_warden(payload: dict[str, Any]) -> dict[str, Any]:
    report = health_deep.probe()
    advice = []
    for check in report["checks"]:
        if check["ok"]:
            continue
        advice.append(f"{check['name']}: {check['detail']}")
    return {
        "status": report["status"],
        "failures": report["critical_failed"],
        "warnings": report["warnings"],
        "advice": advice,
        "checks": report["checks"],
    }


@agent(
    id="backup-keeper",
    name="Backup Keeper",
    category="ops",
    description="Creates and verifies a data backup, then reports its checksum.",
    inputs={"include_media": "true/false", "label": "optional label"},
    engine="rules",
    tools=["/v1/data/backup", "/v1/data/verify"],
    writes=True,
    risk="medium",
)
def backup_keeper(payload: dict[str, Any]) -> dict[str, Any]:
    created = backup.create_backup(
        include_media=bool(payload.get("include_media")),
        label=str(payload.get("label") or "agent"),
    )
    verified = backup.verify_backup(created["name"])
    return {"created": created, "verified": verified}


@agent(
    id="job-runner",
    name="Job Runner",
    category="ops",
    description="Drains queued jobs (bounded) — the cron tick for serverless deployments.",
    inputs={"max": "how many jobs to run (default 5)"},
    engine="rules",
    tools=["/v1/jobs/run-once"],
    writes=True,
)
def job_runner(payload: dict[str, Any]) -> dict[str, Any]:
    budget = min(int(payload.get("max") or 5), 50)
    worked = 0
    for _ in range(budget):
        if not jobs.run_once():
            break
        worked += 1
    return {"ran": worked, "queue": jobs.stats()["counts"]}


@agent(
    id="metrics-reporter",
    name="Metrics Reporter",
    category="ops",
    description="Summarises traffic, latency and the busiest route groups.",
    engine="rules",
    tools=["/metrics", "/v1/observability/summary"],
)
def metrics_reporter(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = obs.snapshot()
    slowest = sorted(snapshot["avg_latency_ms"].items(), key=lambda pair: -pair[1])[:5]
    return {
        "uptime_seconds": snapshot["uptime_seconds"],
        "requests": snapshot["requests"],
        "slowest_routes": slowest,
        "peak_inflight": snapshot["peak_inflight"],
    }


@agent(
    id="audit-reader",
    name="Audit Reader",
    category="ops",
    description="Reads the append-only audit log and groups it by action and outcome.",
    inputs={"limit": "entries (default 100)"},
    engine="rules",
    tools=["/v1/governance/audit"],
)
def audit_reader(payload: dict[str, Any]) -> dict[str, Any]:
    log = governance.read_log(limit=min(int(payload.get("limit") or 100), 500))
    by_action: dict[str, int] = {}
    by_actor: dict[str, int] = {}
    failures = 0
    for entry in log["entries"]:
        by_action[entry["action"]] = by_action.get(entry["action"], 0) + 1
        by_actor[entry["actor"]] = by_actor.get(entry["actor"], 0) + 1
        if entry["outcome"].startswith("error"):
            failures += 1
    return {"entries": log["count"], "by_action": by_action, "by_actor": by_actor, "failures": failures}


@agent(
    id="sdk-builder",
    name="SDK Builder",
    category="ops",
    description="Regenerates a typed client SDK from the live schema.",
    inputs={"lang": "python or ts", "save_to": "optional repo path"},
    engine="index",
    tools=["/v1/sdk"],
    writes=True,
    risk="medium",
)
def sdk_builder(payload: dict[str, Any]) -> dict[str, Any]:
    from . import sdk as sdk_generator
    from .main import app

    language = str(payload.get("lang") or "python")
    code = (
        sdk_generator.generate_typescript(app, payload.get("prefix"))
        if language in {"ts", "typescript"}
        else sdk_generator.generate_python(app, payload.get("prefix"))
    )
    saved = None
    if payload.get("save_to"):
        saved = code_assistant.write_file(str(payload["save_to"]), code, dry_run=False)["path"]
    return {"language": language, "bytes": len(code.encode()), "saved_to": saved}


@agent(
    id="tool-scout",
    name="Tool Scout",
    category="discovery",
    description="Finds repositories or endpoints that can do a described job (BM25).",
    inputs={"query": "what you need", "target": "tools or routes"},
    required=["query"],
    engine="rules",
    tools=["/v1/tools/search", "/v1/tools/routes"],
)
def tool_scout(payload: dict[str, Any]) -> dict[str, Any]:
    query = _need(payload, "query")
    if str(payload.get("target") or "tools") == "routes":
        from .main import app

        return tool_search.search_routes(query, app.openapi(), limit=10)
    return tool_search.search_tools(query, limit=10)


@agent(
    id="api-cartographer",
    name="API Cartographer",
    category="discovery",
    description="Maps the API surface by area with counts and sample routes.",
    engine="index",
    tools=["/v1/tools/capabilities"],
)
def api_cartographer(payload: dict[str, Any]) -> dict[str, Any]:
    return tool_search.capabilities()


@agent(
    id="capacity-planner",
    name="Capacity Planner",
    category="ops",
    description="Compares disk, queue depth and limits, then recommends what to change.",
    engine="rules",
    tools=["/health/deep", "/v1/jobs/stats"],
)
def capacity_planner(payload: dict[str, Any]) -> dict[str, Any]:
    report = health_deep.probe()
    disk = next((c for c in report["checks"] if c["name"] == "disk"), {})
    queue = jobs.stats()
    counts = queue["counts"]
    notes = []
    if counts.get("queued", 0) > 50:
        notes.append("queue is backing up — add workers or slow submissions")
    if counts.get("failed", 0) > 5:
        notes.append("several failed jobs — read /v1/jobs?status=failed for tracebacks")
    if "GB free" in disk.get("detail", ""):
        free = float(disk["detail"].split(" GB")[0])
        if free < 2:
            notes.append("low disk: trim renders or move data to a bigger volume")
    return {"disk": disk.get("detail"), "queue": counts, "recommendations": notes or ["no action needed"]}


# --------------------------------------------------------------------------- #
# Content agents (rule-based: they compose, they do not invent facts)
# --------------------------------------------------------------------------- #

STOP = {"the", "a", "an", "of", "for", "and", "to", "in", "on", "with", "how", "my"}


def _keywords(text: str, limit: int = 8) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2]
    seen: dict[str, int] = {}
    for word in words:
        seen[word] = seen.get(word, 0) + 1
    return [word for word, _ in sorted(seen.items(), key=lambda pair: -pair[1])][:limit]


@agent(
    id="seo-planner",
    name="SEO Planner",
    category="content",
    description="Builds titles, description and tags from a topic using search-shaped rules.",
    inputs={"topic": "video or page topic"},
    required=["topic"],
    engine="rules",
)
def seo_planner(payload: dict[str, Any]) -> dict[str, Any]:
    topic = _need(payload, "topic")
    keys = _keywords(topic)
    titles = [
        f"{topic.title()} — full guide",
        f"How to {topic.lower()} (step by step)",
        f"{topic.title()}: what actually works in 2026",
        f"{topic.title()} for beginners",
    ]
    return {
        "topic": topic,
        "titles": titles,
        "description": (
            f"{topic.title()} explained end to end. Covers {', '.join(keys[:4]) or 'the essentials'} "
            f"with worked examples.\n\nChapters and resources below."
        ),
        "tags": keys + ["tutorial", "guide"],
        "note": "rule-based suggestions, not keyword-volume data (that needs a paid API)",
    }


@agent(
    id="title-suggester",
    name="Title Suggester",
    category="content",
    description="Ten title variants across curiosity, listicle and how-to shapes.",
    inputs={"topic": "subject", "count": "how many (default 10)"},
    required=["topic"],
    engine="rules",
)
def title_suggester(payload: dict[str, Any]) -> dict[str, Any]:
    topic = _need(payload, "topic").strip()
    count = min(int(payload.get("count") or 10), 20)
    shapes = [
        "{t} — the honest guide",
        "I tried {t}: here's what broke",
        "{t} in 10 minutes",
        "7 things nobody tells you about {t}",
        "Why {t} keeps failing (and the fix)",
        "{t} vs the alternative",
        "Beginner to confident with {t}",
        "{t}: free tools that actually work",
        "The 2026 way to do {t}",
        "{t} — mistakes to avoid",
    ]
    return {"topic": topic, "titles": [shape.format(t=topic) for shape in shapes[:count]]}


@agent(
    id="hashtag-smith",
    name="Hashtag Smith",
    category="content",
    description="Derives hashtags from the topic words, deduplicated and platform-safe.",
    inputs={"topic": "subject"},
    required=["topic"],
    engine="rules",
)
def hashtag_smith(payload: dict[str, Any]) -> dict[str, Any]:
    topic = _need(payload, "topic")
    keys = _keywords(topic, limit=6)
    tags = []
    for key in keys:
        tags.append("#" + re.sub(r"[^a-z0-9]", "", key))
    tags += ["#" + re.sub(r"[^a-z0-9]", "", topic.lower().replace(" ", ""))[:24]] if keys else []
    unique = list(dict.fromkeys(tag for tag in tags if len(tag) > 2))
    return {"topic": topic, "hashtags": unique[:12], "count": len(unique[:12])}


@agent(
    id="description-writer",
    name="Description Writer",
    category="content",
    description="Writes an upload description with chapters, links and a summary block.",
    inputs={"topic": "subject", "chapters": "optional list of 'timestamp title'"},
    required=["topic"],
    engine="rules",
)
def description_writer(payload: dict[str, Any]) -> dict[str, Any]:
    topic = _need(payload, "topic")
    chapters = payload.get("chapters") or []
    body = [f"{topic.title()}", "", "In this video:", ""]
    body += [f"- {chapter}" if isinstance(chapter, str) else f"- {chapter}" for chapter in chapters] or ["- (add chapters)"]
    body += ["", "Subscribe for more practical walkthroughs.", "", "Timestamps:", ""]
    body += [str(chapter) for chapter in chapters] or ["00:00 Intro"]
    return {"description": "\n".join(body), "characters": len("\n".join(body))}


@agent(
    id="schedule-planner",
    name="Schedule Planner",
    category="content",
    description="Lays out a two-week posting calendar from a cadence you choose.",
    inputs={"cadence": "per_week (default 3)", "start": "YYYY-MM-DD"},
    engine="rules",
)
def schedule_planner(payload: dict[str, Any]) -> dict[str, Any]:
    cadence = max(1, min(int(payload.get("cadence") or 3), 14))
    start_raw = str(payload.get("start") or time.strftime("%Y-%m-%d"))
    try:
        start = time.strptime(start_raw, "%Y-%m-%d")
    except ValueError as exc:
        raise AgentError("'start' must look like 2026-11-05") from exc
    base = time.mktime(start)
    slots = []
    step_days = max(1, 7 // cadence)
    for index in range(cadence * 2):
        stamp = time.localtime(base + index * step_days * 86400)
        slots.append({
            "date": time.strftime("%Y-%m-%d", stamp),
            "weekday": time.strftime("%A", stamp),
            "slot": index + 1,
        })
    return {"cadence_per_week": cadence, "slots": slots, "note": "submit times still need your audience data"}


@agent(
    id="brand-namer",
    name="Brand Namer",
    category="content",
    description="Generates pronounceable name candidates from a seed word (deterministic).",
    inputs={"seed": "word or two", "count": "how many (default 8)"},
    required=["seed"],
    engine="rules",
)
def brand_namer(payload: dict[str, Any]) -> dict[str, Any]:
    seed = re.sub(r"[^a-zA-Z]", "", _need(payload, "seed"))[:8] or "studio"
    count = min(int(payload.get("count") or 8), 20)
    suffixes = ["lab", "haus", "works", "forge", "flow", "kit", "loop", "craft"]
    prefixes = ["go", "neo", "up", "open", "day", "mini"]
    names = [f"{seed.lower()}{suffix}" for suffix in suffixes]
    names += [f"{prefix}{seed.lower()}" for prefix in prefixes]
    names = list(dict.fromkeys(names))[:count]
    return {"seed": seed, "names": names, "checked_availability": False,
            "note": "domain/handle availability needs a registrar API — not checked here"}


# --------------------------------------------------------------------------- #
# Model-backed agents (honest failure without a model)
# --------------------------------------------------------------------------- #

@agent(
    id="summarizer",
    name="Summarizer",
    category="model",
    description="Summarises text with the configured model (Ollama is free).",
    inputs={"text": "content to summarise", "sentences": "target length"},
    required=["text"],
    engine="model",
    async_safe=False,
)
def summarizer(payload: dict[str, Any]) -> dict[str, Any]:
    text = _need(payload, "text")[:8000]
    target = int(payload.get("sentences") or 5)
    return _model(
        "You are a precise summariser. Return only the summary.",
        f"Summarise in {target} sentences:\n\n{text}",
    )


@agent(
    id="translator",
    name="Translator",
    category="model",
    description="Translates text with the configured model, keeping formatting.",
    inputs={"text": "content", "language": "target language"},
    required=["text", "language"],
    engine="model",
    async_safe=False,
)
def translator(payload: dict[str, Any]) -> dict[str, Any]:
    return _model(
        "You are a translator. Preserve markdown and line breaks. Output only the translation.",
        f"Translate to {_need(payload, 'language')}:\n\n{_need(payload, 'text')[:8000]}",
    )


@agent(
    id="copywriter",
    name="Copywriter",
    category="model",
    description="Writes short marketing copy with the configured model.",
    inputs={"brief": "what to sell/write", "tone": "optional tone"},
    required=["brief"],
    engine="model",
    async_safe=False,
)
def copywriter(payload: dict[str, Any]) -> dict[str, Any]:
    tone = str(payload.get("tone") or "direct, warm, concrete")
    return _model(
        f"You are a copywriter. Tone: {tone}. No clichés, no filler.",
        _need(payload, "brief")[:4000],
    )


@agent(
    id="code-explainer",
    name="Code Explainer",
    category="model",
    description="Explains a file line by line using the configured model.",
    inputs={"path": "file in the repo"},
    required=["path"],
    engine="model",
    async_safe=False,
)
def code_explainer(payload: dict[str, Any]) -> dict[str, Any]:
    source = code_assistant.read_file(_need(payload, "path"))
    return _model(
        "You are a senior engineer. Explain the code for a new teammate, then flag risks.",
        f"File: {source['path']}\n\n{source['content'][:8000]}",
    )


# --------------------------------------------------------------------------- #
# JARVIS layer (memory + planning + chat), exposed here so the editor lists it
# --------------------------------------------------------------------------- #

@agent(
    id="jarvis-chat",
    name="JARVIS",
    category="ops",
    description="Chat with memory and tools: understands a goal, runs the right agents, remembers you.",
    inputs={"message": "what you want", "session": "optional session id"},
    required=["message"],
    engine="rules",
    async_safe=False,
    tools=["/v1/jarvis/chat"],
)
def jarvis_chat(payload: dict[str, Any]) -> dict[str, Any]:
    from . import jarvis

    return jarvis.chat(_need(payload, "message"), session=str(payload.get("session") or "default"))


@agent(
    id="memory-keeper",
    name="Memory Keeper",
    category="ops",
    description="Stores and recalls facts about you (SQLite, survives restarts).",
    inputs={"action": "remember | recall | forget | list", "key": "fact name", "query": "search text"},
    engine="rules",
    tools=["/v1/jarvis/memory"],
)
def memory_keeper(payload: dict[str, Any]) -> dict[str, Any]:
    from . import jarvis

    action = str(payload.get("action") or "list").lower()
    if action == "remember":
        return jarvis.remember(_need(payload, "key"), _need(payload, "value"))
    if action == "forget":
        return jarvis.forget(_need(payload, "key"))
    if action == "recall":
        return {"results": jarvis.recall(_need(payload, "query"))}
    return {"count": len(jarvis.facts()), "facts": jarvis.facts()}


@agent(
    id="goal-planner",
    name="Goal Planner",
    category="ops",
    description="Shows which agents would run for a goal, without running them.",
    inputs={"goal": "what you want to achieve"},
    required=["goal"],
    engine="rules",
    tools=["/v1/jarvis/plan"],
)
def goal_planner(payload: dict[str, Any]) -> dict[str, Any]:
    from . import jarvis

    return jarvis.plan(_need(payload, "goal"))


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #

def list_agents(category: str | None = None, engine: str | None = None) -> dict[str, Any]:
    entries = []
    for agent_entry in sorted(AGENTS.values(), key=lambda item: (item.category, item.id)):
        if category and agent_entry.category != category:
            continue
        if engine and agent_entry.engine != engine:
            continue
        entries.append(describe(agent_entry.id))
    return {
        "count": len(entries),
        "total": len(AGENTS),
        "categories": categories(),
        "agents": entries,
    }


def categories() -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in AGENTS.values():
        counts[entry.category] = counts.get(entry.category, 0) + 1
    return dict(sorted(counts.items()))


def describe(agent_id: str) -> dict[str, Any]:
    entry = AGENTS.get(agent_id)
    if entry is None:
        raise AgentError(f"unknown agent: {agent_id}", status=404)
    return {
        "id": entry.id,
        "name": entry.name,
        "category": entry.category,
        "description": entry.description,
        "inputs": entry.inputs,
        "required": entry.required,
        "tools": entry.tools,
        "risk": entry.risk,
        "engine": entry.engine,
        "writes": entry.writes,
        "async_safe": entry.async_safe,
        "needs_model": entry.engine == "model",
    }


def run(agent_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one agent, timing it and logging the run."""

    entry = AGENTS.get(agent_id)
    if entry is None:
        raise AgentError(f"unknown agent: {agent_id}", status=404)

    payload = payload or {}
    for key in entry.required:
        if not str(payload.get(key) or "").strip():
            raise AgentError(f"'{key}' is required for agent {agent_id}")

    started = time.perf_counter()
    try:
        result = entry.handler(payload) or {}
        outcome = "ok"
    except AgentError:
        raise
    except video_tools.VideoToolError as exc:
        # e.g. "file has no audio track" — the caller's input, not a server fault.
        raise AgentError(str(exc), status=422) from exc
    except Exception as exc:  # noqa: BLE001 - surface as an agent error, keep the API alive
        governance.record("agent.failed", target=agent_id, outcome="error",
                          detail={"error": f"{type(exc).__name__}: {exc}"[:300]})
        raise AgentError(f"{type(exc).__name__}: {exc}", status=500) from exc

    elapsed = round((time.perf_counter() - started) * 1000, 2)
    governance.record("agent.run", target=agent_id, outcome=outcome,
                      detail={"ms": elapsed, "engine": entry.engine})
    return {
        "agent": agent_id,
        "name": entry.name,
        "engine": entry.engine,
        "elapsed_ms": elapsed,
        "result": result,
    }


def crew(agent_ids: list[str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run agents in sequence, feeding each one the previous result as ``context``."""

    if not agent_ids:
        raise AgentError("crew needs at least one agent id")
    unknown = [identifier for identifier in agent_ids if identifier not in AGENTS]
    if unknown:
        raise AgentError(f"unknown agents in crew: {', '.join(unknown)}", status=404)

    shared = dict(payload or {})
    steps: list[dict[str, Any]] = []
    for identifier in agent_ids:
        step = run(identifier, shared)
        steps.append({"agent": identifier, "elapsed_ms": step["elapsed_ms"]})
        shared["context"] = step["result"]
        # Merge simple scalars forward so later agents can use earlier findings.
        for key, value in step["result"].items():
            if not isinstance(value, (dict, list)) and key not in shared:
                shared[key] = value
    return {
        "crew": agent_ids,
        "steps": steps,
        "final": steps[-1]["agent"] if steps else None,
        "context_keys": sorted(shared),
        "result": shared.get("context", {}),
    }


def register_job_handler() -> None:
    """Make agents runnable through the durable queue (`agent.run`)."""

    if "agent.run" in jobs.HANDLERS:
        return

    @jobs.register("agent.run")
    def _agent_job(payload: dict[str, Any], progress) -> dict[str, Any]:
        agent_id = str(payload.get("agent") or "")
        progress(10, f"agent {agent_id}")
        outcome = run(agent_id, payload.get("input") or {})
        progress(100, "done")
        return outcome


def blueprints() -> dict[str, Any]:
    """The catalog blueprints, honestly labelled: they describe a worker, not code here."""

    path = REPO_ROOT / "catalog" / "agents.json"
    if not path.is_file():
        return {"count": 0, "blueprints": [], "note": "catalog/agents.json missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"count": 0, "blueprints": [], "note": "catalog/agents.json is not valid JSON"}

    runnable = set(AGENTS)
    entries = []
    for blueprint in data:
        identifier = blueprint.get("id", "")
        entries.append({
            "id": identifier,
            "name": blueprint.get("name"),
            "mission": (blueprint.get("mission") or "")[:200],
            "risk_level": blueprint.get("risk_level"),
            "worker_service": blueprint.get("worker_service"),
            "runnable_here": identifier in runnable,
            "execution_mode": blueprint.get("execution_mode"),
        })
    return {
        "count": len(entries),
        "runnable_here": sum(1 for entry in entries if entry["runnable_here"]),
        "blueprints": entries,
        "note": (
            "Blueprints describe a worker service; without it they do not execute. "
            "Use /v1/agents/runtime for agents that run inside this process."
        ),
    }


def fingerprint() -> str:
    """Stable hash of the registry, handy for cache-busting client-side lists."""

    ids = "|".join(sorted(AGENTS))
    return hashlib.sha256(ids.encode()).hexdigest()[:12]


register_job_handler()
