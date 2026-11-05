"""A JARVIS that is actually useful, built from seven layers that cost nothing.

Most home-made assistants feel "pagal" (dumb) for the same seven reasons — they have no
memory, no tools, no plan, no verification, and no idea what they cannot do. Each layer
below is implemented here, and none of it needs a paid API:

1. **Memory** — SQLite tables for facts and episodes, so it remembers you across restarts.
2. **Retrieval** — BM25 over those memories; the reply is grounded, not guessed.
3. **Planning** — a goal becomes ordered steps over the agent registry.
4. **Tool use** — 37 real agents (ffmpeg, code index, ops) instead of imagination.
5. **A brain** — local Ollama if present (free), otherwise deterministic intent rules.
6. **Verification** — every step's result is checked; failures are reported, not glossed.
7. **Honesty** — when it cannot do something it says so and lists what it can do.

Say it plainly: without a model this is a very good rule-based assistant, not a genius.
With `ollama serve` and a 3B–8B model it starts to feel like the film. Both are free.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import agents, governance, toolbelt

_lock = threading.Lock()

PERSONA = (
    "You are JARVIS, a terse, competent assistant for a solo builder. "
    "You answer in the user's language (Hinglish or English). "
    "You never invent facts about the user; you use the MEMORY block. "
    "You never claim an action happened unless the TOOLS block shows it did. "
    "When a tool is available and the request fits it, call the tool instead of guessing. "
    "If a tool returns 'unavailable: ...', tell the user exactly what to install — never "
    "describe output you did not receive."
)

PERSONA_TOOLS = (
    "\n\nYou have a tool belt of free, locally installed tools. Call them with the provided "
    "functions. Rules that are not negotiable:\n"
    "1. Never claim a file was produced unless a tool result shows its path.\n"
    "2. Never invent numbers (durations, counts, test results) — they come from tool output.\n"
    "3. If a tool returns an error beginning 'unavailable:', report that error and the install "
    "hint. Do not substitute an imagined result.\n"
    "4. Prefer one precise tool call over many; the user pays for latency, not for effort.\n"
    "5. Answer in the user's language, at most 4 sentences, and end with what was actually done."
)


# --------------------------------------------------------------------------- #
# 1. Memory
# --------------------------------------------------------------------------- #

def db_path() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT", "/data")).expanduser()
    return root / "jarvis.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            updated_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT NOT NULL DEFAULT 'default',
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            at REAL NOT NULL,
            meta TEXT
        )
        """
    )
    return connection


def init_db() -> None:
    with _connect():
        pass


def remember(key: str, value: str, source: str = "user") -> dict[str, Any]:
    key = re.sub(r"\s+", " ", (key or "").strip().lower())[:120]
    value = (value or "").strip()[:2000]
    if not key or not value:
        raise ValueError("key and value are required")
    with _lock, _connect() as connection:
        connection.execute(
            "INSERT INTO facts (key, value, source, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, source=excluded.source,"
            " updated_at=excluded.updated_at",
            (key, value, source, time.time()),
        )
    return {"key": key, "value": value, "source": source}


def forget(key: str) -> dict[str, Any]:
    with _lock, _connect() as connection:
        cursor = connection.execute("DELETE FROM facts WHERE key = ?", (key.strip().lower(),))
        removed = cursor.rowcount
    return {"key": key, "removed": removed}


def facts(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT key, value, source, updated_at FROM facts ORDER BY updated_at DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
    return [
        {"key": row["key"], "value": row["value"], "source": row["source"],
         "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["updated_at"]))}
        for row in rows
    ]


def add_episode(role: str, text: str, session: str = "default", meta: dict[str, Any] | None = None) -> None:
    with _lock, _connect() as connection:
        connection.execute(
            "INSERT INTO episodes (session, role, text, at, meta) VALUES (?, ?, ?, ?, ?)",
            (session, role, text[:4000], time.time(), json.dumps(meta or {})),
        )


def history(session: str = "default", limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT role, text, at, meta FROM episodes WHERE session = ? ORDER BY id DESC LIMIT ?",
            (session, min(limit, 200)),
        ).fetchall()
    return [
        {
            "role": row["role"],
            "text": row["text"],
            "at": time.strftime("%H:%M:%S", time.localtime(row["at"])),
            "meta": json.loads(row["meta"] or "{}"),
        }
        for row in reversed(rows)
    ]


def recall(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """BM25 over memories, so 'maine kya bola tha video ke baare me' actually works."""

    from .tool_search import BM25, tokenize

    documents: list[dict[str, Any]] = [
        {"kind": "fact", "text": f"{item['key']} {item['value']}", **item} for item in facts(250)
    ]
    with _connect() as connection:
        rows = connection.execute(
            "SELECT role, text, at FROM episodes ORDER BY id DESC LIMIT 250"
        ).fetchall()
    documents += [
        {"kind": "episode", "text": row["text"], "role": row["role"],
         "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["at"]))}
        for row in rows
    ]
    if not documents:
        return []

    ranker = BM25([tokenize(item["text"]) for item in documents])
    hits = ranker.search(query, limit=limit)
    return [{**documents[hit["index"]], "score": hit["score"]} for hit in hits]


# --------------------------------------------------------------------------- #
# 2. Fact extraction (so the user never has to say "remember this")
# --------------------------------------------------------------------------- #

FACT_PATTERNS = [
    # English and Hinglish in one pattern: the trailing "hai" is optional, and the value
    # stops at punctuation or a conjunction so a following sentence is not swallowed.
    (
        r"\b(?:mera naam|my name is|call me|mujhe bulao)\s+"
        r"([A-Za-z][\w .-]{1,32}?)(?=[.,!?\n]|$|\s+(?:hai|hoon|hun|and|aur)\b)",
        "name",
    ),
    (
        r"\b(?:i am|i'm|main)\s+(?:a|an|ek)?\s*([a-z][\w ]{2,30}?)\s+"
        r"(?:developer|builder|creator|student|engineer)\b",
        "role",
    ),
    (r"\b(?:i like|mujhe|muje)\s+([\w .-]{2,40}?)\s+(?:pasand|achha|acha)\b", "likes"),
    (r"\b(?:i hate|mujhe|muje)\s+([\w .-]{2,40}?)\s+(?:pasand nahi|nahi chahiye)\b", "dislikes"),
    # One sentence only: a note must not eat the rest of the message.
    (r"\b(?:remember|yaad rakho|note karo)[: ]+([^.!?\n]{3,200})", "note"),
    (r"\b(?:my project is|mera project)\s+([^.!?\n]{2,80})", "project"),
]


def extract_facts(message: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for pattern, key in FACT_PATTERNS:
        for match in re.finditer(pattern, message, flags=re.IGNORECASE):
            value = " ".join(match.group(1).split()).strip(" .,!")
            if value and len(value) > 1:
                found.append({"key": key, "value": value})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in found:
        unique[(item["key"], item["value"].lower())] = item
    return list(unique.values())


# --------------------------------------------------------------------------- #
# 3–4. Intent rules over the real agent registry
# --------------------------------------------------------------------------- #

INTENTS: list[tuple[str, list[str], str, dict[str, str]]] = [
    # (intent, keywords, agent, input hints)
    ("cut_silence", ["silence", "khamoshi", "chup", "cut"], "video-editor", {"path": "$path"}),
    ("chapters", ["chapter", "chapters", "scene"], "chapter-writer", {"path": "$path"}),
    ("thumbnails", ["thumbnail", "thumb"], "thumbnail-designer", {"path": "$path"}),
    ("clip", ["clip", "short", "reel", "vertical"], "clip-maker", {"path": "$path"}),
    ("subtitles", ["subtitle", "srt", "vtt", "caption"], "subtitle-smith", {"path": "$path"}),
    ("loudness", ["loud", "audio level", "lufs", "awaz"], "loudness-master", {"path": "$path"}),
    ("probe", ["probe", "metadata", "resol ution", "duration", "kitna lamba"], "media-prober", {"path": "$path"}),
    ("package", ["publish", "upload", "package", "manifest"], "publish-packager", {"path": "$path"}),
    ("review", ["review", "check code", "code review"], "code-reviewer", {"path": "$path"}),
    ("tests", ["test", "pytest", "spec"], "test-planner", {"path": "$path"}),
    ("plan", ["plan", "refactor", "approach"], "refactor-planner", {"goal": "$text"}),
    ("changelog", ["changelog", "git log", "history"], "changelog-writer", {}),
    ("deps", ["dependency", "dependencies", "requirements", "imports"], "import-auditor", {}),
    ("health", ["health", "haal", "status", "sab theek"], "health-warden", {}),
    ("backup", ["backup", "safe rakh", "snapshot"], "backup-keeper", {}),
    ("metrics", ["metrics", "traffic", "latency", "requests"], "metrics-reporter", {}),
    ("queue", ["jobs", "queue", "workers"], "job-runner", {}),
    ("capacity", ["capacity", "disk", "space", "pura"], "capacity-planner", {}),
    ("titles", ["title", "headline", "naam socho"], "title-suggester", {"topic": "$text"}),
    ("seo", ["seo", "tags", "keywords"], "seo-planner", {"topic": "$text"}),
    ("hashtags", ["hashtag", "#"], "hashtag-smith", {"topic": "$text"}),
    ("description", ["description", "about section"], "description-writer", {"topic": "$text"}),
    ("brand", ["brand", "name ideas", "domain"], "brand-namer", {"seed": "$text"}),
    ("schedule", ["schedule", "calendar", "posting"], "schedule-planner", {}),
    ("discover", ["search", "dhundo", "find tool", "kaunsa tool"], "tool-scout", {"query": "$text"}),
    ("routes", ["endpoint", "route", "api list"], "tool-scout", {"query": "$text", "target": "routes"}),
    ("repo", ["repo", "codebase", "project structure", "files"], "repo-scout", {}),
    ("blueprints", ["blueprints", "jarvis orchestrator"], "api-cartographer", {}),
]

PATH_RE = re.compile(r"[\w./-]+\.(?:mp4|mkv|mov|webm|wav|mp3|m4a|flac|ogg|srt|vtt|py|json|md|txt)\b", re.IGNORECASE)


def detect_intents(message: str) -> list[dict[str, Any]]:
    text = (message or "").lower()
    path_match = PATH_RE.search(message or "")
    path = path_match.group(0) if path_match else ""
    picked: list[tuple[int, dict[str, Any]]] = []

    for intent, keywords, agent_id, hints in INTENTS:
        for keyword in keywords:
            position = text.find(keyword)
            if position < 0:
                continue
            if agent_id not in agents.AGENTS:
                continue
            payload: dict[str, Any] = {}
            for field, template in hints.items():
                if template == "$path":
                    if not path:
                        continue
                    payload[field] = path
                elif template == "$text":
                    payload[field] = _strip_command_words(message)
            entry = agents.AGENTS[agent_id]
            if any(required not in payload for required in entry.required):
                continue
            picked.append((position, {"intent": intent, "agent": agent_id, "input": payload}))
            break

    picked.sort(key=lambda pair: pair[0])
    deduped: list[dict[str, Any]] = []
    for _, entry in picked:
        if not any(existing["agent"] == entry["agent"] for existing in deduped):
            deduped.append(entry)
    return deduped[:4]


# Command/auxiliary words only. Nouns ("video", "title", "editing") are kept: they are
# usually the topic the user is asking about.
COMMAND_WORDS = re.compile(
    r"\b(karo|kar|kardo|karna|kro|please|plz|make|create|banao|bana|batao|bata|socho|soch|"
    r"dedo|de|do|chalao|run|start|chahiye|chaiye|liye|lie|jaldi|abhi|"
    r"ka|ki|ke|se|ko|me|mein|hai|ha|tha|ho|gaya|hoga|kar|"
    r"the|a|an|for|my|mera|meri|mujhe|muje|and|aur|then|phir|about|some|kuch|keep|"
    r"in|on|to|with|of|please)\b",
    re.IGNORECASE,
)


def _strip_command_words(message: str) -> str:
    cleaned = PATH_RE.sub(" ", message or "")
    cleaned = COMMAND_WORDS.sub(" ", cleaned)
    cleaned = re.sub(r"[^\w\s#-]", " ", cleaned)
    return " ".join(cleaned.split())[:160] or (message or "").strip()[:160]


# --------------------------------------------------------------------------- #
# 5. The brain: local model if available, rules if not
# --------------------------------------------------------------------------- #

def model_available() -> bool:
    from . import ai_router

    try:
        return bool(ai_router.chain())
    except Exception:  # noqa: BLE001 - a broken config must not crash chat
        return False


def _ask_model(system: str, user: str) -> dict[str, Any] | None:
    from . import ai_router

    try:
        answer = ai_router.complete(system=system, user=user, max_tokens=700, temperature=0.4)
    except Exception:  # noqa: BLE001 - fall back to rules, never to a fabricated answer
        return None
    text = str(answer.get("text") or "").strip()
    if not text:
        return None
    return {"text": text, "provider": answer.get("provider"), "model": answer.get("model")}


def _inner_block() -> str:
    """Identity and mood, prepended to every brain prompt."""

    from . import affect, character

    try:
        identity = character.prompt_block()
    except Exception:  # noqa: BLE001 - a broken character file must not break chat
        identity = PERSONA
    try:
        mood = affect.state()
        feeling = f"{mood['label']} — {mood['tone_directive']}"
    except Exception:  # noqa: BLE001
        feeling = "neutral"
    return f"{identity}\n\nCURRENT MOOD: {feeling}"


def _finish_turn(*, session: str, message: str, intent: str, ok: bool = True,
                 tools: int = 0, used_model: bool = False, error: str = "") -> dict[str, Any]:
    """Record the turn for the self layer and move the mood. Failures never break chat."""

    from . import affect, mind

    mood: dict[str, Any] = {}
    try:
        # Only an actual run can be a success or failure; talking alone moves nothing.
        mood = affect.observe(message, outcome_ok=(ok if tools else None), tools_used=tools)
    except Exception:  # noqa: BLE001
        pass
    try:
        mind.record_turn(session=session, message=message, intent=intent, ok=bool(ok),
                         tools=tools, used_model=used_model, error=error)
        mind.maybe_reflect()
    except Exception:  # noqa: BLE001
        pass
    return {"mood": mood.get("label"), "affect_triggered": mood.get("triggered", [])}


def _memory_block(limit: int = 8) -> str:
    entries = facts(limit=limit)
    if not entries:
        return "(nothing remembered yet)"
    return "\n".join(f"- {item['key']}: {item['value']}" for item in entries)


# --------------------------------------------------------------------------- #
# 6. Execution with verification
# --------------------------------------------------------------------------- #

def execute(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    shared: dict[str, Any] = {}
    for step in steps:
        identifier = step["agent"]
        payload = dict(step.get("input") or {})
        if "path" not in payload and shared.get("path"):
            payload["path"] = shared["path"]
        try:
            result = agents.run(identifier, payload)
            body = result.get("result") or {}
            if isinstance(body, dict) and body.get("ok") is False:
                outcomes.append({"agent": identifier, "input": payload, "ok": False,
                                 "error": "agent reported ok=false", "result": body})
                continue
            outcomes.append({"agent": identifier, "input": payload, "ok": True,
                             "elapsed_ms": result.get("elapsed_ms"), "result": body})
        except agents.AgentError as exc:
            outcomes.append({"agent": identifier, "input": payload, "ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            outcomes.append({"agent": identifier, "input": payload, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"})
    return outcomes


def summarise(outcomes: list[dict[str, Any]]) -> str:
    """Plain-language report of what actually happened — including failures."""

    if not outcomes:
        return ""
    lines = []
    for outcome in outcomes:
        name = agents.AGENTS[outcome["agent"]].name if outcome["agent"] in agents.AGENTS else outcome["agent"]
        if not outcome["ok"]:
            lines.append(f"{name}: nahi ho paya — {outcome['error']}")
            continue
        body = outcome.get("result") or {}
        highlights = []
        for key in ("duration", "chapter_count", "removed_seconds", "total_files", "declared",
                    "status", "count", "names", "titles", "hashtags", "corpus"):
            if key in body:
                value = body[key]
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value[:4])
                highlights.append(f"{key}={value}")
        suffix = " · ".join(highlights[:3])
        lines.append(f"{name}: done{' — ' + suffix if suffix else ''}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 7. Tool belt: the honest capability layer
# --------------------------------------------------------------------------- #

TOOL_CMD = re.compile(
    r"^\s*(?:run\s+|chalao\s+|use\s+|chala\s+|try\s+)?tool\s+([A-Za-z0-9][\w.\-]*)\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
SKILL_CMD = re.compile(
    r"^\s*(?:run\s+|chalao\s+|use\s+|apply\s+)?skill\s+([A-Za-z0-9][\w.\-]*)\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
CAPABILITY_RE = re.compile(
    r"\b(tools?\s*(list|batao|dikhao|kaunse|kitne)|kitne tools|capabilit|kya kya kar sakta|"
    r"what can you do|toolbelt|tool belt|saare tools)\b",
    re.IGNORECASE,
)


def _parse_args(text: str) -> dict[str, Any]:
    """`path=a.mp4 op=probe count=3` → typed kwargs. Quoted values are respected."""

    import shlex

    try:
        tokens = shlex.split(text or "")
    except ValueError:
        tokens = (text or "").split()
    args: dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, _, raw = token.partition("=")
        key = key.strip()
        if not key:
            continue
        value: Any = raw.strip()
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "false"}:
                value = lowered == "true"
            elif re.fullmatch(r"-?\d+", value):
                value = int(value)
            elif re.fullmatch(r"-?\d*\.\d+", value):
                value = float(value)
        args[key] = value
    return args


def _tool_command(message: str) -> dict[str, Any] | None:
    """`tool git op=log limit=3` — direct, explicit, no model involved."""

    match = TOOL_CMD.match(message or "")
    if not match:
        return None
    tool_id, rest = match.group(1), match.group(2) or ""
    return {"tool": tool_id, "args": _parse_args(rest)}


def _skill_command(message: str) -> dict[str, Any] | None:
    """`skill text.stats.inline text="hello"` — direct, no model needed."""

    match = SKILL_CMD.match(message or "")
    if not match:
        return None
    import shlex

    skill_id, rest = match.group(1), match.group(2) or ""
    args: dict[str, Any] = {}
    try:
        tokens = shlex.split(rest)
    except ValueError:
        tokens = rest.split()
    for token in tokens:
        if "=" not in token:
            continue
        key, _, raw = token.partition("=")
        value: Any = raw
        if raw.lower() in {"true", "false"}:
            value = raw.lower() == "true"
        elif re.fullmatch(r"-?\d+", raw):
            value = int(raw)
        elif re.fullmatch(r"-?\d*\.\d+", raw):
            value = float(raw)
        args[key.strip()] = value
    return {"skill": skill_id, "args": args}


def _skill_chat(skill_id: str, args: dict[str, Any]) -> dict[str, Any]:
    from . import skill_runners, skills

    try:
        run = skills.run(skill_id, args)
    except skill_runners.SkillUnavailable as exc:
        nearby = [item["id"] for item in skills.search(skill_id, limit=3)["results"]]
        hint = f" Kareeb ke skills: {', '.join(nearby)}." if nearby else ""
        return {"ok": False, "reply": f"{exc}.{hint}", "error": str(exc)}
    except skill_runners.SkillInputError as exc:
        return {"ok": False, "reply": f"{skill_id} nahi chala — {exc}", "error": str(exc)}
    except KeyError as exc:
        return {"ok": False, "reply": str(exc).strip('"'), "error": str(exc)}

    body = run.get("result") or {}
    preview = json.dumps(body, ensure_ascii=False)
    if len(preview) > 500:
        preview = preview[:500] + "…"
    return {"ok": True, "reply": f"{skill_id}: done — {preview}", "result": body,
            "elapsed_ms": run.get("elapsed_ms")}


def tool_chat(tool_id: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        run = toolbelt.run(tool_id, args)
    except toolbelt.ToolUnavailable as exc:
        suggestions = [item["id"] for item in toolbelt.search(tool_id, limit=3)["results"]]
        hint = f" Shayad ye chahiye: {', '.join(suggestions)}." if suggestions else ""
        return {"ok": False, "reply": f"{exc}.{hint}", "error": str(exc)}
    except toolbelt.ToolError as exc:
        return {"ok": False, "reply": f"{tool_id} nahi chala — {exc}",
                "error": str(exc)}
    body = run.get("result") or {}
    preview = json.dumps(body, ensure_ascii=False)
    if len(preview) > 600:
        preview = preview[:600] + "…"
    return {"ok": True, "reply": f"{tool_id}: done — {preview}", "result": body,
            "elapsed_ms": run.get("elapsed_ms")}


def capability_reply() -> str:
    belt = toolbelt.summary()
    ready = belt["ready_ids"]
    lines = [f"Tool belt: {belt['total']} tools, {belt['ready']} abhi is machine par chal sakte hain "
             f"({belt['available']} dependencies ke hisaab se present, {belt['runnable']} ke runner wired)."]
    lines.append("Ready: " + ", ".join(ready[:14]) + ("…" if len(ready) > 14 else ""))
    missing = belt["missing"][:4]
    if missing:
        lines.append("Missing: " + "; ".join(f"{row['id']} ({row['detail']})" for row in missing))
    try:
        from . import skills

        catalogue = skills.stats()
        lines.append(f"Skills: {catalogue['total']} registered — {catalogue['native']} native "
                     f"({catalogue['available_now']} abhi ready) + {catalogue['external']} external "
                     "MCP imports. `skill text.stats.inline text=\"hello\"`")
    except Exception:  # noqa: BLE001 - the belt line below still works
        pass
    lines.append("Chalane ke liye: `tool ffmpeg op=probe path=video.mp4`. Poori list: GET /v1/belt")
    return "\n".join(lines)


def claude_available() -> bool:
    from . import anthropic

    return anthropic.available()


def _claude_turn(message: str) -> dict[str, Any] | None:
    """Claude decides which free tool to call, we run it, Claude reads the result."""

    from . import anthropic

    if not anthropic.available():
        return None

    definitions = toolbelt.claude_tools(only_available=True)
    belt = toolbelt.summary()
    system = (
        _inner_block() + PERSONA_TOOLS
        + "\n\nMEMORY (facts about the user):\n" + _memory_block()
        + f"\n\nTOOL BELT: {belt['ready']} of {belt['total']} tools ready — "
        + ", ".join(belt["ready_ids"])
    )
    try:
        answer = anthropic.tool_turn(
            system, message, definitions, toolbelt.run_from_claude,
            max_rounds=3, max_tokens=1200, temperature=0.3,
        )
    except anthropic.AnthropicError as exc:
        return {"error": str(exc), "unavailable": exc.unavailable}

    runs = answer.get("tool_runs") or []
    outcomes = [
        {"agent": f"tool:{run['tool']}", "input": run.get("args") or {},
         "ok": bool(run.get("ok")), "result": run.get("output") or {},
         **({} if run.get("ok") else {"error": str((run.get("output") or {}).get("error"))})}
        for run in runs
    ]
    return {
        "text": answer.get("text") or "",
        "tool_runs": runs,
        "outcomes": outcomes,
        "model": answer.get("model"),
        "rounds": answer.get("rounds"),
        "usage": answer.get("usage"),
        "stopped": answer.get("stopped"),
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def chat(message: str, session: str = "default", dry_run: bool = False) -> dict[str, Any]:
    """One turn: extract memory, find intents, run tools, answer."""

    message = (message or "").strip()
    if not message:
        raise ValueError("message is required")

    init_db()
    learned = []
    for fact in extract_facts(message):
        try:
            remember(fact["key"], fact["value"], source="auto")
            learned.append(fact)
        except ValueError:
            continue

    if re.search(r"\b(kya yaad|what do you remember|memory|yaad hai)\b", message, re.IGNORECASE):
        stored = facts(limit=15)
        reply = "Mujhe ye yaad hai:\n" + "\n".join(f"- {item['key']}: {item['value']}" for item in stored) \
            if stored else "Abhi kuch yaad nahi — bolo 'yaad rakho ...' to main rakh lunga."
        add_episode("user", message, session)
        add_episode("jarvis", reply, session, {"intent": "memory"})
        inner = _finish_turn(session=session, message=message, intent="memory")
        return {"reply": reply, "intent": "memory", "actions": [], "learned": learned,
                "used_model": False, "session": session, **inner}

    skill_request = _skill_command(message)
    if skill_request:
        outcome = _skill_chat(skill_request["skill"], skill_request["args"])
        action = {"agent": f"skill:{skill_request['skill']}", "input": skill_request["args"],
                  "ok": bool(outcome.get("ok")), "result": outcome.get("result") or {},
                  **({} if outcome.get("ok") else {"error": outcome.get("error")})}
        add_episode("user", message, session)
        add_episode("jarvis", outcome["reply"], session,
                    {"intent": "skill", "skill": skill_request["skill"]})
        governance.record("jarvis.chat", target=session,
                          detail={"intent": "skill", "skill": skill_request["skill"],
                                  "ok": bool(outcome.get("ok"))})
        inner = _finish_turn(session=session, message=message,
                             intent=f"skill:{skill_request['skill']}",
                             ok=bool(outcome.get("ok")), tools=1,
                             error=str(outcome.get("error") or ""))
        return {"reply": outcome["reply"], "intent": f"skill:{skill_request['skill']}",
                "actions": [action], "learned": learned, "used_model": False,
                "model": None, "session": session, "available_agents": len(agents.AGENTS),
                **inner}

    if CAPABILITY_RE.search(message) and not TOOL_CMD.match(message) and not SKILL_CMD.match(message):
        reply = capability_reply()
        add_episode("user", message, session)
        add_episode("jarvis", reply, session, {"intent": "tools"})
        governance.record("jarvis.chat", target=session, detail={"intent": "tools"})
        inner = _finish_turn(session=session, message=message, intent="tools")
        return {"reply": reply, "intent": "tools", "actions": [], "learned": learned,
                "used_model": False, "model": None, "session": session,
                "available_agents": len(agents.AGENTS), **inner}

    tool_request = _tool_command(message)
    if tool_request:
        outcome = tool_chat(tool_request["tool"], tool_request["args"])
        action = {"agent": f"tool:{tool_request['tool']}", "input": tool_request["args"],
                  "ok": bool(outcome.get("ok")), "result": outcome.get("result") or {},
                  **({} if outcome.get("ok") else {"error": outcome.get("error")})}
        add_episode("user", message, session)
        add_episode("jarvis", outcome["reply"], session,
                    {"intent": "tool", "tool": tool_request["tool"]})
        governance.record("jarvis.chat", target=session,
                          detail={"intent": "tool", "tool": tool_request["tool"],
                                  "ok": bool(outcome.get("ok"))})
        inner = _finish_turn(session=session, message=message,
                             intent=f"tool:{tool_request['tool']}",
                             ok=bool(outcome.get("ok")), tools=1,
                             error=str(outcome.get("error") or ""))
        return {"reply": outcome["reply"], "intent": f"tool:{tool_request['tool']}",
                "actions": [action], "learned": learned, "used_model": False,
                "model": None, "session": session, "available_agents": len(agents.AGENTS),
                **inner}

    steps = detect_intents(message)
    outcomes = execute(steps) if (steps and not dry_run) else []
    used_model = False
    reply: str | None = None
    model_note = ""

    memories = recall(message, limit=4)
    memory_text = _memory_block()

    learned_meta: dict[str, Any] = {}

    # Claude first: it can read the tool belt and decide what to run. A key is required;
    # without one this is skipped silently and the rule-based path answers.
    if claude_available() and not dry_run:
        turn = _claude_turn(message)
        if turn and turn.get("text"):
            reply = turn["text"]
            outcomes = outcomes + list(turn.get("outcomes") or [])
            used_model = True
            learned_meta = {"provider": "anthropic", "model": turn.get("model"),
                            "rounds": turn.get("rounds"), "stopped": turn.get("stopped")}
        elif turn and turn.get("error"):
            model_note = f"Claude: {turn['error']}"

    if reply is None and model_available():
        tool_report = summarise(outcomes) or "(no tool was run yet)"
        catalogue = ", ".join(sorted(agents.AGENTS))[:1500]
        answer = _ask_model(
            _inner_block() + "\n\nMEMORY:\n" + memory_text + "\n\nTOOLS RUN THIS TURN:\n" + tool_report,
            f"User said: {message}\n\n"
            f"Agents you can suggest by id: {catalogue}\n\n"
            "Answer in 1-4 sentences, in the user's language. If a tool failed, say what to fix. "
            "If the request needs a tool that was not run, say exactly which agent id to use.",
        )
        if answer:
            reply = answer["text"]
            used_model = True
            learned_meta = {"provider": answer.get("provider"), "model": answer.get("model")}

    if reply is None:
        # Rule-based answer: truthful, never inventing capability.
        if learned and not outcomes:
            learned_text = ", ".join(f"{item['key']}={item['value']}" for item in learned)
            reply = f"Yaad rakh liya: {learned_text}. Ab jo kar sakta hoon, bolo — jaise 'health batao' ya 'video.mp4 ke chapters banao'."
        elif outcomes:
            reply = summarise(outcomes)
        elif steps:
            reply = "Ye main kar sakta hoon (dry run): " + summarise(
                [{"agent": step["agent"], "input": step["input"], "ok": True, "result": {}} for step in steps]
            )
        elif memories:
            reply = "Iska seedha tool nahi hai. Sabse relevant yaad: " + \
                "; ".join(f"{item.get('key', 'episode')}={item.get('value', item.get('text', ''))[:60]}" for item in memories[:2])
        else:
            reply = (
                "Ye mujhe samajh nahi aaya. Jo pakka kar sakta hoon: " + ", ".join(sorted(agents.AGENTS)[:10]) +
                f" … plus {toolbelt.summary()['available']} free tools (`tool ffmpeg op=probe path=video.mp4`). "
                "Poori list /v1/belt par. Claude brain lagana ho to ANTHROPIC_API_KEY daal do."
            )

    add_episode("user", message, session)
    add_episode("jarvis", reply, session, {"intent": steps[0]["intent"] if steps else "chat",
                                           "agents": [step["agent"] for step in steps], **learned_meta})
    governance.record("jarvis.chat", target=session, detail={
        "intents": [step["intent"] for step in steps],
        "agents": [step["agent"] for step in steps],
        "model": used_model,
    })

    first_error = next((str(item.get("error")) for item in outcomes if not item.get("ok")), "")
    inner = _finish_turn(
        session=session, message=message,
        intent=steps[0]["intent"] if steps else ("chat" if used_model else "unknown"),
        ok=not first_error, tools=len(outcomes), used_model=used_model, error=first_error,
    )

    return {
        "reply": reply,
        "intent": steps[0]["intent"] if steps else ("chat" if used_model else "unknown"),
        "actions": outcomes,
        "learned": learned,
        "used_model": used_model,
        "model": learned_meta if used_model else None,
        "model_note": model_note,
        "session": session,
        "available_agents": len(agents.AGENTS),
        **inner,
    }


def plan(goal: str) -> dict[str, Any]:
    """Show what would run, without running it."""

    steps = detect_intents(goal)
    return {
        "goal": goal,
        "steps": [
            {
                "agent": step["agent"],
                "name": agents.AGENTS[step["agent"]].name,
                "input": step["input"],
                "required": agents.AGENTS[step["agent"]].required,
            }
            for step in steps
        ],
        "note": "rule-based plan over the local agent registry; nothing was executed" if steps
                else "no local agent matches this goal",
    }


def status() -> dict[str, Any]:
    from . import anthropic

    belt = toolbelt.summary()
    return {
        "memory": {"facts": len(facts(500)), "db": str(db_path())},
        "model": {
            "configured": model_available(),
            "claude": anthropic.available(),
            "claude_model": anthropic.model() if anthropic.available() else None,
            "fallback": "ollama / openai-compatible chain" if model_available() else "rules only",
        },
        "agents": len(agents.AGENTS),
        "tools": {"total": belt["total"], "ready": belt["ready"],
                  "available": belt["available"], "runnable": belt["runnable"],
                  "ready_ids": belt["ready_ids"]},
        "character": {"name": character_status()["name"], "preset": character_status()["preset"]},
        "mood": mood_status()["label"],
        "self": {"lessons": mind_counts()["lessons"], "open_proposals": mind_counts()["proposals"]},
        "sessions": _sessions(),
    }


def character_status() -> dict[str, Any]:
    from . import character

    return character.status()


def mood_status() -> dict[str, Any]:
    from . import affect

    return affect.state()


def mind_counts() -> dict[str, Any]:
    from . import mind

    return {"lessons": len(mind.lessons(200)), "proposals": len(mind.proposals("open", 100))}


def _sessions() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT session, COUNT(*) AS turns, MAX(at) AS last FROM episodes GROUP BY session"
            " ORDER BY last DESC LIMIT 10"
        ).fetchall()
    return [
        {"session": row["session"], "turns": row["turns"],
         "last": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["last"]))}
        for row in rows
    ]
