"""The self layer: what it knows about itself, and how it improves without lying.

Three things live here, all built from its own logs rather than from vibes:

* **Self-model** — measured capability, refreshed on demand: how many agents exist, which
  belt tools are actually ready on this machine, whether a model is configured, how much
  it remembers. Gaps are listed, not hidden.
* **Reflection** — every turn is recorded. ``reflect()`` reads the recent history and finds
  patterns: tools that keep failing, dependencies that are missing, messages it could not
  classify. Each finding becomes a lesson (a fact about itself) or a proposal (an action
  for the human).
* **Proposals** — a proposal is text plus evidence. Accepting one **does not change code**.
  It records the decision and prints the exact next step. An assistant that silently edits
  itself at 3am is a liability, not a personality.

Storage: ``UAI_DATA_ROOT/mind.db``. Nothing here needs a model; with a model configured it
gets better wording, not better facts.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()  # re-entrant: helpers call init_db while holding it
_PROCESS_START = time.time()


def _db() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "mind.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " at REAL NOT NULL, session TEXT, message TEXT, intent TEXT, ok INTEGER,"
            " tools INTEGER, used_model INTEGER, error TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS lessons (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " at REAL NOT NULL, text TEXT NOT NULL UNIQUE, source TEXT, evidence TEXT,"
            " pinned INTEGER DEFAULT 0)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " at REAL NOT NULL, title TEXT NOT NULL, rationale TEXT, kind TEXT,"
            " evidence TEXT, status TEXT DEFAULT 'open')"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " at REAL NOT NULL, entry TEXT NOT NULL, mood TEXT, kind TEXT)"
        )


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #

def record_turn(*, session: str, message: str, intent: str, ok: bool = True,
                tools: int = 0, used_model: bool = False, error: str = "") -> dict[str, Any]:
    init_db()
    with _LOCK, _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO turns (at, session, message, intent, ok, tools, used_model, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), session, (message or "")[:500], intent or "chat",
             1 if ok else 0, int(tools), 1 if used_model else 0, (error or "")[:300]),
        )
        count = connection.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
    return {"turn_id": cursor.lastrowid, "turns_total": count}


def journal(entry: str, *, mood: str = "", kind: str = "note") -> dict[str, Any]:
    if not (entry or "").strip():
        raise ValueError("journal entry cannot be empty")
    init_db()
    with _LOCK, _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO journal (at, entry, mood, kind) VALUES (?, ?, ?, ?)",
            (time.time(), entry.strip()[:2000], mood[:40], kind[:30]),
        )
    return {"id": cursor.lastrowid, "entry": entry.strip()[:2000], "kind": kind}


def entries(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT at, entry, mood, kind FROM journal ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    return [{"at": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["at"])),
             "entry": row["entry"], "mood": row["mood"], "kind": row["kind"]} for row in rows]


# --------------------------------------------------------------------------- #
# Lessons and proposals
# --------------------------------------------------------------------------- #

def add_lesson(text: str, *, source: str = "reflection", evidence: str = "") -> dict[str, Any]:
    text = (text or "").strip()[:400]
    if not text:
        raise ValueError("lesson text cannot be empty")
    init_db()
    with _LOCK, _connect() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO lessons (at, text, source, evidence) VALUES (?, ?, ?, ?)",
                (time.time(), text, source[:40], evidence[:300]),
            )
            return {"id": cursor.lastrowid, "text": text, "created": True}
        except sqlite3.IntegrityError:
            row = connection.execute("SELECT id FROM lessons WHERE text = ?", (text,)).fetchone()
            return {"id": row["id"], "text": text, "created": False}


def lessons(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, at, text, source, evidence, pinned FROM lessons"
            " ORDER BY pinned DESC, id DESC LIMIT ?", (max(1, min(int(limit), 200)),)
        ).fetchall()
    return [{"id": row["id"],
             "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["at"])),
             "text": row["text"], "source": row["source"], "evidence": row["evidence"],
             "pinned": bool(row["pinned"])} for row in rows]


def _proposal(title: str, rationale: str, kind: str, evidence: str = "") -> dict[str, Any]:
    init_db()
    with _LOCK, _connect() as connection:
        existing = connection.execute(
            "SELECT id, status FROM proposals WHERE title = ? AND status = 'open'", (title,)
        ).fetchone()
        if existing:
            return {"id": existing["id"], "title": title, "status": existing["status"],
                    "duplicate": True}
        cursor = connection.execute(
            "INSERT INTO proposals (at, title, rationale, kind, evidence) VALUES (?, ?, ?, ?, ?)",
            (time.time(), title[:200], rationale[:600], kind[:30], evidence[:400]),
        )
    return {"id": cursor.lastrowid, "title": title, "status": "open", "duplicate": False}


def proposals(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    query = "SELECT id, at, title, rationale, kind, evidence, status FROM proposals"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [{"id": row["id"],
             "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["at"])),
             "title": row["title"], "rationale": row["rationale"], "kind": row["kind"],
             "evidence": row["evidence"], "status": row["status"]} for row in rows]


def decide(proposal_id: int, status: str, *, note: str = "") -> dict[str, Any]:
    if status not in {"open", "accepted", "rejected", "done"}:
        raise ValueError("status must be open, accepted, rejected or done")
    init_db()
    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM proposals WHERE id = ?", (int(proposal_id),)).fetchone()
        if row is None:
            raise ValueError(f"no proposal with id {proposal_id}")
        connection.execute("UPDATE proposals SET status = ? WHERE id = ?", (status, int(proposal_id)))
    if note:
        journal(f"proposal #{proposal_id} {status}: {note}", kind="decision")
    return {
        "id": int(proposal_id), "title": row["title"], "status": status,
        "applied_by_me": False,
        "note": (
            "Recorded, not executed. I do not edit my own code: a human applies the change "
            "and re-runs the tests, so nothing silently rewrites behaviour."
        ),
    }


# --------------------------------------------------------------------------- #
# Statistics and reflection
# --------------------------------------------------------------------------- #

def stats(window: int = 100) -> dict[str, Any]:
    init_db()
    window = max(1, min(int(window), 2000))
    with _connect() as connection:
        rows = connection.execute(
            "SELECT at, message, intent, ok, tools, used_model, error FROM turns"
            " ORDER BY id DESC LIMIT ?", (window,)
        ).fetchall()
    if not rows:
        return {"turns": 0, "ok_rate": None, "top_intents": {}, "unknown_intents": 0,
                "tools_per_turn": 0.0, "errors": [], "model_share": 0.0}

    ok = sum(1 for row in rows if row["ok"])
    intents = Counter(row["intent"] or "chat" for row in rows)
    unknown = sum(1 for row in rows if (row["intent"] or "") in {"unknown", "chat"})
    errors = Counter(row["error"][:120] for row in rows if row["error"])
    return {
        "turns": len(rows),
        "ok_rate": round(ok / len(rows), 3),
        "top_intents": dict(intents.most_common(6)),
        "unknown_intents": unknown,
        "tools_per_turn": round(sum(row["tools"] or 0 for row in rows) / len(rows), 2),
        "errors": errors.most_common(5),
        "model_share": round(sum(1 for row in rows if row["used_model"]) / len(rows), 3),
        "unclassified_messages": [row["message"][:80] for row in rows
                                  if (row["intent"] or "") in {"unknown"}][:5],
    }


PIP_HINT = re.compile(r"unavailable:\s*(pip install [A-Za-z0-9._\-]+)")
APT_HINT = re.compile(r"unavailable:\s*(install [A-Za-z0-9._\- ]+)")


def reflect(window: int = 60) -> dict[str, Any]:
    """Read the last N turns, write down what is measurably true, propose the fixes."""

    from . import toolbelt

    report = stats(window)
    findings: list[str] = []
    new_lessons: list[dict[str, Any]] = []
    new_proposals: list[dict[str, Any]] = []

    if not report["turns"]:
        return {"ran": False, "reason": "no turns recorded yet", "findings": [],
                "lessons": [], "proposals": []}

    findings.append(f"{report['turns']} turns, success rate {report['ok_rate']}")
    if report["ok_rate"] is not None and report["ok_rate"] < 0.8:
        findings.append("success rate under 80% — the failures are the useful signal")

    # 1. Missing dependencies that keep biting
    hints = Counter()
    for error, count in report["errors"]:
        match = PIP_HINT.search(error) or APT_HINT.search(error)
        if match:
            hints[match.group(1)] += count
    for hint, count in hints.most_common(3):
        lesson = f"Recurring blocker: {hint} ({count} failure(s) recently)."
        new_lessons.append(add_lesson(lesson, source="reflection",
                                      evidence=f"{count} recorded failures"))
        new_proposals.append(_proposal(
            title=f"Install the missing dependency: {hint.split()[-1]}",
            rationale=f"{count} recent failure(s) came back as '{hint}'. The tool exists; "
                      "its dependency does not.",
            kind="dependency", evidence=hint,
        ))

    # 2. Messages it could not classify
    if report["unknown_intents"] >= max(2, report["turns"] // 4):
        samples = ", ".join(report["unclassified_messages"][:3]) or "(no samples)"
        lesson = ("Unclassified messages are piling up: "
                  f"{report['unknown_intents']}/{report['turns']} turns had no matching intent.")
        new_lessons.append(add_lesson(lesson, source="reflection", evidence=samples))
        new_proposals.append(_proposal(
            title="Add intents for the phrases that miss",
            rationale=f"{report['unknown_intents']} of {report['turns']} recent turns had no "
                      f"matching rule. Samples: {samples}. Add keywords to INTENTS in "
                      "app/jarvis.py, or rely on Claude/Ollama for these.",
            kind="capability", evidence=samples,
        ))

    # 3. The belt is thinner than the catalogue
    belt = toolbelt.summary()
    if belt["ready"] < belt["total"] // 3:
        lesson = (f"Tool belt: {belt['ready']} of {belt['total']} ready. "
                  "The gap is dependencies, not design.")
        new_lessons.append(add_lesson(lesson, source="self-model",
                                      evidence=", ".join(belt["available_ids"][:8])))
    if belt["ready"] < 5:
        new_proposals.append(_proposal(
            title="Wire or install more belt tools",
            rationale=f"Only {belt['ready']} tools are runnable here "
                      f"({', '.join(belt['ready_ids']) or 'none'}). Install the ones you need, "
                      "then POST /v1/belt/refresh.",
            kind="capability",
            evidence=", ".join(row["id"] for row in belt["missing"][:3]),
        ))

    # 4. Is the model actually being used?
    if report["model_share"] < 0.2 and report["turns"] >= 10:
        lesson = (f"Model used in {int(report['model_share'] * 100)}% of turns — replies are "
                  "rule-based. A key or a local Ollama server would change the quality ceiling.")
        new_lessons.append(add_lesson(lesson, source="self-model",
                                      evidence=f"model_share={report['model_share']}"))

    # 5. Cheap honesty check: is it doing work, or talking?
    if report["tools_per_turn"] < 0.2 and report["turns"] >= 10:
        new_proposals.append(_proposal(
            title="Route more requests into tools instead of prose",
            rationale=f"Only {report['tools_per_turn']} tools per turn. If the answer could "
                      "have been a tool run, prefer the tool: numbers come from output.",
            kind="behaviour", evidence=f"tools_per_turn={report['tools_per_turn']}",
        ))

    journal("reflection: " + "; ".join(findings[:3]), kind="reflection")
    return {
        "ran": True,
        "stats": report,
        "findings": findings,
        "lessons": [item for item in new_lessons if item.get("created")],
        "proposals": new_proposals,
        "next": "Accept or reject proposals via POST /v1/mind/proposals/{id}/decide.",
    }


def maybe_reflect() -> dict[str, Any] | None:
    """Automatic reflection every N turns (UAI_REFLECT_EVERY, default 25)."""

    try:
        every = int(os.getenv("UAI_REFLECT_EVERY") or 25)
    except ValueError:
        every = 25
    if every <= 0:
        return None
    init_db()
    with _connect() as connection:
        total = connection.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
        already = connection.execute(
            "SELECT COUNT(*) AS n FROM journal WHERE kind = 'reflection'").fetchone()["n"]
    if total and total % every == 0 and already < total // every:
        return reflect()
    return None


# --------------------------------------------------------------------------- #
# Self-model
# --------------------------------------------------------------------------- #

def self_model() -> dict[str, Any]:
    from . import affect, agents, character, jarvis, toolbelt

    belt = toolbelt.summary()
    report = stats(100)
    model = jarvis.status()["model"]
    gaps = []
    if not model.get("configured"):
        gaps.append("no model configured — rules only, so the quality ceiling is intent heuristics")
    missing = [row for row in belt["missing"][:10]]
    for row in missing[:5]:
        gaps.append(f"{row['id']}: {row['detail']}")

    return {
        "identity": character.status()["name"],
        "preset": character.load()["preset"],
        "mood": affect.state()["label"],
        "capabilities": {
            "agents": len(agents.AGENTS),
            "tools_total": belt["total"],
            "tools_ready": belt["ready"],
            "tools_ready_ids": belt["ready_ids"],
            "model": model,
        },
        "memory": {
            "facts": len(jarvis.facts(500)),
            "turns_recorded": report["turns"],
        },
        "behaviour": {
            "success_rate": report["ok_rate"],
            "tools_per_turn": report["tools_per_turn"],
            "model_share": report["model_share"],
        },
        "known_gaps": gaps,
        "uptime_seconds": round(time.time() - _PROCESS_START, 1),
        "lessons_learned": len(lessons(200)),
        "open_proposals": len(proposals("open")),
        "honesty": (
            "This is a measured inventory of what the process can do on this machine, "
            "plus the gaps it knows about. It is not self-awareness."
        ),
    }


def status() -> dict[str, Any]:
    return {
        "self_model": self_model(),
        "stats": stats(50),
        "recent_lessons": lessons(5),
        "open_proposals": proposals("open", 5),
        "journal": entries(5),
    }
