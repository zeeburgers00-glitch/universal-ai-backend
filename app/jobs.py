"""A durable job queue on SQLite — so the stack works without Redis.

Celery needs a broker, and a broker is one more thing that can be down (or unbilled)
on a free deploy. This queue keeps state in one SQLite file inside `UAI_DATA_ROOT`,
runs handlers on worker threads in the same process, survives restarts, and exposes
progress so long video jobs stop blocking an HTTP request.

Scope, stated honestly: it is single-host. If you run several API containers they do
not share a claim protocol beyond SQLite's own locking, so use one writer container
(or point `UAI_JOBS_DB` at shared storage) until you actually need Celery.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_ATTEMPTS_DEFAULT = 1
TERMINAL = {"done", "failed", "cancelled"}


class JobError(ValueError):
    """Caller asked for something invalid (unknown kind, bad id)."""


# kind -> handler(payload, progress) -> result dict
HANDLERS: dict[str, Callable[[dict[str, Any], Callable[[float, str], None]], dict[str, Any]]] = {}

_lock = threading.Lock()
_started = threading.Event()


def register(kind: str) -> Callable:
    """Decorator: `@register("video.cut_silence")`."""

    def decorator(func: Callable) -> Callable:
        HANDLERS[kind] = func
        return func

    return decorator


def db_path() -> Path:
    explicit = (os.getenv("UAI_JOBS_DB") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    return root / "jobs.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            progress REAL NOT NULL DEFAULT 0,
            stage TEXT NOT NULL DEFAULT '',
            result TEXT,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL
        )
        """
    )
    return connection


def init_db() -> None:
    with _connect():
        pass


def submit(kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if kind not in HANDLERS:
        raise JobError(f"unknown job kind: {kind}. Available: {', '.join(sorted(HANDLERS))}")
    job_id = uuid.uuid4().hex
    now = time.time()
    with _lock, _connect() as connection:
        connection.execute(
            "INSERT INTO jobs (id, kind, payload, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
            (job_id, kind, json.dumps(payload or {}), now),
        )
    ensure_started()
    return get(job_id)


def get(job_id: str) -> dict[str, Any]:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise JobError(f"job not found: {job_id}")
    return _row(row)


def list_jobs(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    query = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return {"total": len(rows), "jobs": [_row(row) for row in rows]}


def cancel(job_id: str) -> dict[str, Any]:
    job = get(job_id)
    if job["status"] in TERMINAL:
        raise JobError(f"job already {job['status']}")
    with _lock, _connect() as connection:
        connection.execute(
            "UPDATE jobs SET status='cancelled', finished_at=? WHERE id=? AND status='queued'",
            (time.time(), job_id),
        )
    return get(job_id)


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "payload": json.loads(row["payload"] or "{}"),
        "status": row["status"],
        "progress": row["progress"],
        "stage": row["stage"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "attempts": row["attempts"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "elapsed": round((row["finished_at"] or time.time()) - (row["started_at"] or row["created_at"]), 2),
    }


# --------------------------------------------------------------------------- #
# Worker loop
# --------------------------------------------------------------------------- #
def _claim() -> dict[str, Any] | None:
    """Atomically take one queued job (SQLite serialises this for us)."""

    with _lock, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            connection.execute("COMMIT")
            return None
        connection.execute(
            "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
            (time.time(), row["id"]),
        )
        connection.execute("COMMIT")
        return _row(row)


def _finish(job_id: str, status: str, result: Any = None, error: str | None = None) -> None:
    with _lock, _connect() as connection:
        connection.execute(
            "UPDATE jobs SET status=?, result=?, error=?, finished_at=?, progress=? WHERE id=?",
            (status, json.dumps(result) if result is not None else None, error, time.time(),
             100.0 if status == "done" else 0.0, job_id),
        )


def _set_progress(job_id: str, progress: float, stage: str) -> None:
    with _lock, _connect() as connection:
        connection.execute(
            "UPDATE jobs SET progress=?, stage=? WHERE id=?",
            (max(0.0, min(100.0, float(progress))), stage[:200], job_id),
        )


def run_once() -> bool:
    """Execute a single queued job. Returns False when the queue was empty."""

    claimed = _claim()
    if claimed is None:
        return False

    handler = HANDLERS.get(claimed["kind"])
    if handler is None:
        _finish(claimed["id"], "failed", error=f"handler disappeared for kind {claimed['kind']}")
        return True

    def progress(value: float, stage: str = "") -> None:
        _set_progress(claimed["id"], value, stage)

    try:
        result = handler(claimed["payload"], progress) or {}
        _finish(claimed["id"], "done", result=result)
    except Exception as exc:  # handler crashed: record it, don't kill the worker
        _finish(claimed["id"], "failed", error=f"{type(exc).__name__}: {exc}"[:2000],
                result={"traceback": traceback.format_exc()[-2000:]})
    return True


def _loop(concurrency: int, poll: float) -> None:
    while True:
        worked = run_once()
        if not worked:
            time.sleep(poll)


def ensure_started(concurrency: int | None = None, poll: float = 0.5) -> bool:
    """Start background worker threads once per process. Returns True if started now."""

    if os.getenv("UAI_JOBS_DISABLE", "").strip() in {"1", "true", "yes"}:
        return False
    if _started.is_set():
        return False
    init_db()
    workers = concurrency or int(os.getenv("UAI_JOBS_CONCURRENCY", "2"))
    for index in range(max(1, workers)):
        thread = threading.Thread(target=_loop, args=(workers, poll), name=f"uai-jobs-{index}", daemon=True)
        thread.start()
    _started.set()
    return True


def stats() -> dict[str, Any]:
    with _connect() as connection:
        rows = connection.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    counts = {row["status"]: row["n"] for row in rows}
    return {
        "db": str(db_path()),
        "worker_threads_running": _started.is_set(),
        "concurrency": int(os.getenv("UAI_JOBS_CONCURRENCY", "2")),
        "counts": counts,
        "total": sum(counts.values()),
        "kinds": sorted(HANDLERS),
    }


# --------------------------------------------------------------------------- #
# Built-in handlers: the video toolkit, queued instead of blocking HTTP
# --------------------------------------------------------------------------- #
def _register_video_handlers() -> None:
    try:
        from . import video_tools
    except Exception:  # pragma: no cover - ffmpeg missing should not break the app
        return

    @register("video.probe")
    def _probe(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(20, "reading metadata")
        return video_tools.probe_media(video_tools.resolve_input(payload["path"]))

    @register("video.cut_silence")
    def _cut(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(10, "detecting silence")
        return video_tools.cut_silence(
            payload["path"],
            float(payload.get("threshold_db", -30.0)),
            float(payload.get("min_silence", 0.6)),
        )

    @register("video.chapters")
    def _chapters(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(10, "detecting pauses")
        return video_tools.chapters(
            payload["path"],
            float(payload.get("threshold_db", -30.0)),
            float(payload.get("min_silence", 0.6)),
            float(payload.get("min_chapter", 25.0)),
        )

    @register("video.thumbnails")
    def _thumbs(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(10, "sampling frames")
        return video_tools.thumbnails(
            payload["path"], int(payload.get("count", 5)), int(payload.get("width", 1280)),
        )

    @register("video.loudnorm")
    def _loudnorm(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(10, "normalising loudness")
        return video_tools.loudnorm(payload["path"], float(payload.get("target_lufs", -14.0)))

    @register("video.clip")
    def _clip(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(10, "cutting clip")
        return video_tools.vertical_clip(
            payload["path"], float(payload["start"]), float(payload["end"]),
            str(payload.get("aspect", "9:16")),
        )

    @register("video.subtitles")
    def _subs(payload: dict[str, Any], progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(30, "converting subtitles")
        return video_tools.convert_subtitles(payload["path"], str(payload.get("to", "vtt")))


_register_video_handlers()
