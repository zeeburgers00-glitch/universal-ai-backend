"""Small persistent status store for approval-gated REA tool jobs."""
import asyncio
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from .rea_mcp import ReaBridgeError, call_rea_tool, close_rea_session, _allowed_tool_names, _configuration, _validate_argument_scope
except ImportError:
    from rea_mcp import ReaBridgeError, call_rea_tool, close_rea_session, _allowed_tool_names, _configuration, _validate_argument_scope

_ACTIVE_JOBS: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    configured = os.getenv("REA_JOB_DB_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
        path = (base / "UniversalAIBackend" / "rea-jobs.sqlite3").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _connect():
    connection = sqlite3.connect(_db_path(), timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_rea_jobs() -> None:
    with _connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS rea_jobs (
                id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                authorization_scope_note TEXT NOT NULL DEFAULT '',
                approval_confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            )
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(rea_jobs)").fetchall()}
        if "authorization_scope_note" not in columns:
            db.execute("ALTER TABLE rea_jobs ADD COLUMN authorization_scope_note TEXT NOT NULL DEFAULT ''")
        if "approval_confirmed" not in columns:
            db.execute("ALTER TABLE rea_jobs ADD COLUMN approval_confirmed INTEGER NOT NULL DEFAULT 0")
        # A desktop-agent restart cannot know if an in-flight native operation
        # completed. Never replay it automatically; report it as interrupted.
        db.execute(
            "UPDATE rea_jobs SET status='interrupted', error='Windows agent restarted during this job', updated_at=?, finished_at=? WHERE status IN ('queued','running')",
            (_now(), _now()),
        )


def _validate_request(tool_name: str, arguments: dict[str, Any]) -> None:
    _configuration()  # Ensure REA is explicitly enabled and the local executable exists.
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", tool_name):
        raise ReaBridgeError("Invalid REA tool name.")
    if tool_name not in _allowed_tool_names():
        raise ReaBridgeError("Tool is not in REA_ALLOWED_TOOL_NAMES. Review /v1/rea/tools and configure the exact name locally.")
    _validate_argument_scope(arguments)
    encoded = json.dumps(arguments, ensure_ascii=False).encode("utf-8")
    if len(encoded) > 128 * 1024:
        raise ReaBridgeError("REA tool arguments exceed the 128 KB limit.")


def submit_rea_job(tool_name: str, arguments: dict[str, Any], authorization_scope_note: str) -> dict[str, Any]:
    _validate_request(tool_name, arguments)
    if len(authorization_scope_note.strip()) < 15 or len(authorization_scope_note) > 2000:
        raise ReaBridgeError("An authorization scope note of 15-2000 characters is required.")
    task_id = "rea-" + uuid4().hex
    now = _now()
    payload = json.dumps(arguments, ensure_ascii=False)
    with _connect() as db:
        pending_count = db.execute(
            "SELECT COUNT(*) AS n FROM rea_jobs WHERE status IN ('queued','running')"
        ).fetchone()["n"]
        if pending_count >= 10:
            raise ReaBridgeError("REA job queue has reached its 10 pending-job safety limit.")
        db.execute(
            "INSERT INTO rea_jobs(id, tool_name, status, request_json, authorization_scope_note, approval_confirmed, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?, 1, ?, ?)",
            (task_id, tool_name, payload, authorization_scope_note.strip(), now, now),
        )
    task = asyncio.create_task(_run_rea_job(task_id, tool_name, arguments))
    _ACTIVE_JOBS[task_id] = task
    task.add_done_callback(lambda _: _ACTIVE_JOBS.pop(task_id, None))
    return {
        "task_id": task_id,
        "tool_name": tool_name,
        "status": "queued",
        "poll_url": f"/v1/rea/tasks/{task_id}",
        "note": "REA runs on the paired Windows device. A queued job is not complete until its status becomes succeeded.",
    }


async def _run_rea_job(task_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
    with _connect() as db:
        db.execute("UPDATE rea_jobs SET status='running', updated_at=? WHERE id=?", (_now(), task_id))
    try:
        result = await call_rea_tool(tool_name, arguments)
        encoded = json.dumps(result, ensure_ascii=False, default=str)
        if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
            raise ReaBridgeError("REA result exceeds the 4 MB API response limit.")
    except asyncio.CancelledError:
        with _connect() as db:
            db.execute("UPDATE rea_jobs SET status='interrupted', error='Job was interrupted by agent shutdown', updated_at=?, finished_at=? WHERE id=?", (_now(), _now(), task_id))
        raise
    except ReaBridgeError as exc:
        with _connect() as db:
            db.execute("UPDATE rea_jobs SET status='failed', error=?, updated_at=?, finished_at=? WHERE id=?", (str(exc)[:1000], _now(), _now(), task_id))
    except Exception as exc:
        with _connect() as db:
            db.execute("UPDATE rea_jobs SET status='failed', error=?, updated_at=?, finished_at=? WHERE id=?", (f"REA job failed ({type(exc).__name__}); inspect local logs.", _now(), _now(), task_id))
    else:
        with _connect() as db:
            db.execute("UPDATE rea_jobs SET status='succeeded', result_json=?, error=NULL, updated_at=?, finished_at=? WHERE id=?", (encoded, _now(), _now(), task_id))


def read_rea_job(task_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute(
            "SELECT id, tool_name, status, result_json, error, authorization_scope_note, approval_confirmed, created_at, updated_at, finished_at FROM rea_jobs WHERE id=?",
            (task_id,),
        ).fetchone()
    if row is None:
        return None
    result = None
    if row["result_json"]:
        try:
            result = json.loads(row["result_json"])
        except json.JSONDecodeError:
            result = {"status": "unavailable"}
    return {
        "task_id": row["id"],
        "tool_name": row["tool_name"],
        "status": row["status"],
        "result": result,
        "error": row["error"],
        "authorization_scope_note": row["authorization_scope_note"],
        "approval_confirmed": bool(row["approval_confirmed"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


async def shutdown_rea_jobs() -> None:
    tasks = list(_ACTIVE_JOBS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await close_rea_session()
