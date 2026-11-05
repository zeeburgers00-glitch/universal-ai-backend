"""Universal agent task runtime: SQLite-backed queue, approvals, workflows and memory.

For durable production storage, point AGENT_RUNTIME_DB_PATH at a persistent disk.
Serverless /tmp storage is ephemeral and is not a durable queue.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .security import require_api_key

router = APIRouter(
    prefix="/v1/agent-runtime",
    tags=["Universal Agent Runtime"],
    dependencies=[Depends(require_api_key)],
)

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECRET_KEYS = {
    "api_key", "apikey", "authorization", "access_token", "refresh_token",
    "password", "passwd", "client_secret", "private_key", "secret", "token",
    "secret_key", "service_role_key", "worker_token",
}
_TERMINAL = {"succeeded", "failed", "blocked", "cancelled"}
_ACTIVE = {"queued", "pending_approval", "running"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _db_path() -> Path:
    configured = os.getenv("AGENT_RUNTIME_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.getenv("VERCEL") == "1":
        return Path("/tmp/universal-ai-agent-runtime.sqlite3")
    return Path("data/agent_runtime.sqlite3").resolve()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    with _SCHEMA_LOCK:
        conn = sqlite3.connect(key, timeout=20, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if key not in _SCHEMA_READY:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    workflow_id TEXT,
                    step_key TEXT,
                    task_type TEXT NOT NULL,
                    agent_id TEXT,
                    objective TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    lease_seconds INTEGER NOT NULL DEFAULT 180,
                    lease_until TEXT,
                    worker_id TEXT,
                    result_json TEXT,
                    error TEXT,
                    idempotency_key TEXT UNIQUE,
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    approval_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_queue
                    ON agent_tasks(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_workflow
                    ON agent_tasks(workflow_id, created_at);
                CREATE TABLE IF NOT EXISTS agent_task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_task_events
                    ON agent_task_events(task_id, event_id);
                CREATE TABLE IF NOT EXISTS agent_approvals (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE REFERENCES agent_tasks(task_id) ON DELETE CASCADE,
                    risk_level TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    decided_at TEXT,
                    decision_note TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runtime_workers (
                    worker_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    current_task_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runtime_workers_seen
                    ON agent_runtime_workers(last_seen);
                CREATE TABLE IF NOT EXISTS agent_memory (
                    memory_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, memory_key)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_memory_scope
                    ON agent_memory(scope, updated_at);
                """
            )
            conn.commit()
            _SCHEMA_READY.add(key)
        return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _check_secrets(value: Any, path: str = "inputs") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9_]", "", str(key).lower())
            if normalized in _SECRET_KEYS or normalized.endswith("_api_key"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Do not send credentials in task payloads ({path}.{key}); configure secrets server-side.",
                )
            _check_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_secrets(child, f"{path}[{index}]")


@lru_cache(maxsize=3)
def _load_agent_catalog(filename: str) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parent.parent / "catalog"
    path = (root / filename).resolve()
    if root.resolve() not in path.parents or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("agents") or data.get("roles") or []
        return [item for item in items if isinstance(item, dict)]
    return []


def _agent_blueprint(agent_id: str | None) -> dict[str, Any] | None:
    if not agent_id:
        return None
    for filename in ("agents.json", "openavatar_agent_fleet.json", "youtube_agent_fleet.json"):
        for item in _load_agent_catalog(filename):
            if item.get("id") == agent_id:
                blueprint = dict(item)
                label = f"{blueprint.get('id', '')} {blueprint.get('name', '')}".lower()
                if not blueprint.get("risk_level"):
                    if any(word in label for word in ("publish", "publisher", "upload", "delete", "payment", "purchase")):
                        blueprint["risk_level"] = "critical"
                    elif any(word in label for word in ("channel", "voice", "clone", "account", "message")):
                        blueprint["risk_level"] = "high"
                    else:
                        blueprint["risk_level"] = "medium"
                blueprint.setdefault("operating_instructions", blueprint.get("instructions", ""))
                blueprint.setdefault(
                    "human_approval_rules",
                    "Planning only; all external side effects require a separate human approval.",
                )
                return blueprint
    raise HTTPException(status_code=404, detail="Agent blueprint not found in the installed catalogs")


def _effective_risk(requested: str, blueprint: dict[str, Any] | None) -> str:
    levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    catalog_level = str((blueprint or {}).get("risk_level", "low")).lower()
    if catalog_level not in levels:
        catalog_level = "medium"
    return max((requested, catalog_level), key=lambda value: levels[value])


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _validate_input_refs(value: Any, allowed_steps: set[str], path: str = "inputs") -> None:
    if isinstance(value, dict):
        if "$from_step" in value:
            if set(value) != {"$from_step", "path"}:
                raise HTTPException(
                    status_code=422,
                    detail=f"{path}: dependency references must contain only $from_step and path.",
                )
            source = value.get("$from_step")
            result_path = value.get("path")
            if not isinstance(source, str) or source not in allowed_steps:
                raise HTTPException(
                    status_code=422,
                    detail=f"{path}: referenced step must be a direct dependency.",
                )
            if not isinstance(result_path, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", result_path
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"{path}: dependency result path is invalid.",
                )
            return
        for key, child in value.items():
            _validate_input_refs(child, allowed_steps, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_input_refs(child, allowed_steps, f"{path}[{index}]")


def _resolve_input_refs(value: Any, dependency_results: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if "$from_step" in value:
            source = value["$from_step"]
            current = dependency_results[source]
            for segment in value["path"].split("."):
                if isinstance(current, dict) and segment in current:
                    current = current[segment]
                elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
                    current = current[int(segment)]
                else:
                    raise KeyError(f"Dependency result path is missing: {source}.{value['path']}")
            return current
        return {key: _resolve_input_refs(child, dependency_results) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve_input_refs(child, dependency_results) for child in value]
    return value


def _event(conn: sqlite3.Connection, task_id: str, event_type: str, status: str,
           message: str, payload: dict[str, Any] | None = None) -> None:
    conn.execute(
        """INSERT INTO agent_task_events
           (task_id,event_type,status,message,payload_json,created_at)
           VALUES(?,?,?,?,?,?)""",
        (task_id, event_type, status, message[:2000], _json(payload or {}), _iso()),
    )


def _task_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "workflow_id": row["workflow_id"],
        "step_key": row["step_key"],
        "task_type": row["task_type"],
        "agent_id": row["agent_id"],
        "objective": row["objective"],
        "payload": _decode(row["payload_json"], {}),
        "risk_level": row["risk_level"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
        "lease_until": row["lease_until"],
        "worker_id": row["worker_id"],
        "result": _decode(row["result_json"], None),
        "error": row["error"],
        "depends_on": _decode(row["depends_on_json"], []),
        "approval_id": row["approval_id"],
    }


def _approval_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in (
        "approval_id", "task_id", "risk_level", "reason", "status",
        "created_at", "updated_at", "decided_at", "decision_note",
    )}


def _new_approval(conn: sqlite3.Connection, task_id: str, risk_level: str) -> str:
    # Allocate the ID first; the approval row is inserted after its task (FK target).
    return str(uuid.uuid4())


def _insert_task(
    conn: sqlite3.Connection,
    *,
    task_type: str,
    objective: str,
    agent_id: str | None,
    inputs: dict[str, Any],
    risk_level: str,
    max_attempts: int,
    lease_seconds: int,
    idempotency_key: str | None,
    depends_on: list[str],
    dry_run: bool,
    tool_allowlist: list[str],
    workflow_id: str | None = None,
    step_key: str | None = None,
    task_id: str | None = None,
    validate_dependencies: bool = True,
    agent_blueprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM agent_tasks WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            return _task_dict(existing)
    count = conn.execute(
        "SELECT COUNT(*) FROM agent_tasks WHERE status IN ('queued','pending_approval','running')"
    ).fetchone()[0]
    max_pending = max(1, min(10000, int(os.getenv("AGENT_RUNTIME_MAX_PENDING_TASKS", "1000"))))
    if count >= max_pending:
        raise HTTPException(status_code=429, detail="Agent runtime queue is full; retry after workers drain tasks.")
    if validate_dependencies:
        for dependency in depends_on:
            if not conn.execute("SELECT 1 FROM agent_tasks WHERE task_id=?", (dependency,)).fetchone():
                raise HTTPException(status_code=422, detail=f"Unknown dependency task: {dependency}")
    task_id = task_id or str(uuid.uuid4())
    status = "pending_approval" if risk_level in {"high", "critical"} else "queued"
    payload = {
        "inputs": inputs,
        "agent": agent_blueprint or {
            "id": agent_id or "general-agent",
            "name": "General Agent",
            "mission": "Produce a bounded, reviewable action plan for the supplied objective.",
            "capabilities": ["planning", "summarization"],
            "risk_level": risk_level,
            "human_approval_rules": "Planning only; external side effects require human approval.",
        },
        "user_approved": False,
        "dry_run": dry_run,
        "tool_allowlist": tool_allowlist,
        "no_paid_provider_fallback": True,
        "no_secrets_in_prompt": True,
    }
    approval_id = _new_approval(conn, task_id, risk_level) if status == "pending_approval" else None
    now = _iso()
    conn.execute(
        """INSERT INTO agent_tasks
           (task_id,workflow_id,step_key,task_type,agent_id,objective,payload_json,
            risk_level,status,created_at,updated_at,max_attempts,lease_seconds,
            idempotency_key,depends_on_json,approval_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, workflow_id, step_key, task_type, agent_id, objective, _json(payload),
         risk_level, status, now, now, max_attempts, lease_seconds, idempotency_key,
         _json(depends_on), approval_id),
    )
    if approval_id:
        conn.execute(
            """INSERT INTO agent_approvals
               (approval_id,task_id,risk_level,reason,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (approval_id, task_id, risk_level,
             "High-risk or critical task requires explicit human approval.", "pending", now, now),
        )
    _event(conn, task_id, "created", status,
           "Task awaits human approval." if approval_id else "Task added to queue.",
           {"workflow_id": workflow_id, "risk_level": risk_level})
    row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
    return _task_dict(row)


def _refresh_workflow(conn: sqlite3.Connection, workflow_id: str | None) -> None:
    if not workflow_id:
        return
    rows = conn.execute(
        "SELECT status FROM agent_tasks WHERE workflow_id=?", (workflow_id,)
    ).fetchall()
    states = [row["status"] for row in rows]
    if states and all(state == "succeeded" for state in states):
        status = "completed"
    elif any(state in {"failed", "blocked", "cancelled"} for state in states):
        status = "failed"
    else:
        status = "running"
    conn.execute(
        "UPDATE agent_workflows SET status=?,updated_at=? WHERE workflow_id=?",
        (status, _iso(), workflow_id),
    )


class TaskCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=12000)
    agent_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
    task_type: str = Field(default="agent", min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    inputs: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    dry_run: bool = False
    tool_allowlist: list[str] = Field(default_factory=list, max_length=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    lease_seconds: int = Field(default=180, ge=15, le=3600)
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class WorkflowStep(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    objective: str = Field(min_length=3, max_length=12000)
    agent_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
    task_type: str = Field(default="agent", min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    inputs: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    dry_run: bool = False
    tool_allowlist: list[str] = Field(default_factory=list, max_length=100)
    depends_on: list[str] = Field(default_factory=list, max_length=100)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    lease_seconds: int = Field(default=180, ge=15, le=3600)


class WorkerRegister(BaseModel):
    worker_id: str = Field(min_length=2, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    capabilities: dict[str, Any] = Field(default_factory=dict)


class WorkerDrainRequest(BaseModel):
    reason: str = Field(default="Operator requested worker drain.", max_length=500)


class WorkerClaim(BaseModel):
    worker_id: str = Field(min_length=2, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class WorkerHeartbeat(BaseModel):
    extend_seconds: int = Field(default=180, ge=15, le=3600)


class WorkerComplete(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class WorkerFail(BaseModel):
    error: str = Field(min_length=1, max_length=4000)
    retryable: bool = True


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=2000)


class MemoryWrite(BaseModel):
    scope: str = Field(default="default", min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    key: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=30000)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/catalog")
def unified_agent_catalog(
    query: str | None = Query(default=None, max_length=200),
    source: str | None = Query(default=None, pattern=r"^(general|openavatar|youtube)$"),
    risk_level: str | None = Query(default=None, pattern=r"^(low|medium|high|critical)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100000),
):
    catalogs = {
        "general": "agents.json",
        "openavatar": "openavatar_agent_fleet.json",
        "youtube": "youtube_agent_fleet.json",
    }
    sources = [source] if source else list(catalogs)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_id in sources:
        for raw in _load_agent_catalog(catalogs[source_id]):
            agent_id = str(raw.get("id") or raw.get("role_id") or "")
            if not agent_id or agent_id in seen:
                continue
            seen.add(agent_id)
            item = dict(raw)
            item["id"] = agent_id
            item["source"] = source_id
            if source_id == "youtube":
                label = f"{agent_id} {item.get('name', '')}".lower()
                item["risk_level"] = (
                    "critical" if any(word in label for word in ("publish", "publisher", "upload", "delete", "payment", "purchase"))
                    else "high" if any(word in label for word in ("channel", "voice", "clone", "account", "message"))
                    else "medium"
                )
            else:
                item.setdefault("risk_level", "medium")
            item.setdefault("capabilities", [])
            item.setdefault("mission", item.get("description", item.get("role_id", "Specialist agent role")))
            item.setdefault("allowed_tool_families", item.get("tool_families", []))
            items.append(item)
    if query:
        needle = query.casefold()
        items = [item for item in items if needle in " ".join([
            str(item.get("id", "")), str(item.get("name", "")),
            str(item.get("mission", "")), " ".join(map(str, item.get("capabilities", []))),
        ]).casefold()]
    if risk_level:
        items = [item for item in items if item.get("risk_level") == risk_level]
    items.sort(key=lambda item: (item.get("source", ""), item.get("id", "")))
    return {
        "total": len(items),
        "items": items[offset:offset + limit],
        "limit": limit,
        "offset": offset,
        "catalog_sources": list(sources),
        "note": "Catalog entries are role blueprints, not running processes. Every write or external side effect must pass worker, permission, consent and approval controls.",
    }


@router.get("/catalog/{agent_id}")
def unified_agent_detail(agent_id: str):
    blueprint = _agent_blueprint(agent_id)
    if not blueprint:
        raise HTTPException(status_code=404, detail="Agent blueprint not found")
    return blueprint


@router.get("/status")
def runtime_status():
    path = _db_path()
    with _db() as conn:
        counts = {
            row["status"]: row["total"]
            for row in conn.execute(
                "SELECT status,COUNT(*) AS total FROM agent_tasks GROUP BY status"
            ).fetchall()
        }
        memories = conn.execute("SELECT COUNT(*) FROM agent_memory").fetchone()[0]
        workers = conn.execute("SELECT COUNT(*) FROM agent_runtime_workers").fetchone()[0]
        online_cutoff = _iso(_now() - timedelta(seconds=90))
        online_workers = conn.execute(
            "SELECT COUNT(*) FROM agent_runtime_workers WHERE last_seen>=?", (online_cutoff,)
        ).fetchone()[0]
    attested = os.getenv("AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED", "false").lower() == "true"
    return {
        "service": "universal-agent-runtime",
        "storage": "sqlite",
        "database_path": str(path),
        "storage_note": (
            "The configured path is on the local filesystem. Use a persistent mounted disk for durable production state."
            if not str(path).startswith("/tmp")
            else "This /tmp database is ephemeral; data may be lost on restart or serverless cold start."
        ),
        "task_counts": counts,
        "memory_records": memories,
        "workers_known": workers,
        "workers_seen_within_90s": online_workers,
        "running_tasks": counts.get("running", 0),
        "max_parallel_tasks": _bounded_env_int("AGENT_RUNTIME_MAX_PARALLEL_TASKS", 5, 1, 20),
        "max_parallel_per_agent": _bounded_env_int("AGENT_RUNTIME_MAX_PARALLEL_PER_AGENT", 1, 1, 10),
        "execution_attested_no_card": attested,
        "no_card_only": True,
        "paid_provider_fallback": False,
        "features": ["task_queue", "leases", "retries", "manual_retry", "workflow_dag", "workflow_output_handoffs", "bounded_concurrency", "human_approvals", "scoped_memory", "event_log", "unified_agent_catalog", "worker_registry", "worker_drain", "prometheus_metrics"],
    }



@router.get("/metrics", response_class=PlainTextResponse)
def runtime_metrics():
    """Prometheus exposition format for queue, worker, approval and memory health."""
    now = _now()
    with _db() as conn:
        task_rows = conn.execute("SELECT status,COUNT(*) AS total FROM agent_tasks GROUP BY status").fetchall()
        worker_rows = conn.execute("SELECT status,last_seen FROM agent_runtime_workers").fetchall()
        approval_rows = conn.execute("SELECT status,COUNT(*) AS total FROM agent_approvals GROUP BY status").fetchall()
        memory_total = int(conn.execute("SELECT COUNT(*) FROM agent_memory").fetchone()[0])
        oldest = conn.execute("SELECT MIN(created_at) FROM agent_tasks WHERE status='queued'").fetchone()[0]
    task_counts = {str(row["status"]): int(row["total"]) for row in task_rows}
    approval_counts = {str(row["status"]): int(row["total"]) for row in approval_rows}
    worker_counts = {"idle": 0, "busy": 0, "draining": 0, "offline": 0}
    cutoff = now - timedelta(seconds=90)
    for row in worker_rows:
        status = "offline" if row["last_seen"] < _iso(cutoff) else str(row["status"])
        if status in worker_counts:
            worker_counts[status] += 1
    task_statuses = ("queued", "pending_approval", "running", "succeeded", "failed", "blocked", "cancelled")
    approval_statuses = ("pending", "approved", "rejected")
    lines = ["# HELP agent_runtime_tasks Current task count by lifecycle status.", "# TYPE agent_runtime_tasks gauge"]
    lines.extend(f'agent_runtime_tasks{{status="{s}"}} {task_counts.get(s, 0)}' for s in task_statuses)
    lines.extend(["# HELP agent_runtime_workers Current worker count by liveness status.", "# TYPE agent_runtime_workers gauge"])
    lines.extend(f'agent_runtime_workers{{status="{s}"}} {worker_counts[s]}' for s in ("idle", "busy", "draining", "offline"))
    lines.extend(["# HELP agent_runtime_approvals Current approval count by status.", "# TYPE agent_runtime_approvals gauge"])
    lines.extend(f'agent_runtime_approvals{{status="{s}"}} {approval_counts.get(s, 0)}' for s in approval_statuses)
    oldest_age = 0.0
    if oldest:
        try:
            oldest_age = max(0.0, (now - datetime.fromisoformat(oldest)).total_seconds())
        except ValueError:
            oldest_age = 0.0
    lines.extend([
        "# HELP agent_runtime_queue_oldest_seconds Age of the oldest queued task.",
        "# TYPE agent_runtime_queue_oldest_seconds gauge",
        f"agent_runtime_queue_oldest_seconds {oldest_age:.3f}",
        "# HELP agent_runtime_memory_records Number of stored memory records.",
        "# TYPE agent_runtime_memory_records gauge",
        f"agent_runtime_memory_records {memory_total}",
        "# HELP agent_runtime_execution_attested_no_card Whether worker no-card attestation is enabled.",
        "# TYPE agent_runtime_execution_attested_no_card gauge",
        f"agent_runtime_execution_attested_no_card {1 if os.getenv('AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED', 'false').lower() == 'true' else 0}",
        "# HELP agent_runtime_max_pending_tasks Configured queue capacity.",
        "# TYPE agent_runtime_max_pending_tasks gauge",
        f"agent_runtime_max_pending_tasks {_bounded_env_int('AGENT_RUNTIME_MAX_PENDING_TASKS', 1000, 1, 10000)}",
        "",
    ])
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4; charset=utf-8")


@router.post("/tasks", status_code=202)
def create_task(body: TaskCreate):
    _check_secrets(body.inputs)
    _check_secrets(body.tool_allowlist, "tool_allowlist")
    _validate_input_refs(body.inputs, set())
    blueprint = _agent_blueprint(body.agent_id)
    effective_risk = _effective_risk(body.risk_level, blueprint)
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = _insert_task(
            conn, task_type=body.task_type, objective=body.objective, agent_id=body.agent_id,
            inputs=body.inputs, risk_level=effective_risk, max_attempts=body.max_attempts,
            lease_seconds=body.lease_seconds, idempotency_key=body.idempotency_key,
            depends_on=body.depends_on, dry_run=body.dry_run,
            tool_allowlist=body.tool_allowlist, agent_blueprint=blueprint,
        )
        return task


@router.get("/tasks")
def list_tasks(
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100000),
):
    with _db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks" + (" WHERE status=?" if status else ""),
            (status,) if status else (),
        ).fetchone()[0]
    return {"items": [_task_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    with _db() as conn:
        row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(row)


@router.get("/tasks/{task_id}/events")
def get_task_events(task_id: str, limit: int = Query(default=200, ge=1, le=500)):
    with _db() as conn:
        exists = conn.execute("SELECT 1 FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Task not found")
        rows = conn.execute(
            "SELECT * FROM agent_task_events WHERE task_id=? ORDER BY event_id ASC LIMIT ?",
            (task_id, limit),
        ).fetchall()
    return {"items": [{
        "event_id": row["event_id"], "event_type": row["event_type"], "status": row["status"],
        "message": row["message"], "payload": _decode(row["payload_json"], {}),
        "created_at": row["created_at"],
    } for row in rows]}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        if row["status"] in _TERMINAL:
            raise HTTPException(status_code=409, detail=f"Task is already {row['status']}")
        if row["status"] == "running":
            raise HTTPException(status_code=409, detail="A running task cannot be hard-cancelled. Stop it through the executor, then report its final state.")
        now = _iso()
        if row["approval_id"] and row["status"] == "pending_approval":
            conn.execute(
                """UPDATE agent_approvals SET status='rejected',updated_at=?,decided_at=?,
                   decision_note=? WHERE approval_id=? AND status='pending'""",
                (now, now, "Cancelled by API request.", row["approval_id"]),
            )
        conn.execute(
            "UPDATE agent_tasks SET status='cancelled',worker_id=NULL,lease_until=NULL,updated_at=? WHERE task_id=?",
            (now, task_id),
        )
        _event(conn, task_id, "cancelled", "cancelled", "Task cancelled by API request.")
        _refresh_workflow(conn, row["workflow_id"])
        return {"task_id": task_id, "status": "cancelled"}



@router.post("/tasks/{task_id}/retry", status_code=202)
def retry_failed_task(task_id: str):
    """Manually requeue a terminal failure; high-risk work must be approved again."""
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        if row["workflow_id"]:
            raise HTTPException(status_code=409, detail="Retry failed workflow steps by submitting a new workflow; individual step replay is not supported.")
        if row["status"] != "failed":
            raise HTTPException(status_code=409, detail=f"Only failed tasks can be manually retried (current status: {row['status']}).")
        now = _iso()
        approval_id = row["approval_id"]
        next_status = "queued"
        if row["risk_level"] in {"high", "critical"}:
            next_status = "pending_approval"
            if approval_id:
                conn.execute(
                    """UPDATE agent_approvals SET status='pending',created_at=?,updated_at=?,decided_at=NULL,
                       decision_note=NULL,reason=? WHERE approval_id=?""",
                    (now, now, "Manual retry of high-risk or critical task requires fresh approval.", approval_id),
                )
            else:
                approval_id = _new_approval(conn, task_id, row["risk_level"])
                conn.execute(
                    """INSERT INTO agent_approvals
                       (approval_id,task_id,risk_level,reason,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (approval_id, task_id, row["risk_level"],
                     "Manual retry of high-risk or critical task requires fresh approval.",
                     "pending", now, now),
                )
        conn.execute(
            """UPDATE agent_tasks SET status=?,attempts=0,worker_id=NULL,lease_until=NULL,
               result_json=NULL,error=NULL,approval_id=?,updated_at=? WHERE task_id=?""",
            (next_status, approval_id, now, task_id),
        )
        _event(
            conn, task_id, "manual_retry", next_status,
            "Task manually requeued; fresh human approval is required." if next_status == "pending_approval"
            else "Task manually requeued by operator.",
            {"previous_attempts": row["attempts"], "approval_required": next_status == "pending_approval"},
        )
        refreshed = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        return _task_dict(refreshed)


@router.post("/workers/register")
def register_worker(body: WorkerRegister):
    _check_secrets(body.capabilities, "capabilities")
    now = _iso()
    with _db() as conn:
        conn.execute(
            """INSERT INTO agent_runtime_workers
               (worker_id,status,capabilities_json,created_at,updated_at,last_seen,current_task_id)
               VALUES(?,?,?,?,?,?,NULL)
               ON CONFLICT(worker_id) DO UPDATE SET
                 status=CASE WHEN agent_runtime_workers.status='draining' THEN 'draining' WHEN agent_runtime_workers.current_task_id IS NULL THEN 'idle' ELSE agent_runtime_workers.status END,
                 capabilities_json=excluded.capabilities_json,
                 updated_at=excluded.updated_at,last_seen=excluded.last_seen""",
            (body.worker_id, "idle", _json(body.capabilities), now, now, now),
        )
        updated = conn.execute(
            "SELECT status FROM agent_runtime_workers WHERE worker_id=?", (body.worker_id,)
        ).fetchone()
    return {"worker_id": body.worker_id, "status": updated["status"], "last_seen": now}



@router.post("/workers/{worker_id}/drain")
def drain_worker(worker_id: str, body: WorkerDrainRequest = WorkerDrainRequest()):
    """Stop assigning new tasks while allowing the current lease to finish."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_runtime_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Worker not found")
        conn.execute(
            "UPDATE agent_runtime_workers SET status='draining',updated_at=? WHERE worker_id=?",
            (_iso(), worker_id),
        )
    return {
        "worker_id": worker_id,
        "status": "draining",
        "current_task_id": row["current_task_id"],
        "reason": body.reason,
        "new_tasks_enabled": False,
    }


@router.post("/workers/{worker_id}/undrain")
def undrain_worker(worker_id: str):
    """Allow a drained worker to claim tasks again."""
    now = _iso()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_runtime_workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Worker not found")
        active = None
        if row["current_task_id"]:
            active = conn.execute(
                """SELECT task_id FROM agent_tasks WHERE task_id=? AND worker_id=?
                   AND status='running' AND lease_until>=?""",
                (row["current_task_id"], worker_id, now),
            ).fetchone()
        status = "busy" if active else "idle"
        conn.execute(
            "UPDATE agent_runtime_workers SET status=?,current_task_id=?,updated_at=? WHERE worker_id=?",
            (status, active["task_id"] if active else None, now, worker_id),
        )
    return {"worker_id": worker_id, "status": status, "new_tasks_enabled": True}


@router.get("/workers")
def list_runtime_workers(
    stale_after_seconds: int = Query(default=90, ge=15, le=3600),
    limit: int = Query(default=100, ge=1, le=500),
):
    cutoff = _iso(_now() - timedelta(seconds=stale_after_seconds))
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runtime_workers ORDER BY last_seen DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [{
        "worker_id": row["worker_id"],
        "status": "offline" if row["last_seen"] < cutoff else row["status"],
        "last_seen": row["last_seen"],
        "current_task_id": row["current_task_id"],
        "capabilities": _decode(row["capabilities_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    } for row in rows], "stale_after_seconds": stale_after_seconds}


@router.post("/workers/claim")
def claim_task(body: WorkerClaim):
    if os.getenv("AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="Worker execution is disabled until no-card/free-only operation is attested.")
    now = _now()
    now_s = _iso(now)
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO agent_runtime_workers
               (worker_id,status,capabilities_json,created_at,updated_at,last_seen,current_task_id)
               VALUES(?,?,?,?,?,?,NULL)
               ON CONFLICT(worker_id) DO UPDATE SET
                 status=CASE WHEN agent_runtime_workers.current_task_id IS NULL THEN 'idle' ELSE agent_runtime_workers.status END,
                 updated_at=excluded.updated_at,last_seen=excluded.last_seen""",
            (body.worker_id, "idle", "{}", now_s, now_s, now_s),
        )
        expired = conn.execute(
            "SELECT * FROM agent_tasks WHERE status='running' AND lease_until IS NOT NULL AND lease_until<?",
            (now_s,),
        ).fetchall()
        for row in expired:
            retry = row["attempts"] < row["max_attempts"]
            status = "queued" if retry else "failed"
            conn.execute(
                """UPDATE agent_tasks SET status=?,worker_id=NULL,lease_until=NULL,updated_at=?,
                   error=? WHERE task_id=?""",
                (status, now_s, "Worker lease expired.", row["task_id"]),
            )
            if row["worker_id"]:
                conn.execute(
                    """UPDATE agent_runtime_workers SET status=CASE WHEN status='draining' THEN 'draining' ELSE 'offline' END,
                       current_task_id=NULL,updated_at=? WHERE worker_id=?""",
                    (now_s, row["worker_id"]),
                )
            _event(conn, row["task_id"], "lease_expired", status, "Worker lease expired; task returned to queue." if retry else "Worker lease expired; retry limit reached.")
            _refresh_workflow(conn, row["workflow_id"])
        worker_state = conn.execute("SELECT status FROM agent_runtime_workers WHERE worker_id=?", (body.worker_id,)).fetchone()
        if worker_state and worker_state["status"] == "draining":
            return {"task": None, "queue_empty": True, "worker_draining": True}
        owned_task = conn.execute(
            "SELECT * FROM agent_tasks WHERE status='running' AND worker_id=? AND lease_until>=? LIMIT 1",
            (body.worker_id, now_s),
        ).fetchone()
        if owned_task:
            conn.execute(
                "UPDATE agent_runtime_workers SET status='busy',current_task_id=?,updated_at=?,last_seen=? WHERE worker_id=?",
                (owned_task["task_id"], now_s, now_s, body.worker_id),
            )
            return {"task": None, "queue_empty": True, "worker_busy": True}
        max_parallel = _bounded_env_int("AGENT_RUNTIME_MAX_PARALLEL_TASKS", 5, 1, 20)
        max_per_agent = _bounded_env_int("AGENT_RUNTIME_MAX_PARALLEL_PER_AGENT", 1, 1, 10)
        running_total = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE status='running'"
        ).fetchone()[0]
        if running_total >= max_parallel:
            conn.execute(
                "UPDATE agent_runtime_workers SET status='idle',current_task_id=NULL,updated_at=?,last_seen=? WHERE worker_id=?",
                (now_s, now_s, body.worker_id),
            )
            return {"task": None, "queue_empty": False, "concurrency_limited": True}
        candidates = conn.execute(
            "SELECT * FROM agent_tasks WHERE status='queued' ORDER BY created_at ASC LIMIT 200"
        ).fetchall()
        selected = None
        per_agent_limited = False
        for row in candidates:
            dependencies = _decode(row["depends_on_json"], [])
            if dependencies:
                placeholders = ",".join("?" for _ in dependencies)
                dep_rows = conn.execute(
                    f"SELECT task_id,status,step_key,result_json FROM agent_tasks WHERE task_id IN ({placeholders})",
                    tuple(dependencies),
                ).fetchall()
                dep_states = {item["task_id"]: item["status"] for item in dep_rows}
                dependency_results = {
                    str(item["step_key"]): _decode(item["result_json"], {})
                    for item in dep_rows if item["step_key"]
                }
                if any(dep_states.get(dep) in {"failed", "blocked", "cancelled"} for dep in dependencies):
                    conn.execute(
                        "UPDATE agent_tasks SET status='blocked',updated_at=?,error=? WHERE task_id=?",
                        (now_s, "A dependency did not complete successfully.", row["task_id"]),
                    )
                    _event(conn, row["task_id"], "dependency_blocked", "blocked", "A dependency did not complete successfully.")
                    _refresh_workflow(conn, row["workflow_id"])
                    continue
                if not all(dep_states.get(dep) == "succeeded" for dep in dependencies):
                    continue
                task_payload = _decode(row["payload_json"], {})
                original_inputs = task_payload.get("inputs") or {}
                try:
                    resolved_inputs = _resolve_input_refs(original_inputs, dependency_results)
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    conn.execute(
                        "UPDATE agent_tasks SET status='blocked',updated_at=?,error=? WHERE task_id=?",
                        (now_s, str(exc)[:1000], row["task_id"]),
                    )
                    _event(conn, row["task_id"], "dependency_output_missing", "blocked",
                           "A referenced dependency output was unavailable.")
                    _refresh_workflow(conn, row["workflow_id"])
                    continue
                if resolved_inputs != original_inputs:
                    task_payload["inputs"] = resolved_inputs
                    conn.execute(
                        "UPDATE agent_tasks SET payload_json=?,updated_at=? WHERE task_id=?",
                        (_json(task_payload), now_s, row["task_id"]),
                    )
                    _event(conn, row["task_id"], "dependency_outputs_resolved", "queued",
                           "Resolved workflow inputs from completed dependency outputs.",
                           {"source_steps": sorted(dependency_results)})
                    row = conn.execute(
                        "SELECT * FROM agent_tasks WHERE task_id=?", (row["task_id"],)
                    ).fetchone()
            if row["agent_id"]:
                current_for_agent = conn.execute(
                    "SELECT COUNT(*) FROM agent_tasks WHERE status='running' AND agent_id=?",
                    (row["agent_id"],),
                ).fetchone()[0]
                if current_for_agent >= max_per_agent:
                    per_agent_limited = True
                    continue
            selected = row
            break
        if not selected:
            conn.execute(
                "UPDATE agent_runtime_workers SET status='idle',current_task_id=NULL,updated_at=?,last_seen=? WHERE worker_id=?",
                (now_s, now_s, body.worker_id),
            )
            return {"task": None, "queue_empty": not per_agent_limited,
                    "concurrency_limited": running_total >= max_parallel or per_agent_limited}
        lease_seconds = selected["lease_seconds"]
        lease_until = _iso(now + timedelta(seconds=lease_seconds))
        attempt = selected["attempts"] + 1
        conn.execute(
            """UPDATE agent_tasks SET status='running',worker_id=?,lease_until=?,attempts=?,updated_at=?
               WHERE task_id=? AND status='queued'""",
            (body.worker_id, lease_until, attempt, now_s, selected["task_id"]),
        )
        conn.execute(
            "UPDATE agent_runtime_workers SET status='busy',current_task_id=?,updated_at=?,last_seen=? WHERE worker_id=?",
            (selected["task_id"], now_s, now_s, body.worker_id),
        )
        _event(conn, selected["task_id"], "claimed", "running", "Task claimed by worker.",
               {"worker_id": body.worker_id, "attempt": attempt, "lease_until": lease_until})
        current = conn.execute("SELECT * FROM agent_tasks WHERE task_id=?", (selected["task_id"],)).fetchone()
        return {"task": _task_dict(current), "queue_empty": False}


@router.post("/workers/{worker_id}/tasks/{task_id}/heartbeat")
def heartbeat_task(worker_id: str, task_id: str, body: WorkerHeartbeat):
    now = _now()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE task_id=? AND status='running' AND worker_id=?",
            (task_id, worker_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="Task is not leased to this worker")
        if row["lease_until"] and row["lease_until"] < _iso(now):
            raise HTTPException(status_code=409, detail="Worker lease has expired")
        lease_until = _iso(now + timedelta(seconds=body.extend_seconds))
        conn.execute("UPDATE agent_tasks SET lease_until=?,updated_at=? WHERE task_id=?",
                     (lease_until, _iso(now), task_id))
        conn.execute(
            "UPDATE agent_runtime_workers SET status=CASE WHEN status='draining' THEN 'draining' ELSE 'busy' END,last_seen=?,updated_at=? WHERE worker_id=?",
            (_iso(now), _iso(now), worker_id),
        )
        _event(conn, task_id, "heartbeat", "running", "Worker lease extended.",
               {"worker_id": worker_id, "lease_until": lease_until})
    return {"task_id": task_id, "lease_until": lease_until}


@router.post("/workers/{worker_id}/tasks/{task_id}/complete")
def complete_task(worker_id: str, task_id: str, body: WorkerComplete):
    _check_secrets(body.result, "result")
    encoded = _json(body.result)
    if len(encoded.encode("utf-8")) > 262144:
        raise HTTPException(status_code=413, detail="Task result exceeds 256 KiB; store large outputs as artifacts.")
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE task_id=? AND status='running' AND worker_id=?",
            (task_id, worker_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="Task is not running under this worker")
        if row["lease_until"] and row["lease_until"] < _iso():
            raise HTTPException(status_code=409, detail="Worker lease expired; stale completion rejected")
        conn.execute(
            """UPDATE agent_tasks SET status='succeeded',result_json=?,error=NULL,
               worker_id=NULL,lease_until=NULL,updated_at=? WHERE task_id=?""",
            (encoded, _iso(), task_id),
        )
        conn.execute(
            "UPDATE agent_runtime_workers SET status=CASE WHEN status='draining' THEN 'draining' ELSE 'idle' END,current_task_id=NULL,last_seen=?,updated_at=? WHERE worker_id=?",
            (_iso(), _iso(), worker_id),
        )
        _event(conn, task_id, "completed", "succeeded", "Task completed successfully.")
        _refresh_workflow(conn, row["workflow_id"])
    return {"task_id": task_id, "status": "succeeded"}


@router.post("/workers/{worker_id}/tasks/{task_id}/fail")
def fail_task(worker_id: str, task_id: str, body: WorkerFail):
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE task_id=? AND status='running' AND worker_id=?",
            (task_id, worker_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="Task is not running under this worker")
        retry = body.retryable and row["attempts"] < row["max_attempts"]
        status = "queued" if retry else "failed"
        conn.execute(
            """UPDATE agent_tasks SET status=?,error=?,worker_id=NULL,lease_until=NULL,updated_at=?
               WHERE task_id=?""",
            (status, body.error[:4000], _iso(), task_id),
        )
        conn.execute(
            "UPDATE agent_runtime_workers SET status='idle',current_task_id=NULL,last_seen=?,updated_at=? WHERE worker_id=?",
            (_iso(), _iso(), worker_id),
        )
        _event(conn, task_id, "failed", status, body.error, {"retryable": body.retryable})
        _refresh_workflow(conn, row["workflow_id"])
    return {"task_id": task_id, "status": status, "will_retry": retry}


def _validate_dag(steps: list[WorkflowStep]) -> None:
    by_id = {step.id: step for step in steps}
    if len(by_id) != len(steps):
        raise HTTPException(status_code=422, detail="Workflow step IDs must be unique.")
    for step in steps:
        unknown = set(step.depends_on) - set(by_id)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown dependencies for {step.id}: {sorted(unknown)}")
        if step.id in step.depends_on:
            raise HTTPException(status_code=422, detail=f"Workflow step {step.id} cannot depend on itself.")
    remaining = {step.id: set(step.depends_on) for step in steps}
    ready = [key for key, deps in remaining.items() if not deps]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for key in remaining:
            if current in remaining[key]:
                remaining[key].remove(current)
                if not remaining[key]:
                    ready.append(key)
    if visited != len(steps):
        raise HTTPException(status_code=422, detail="Workflow contains a dependency cycle.")
    for step in steps:
        _validate_input_refs(step.inputs, set(step.depends_on), f"steps.{step.id}.inputs")


@router.post("/workflows", status_code=202)
def create_workflow(body: WorkflowCreate):
    blueprints: dict[str, dict[str, Any] | None] = {}
    for step in body.steps:
        _check_secrets(step.inputs, f"steps.{step.id}.inputs")
        blueprints[step.id] = _agent_blueprint(step.agent_id)
    _validate_dag(body.steps)
    workflow_id = str(uuid.uuid4())
    step_task_ids = {step.id: str(uuid.uuid4()) for step in body.steps}
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        now = _iso()
        conn.execute(
            "INSERT INTO agent_workflows(workflow_id,name,status,created_at,updated_at) VALUES(?,?,?,?,?)",
            (workflow_id, body.name, "queued", now, now),
        )
        for step in body.steps:
            deps = [step_task_ids[key] for key in step.depends_on]
            task = _insert_task(
                conn, task_type=step.task_type, objective=step.objective, agent_id=step.agent_id,
                inputs=step.inputs, risk_level=_effective_risk(step.risk_level, blueprints[step.id]), max_attempts=body.max_attempts,
                lease_seconds=body.lease_seconds, idempotency_key=f"workflow:{workflow_id}:{step.id}",
                depends_on=deps, dry_run=step.dry_run, tool_allowlist=step.tool_allowlist,
                workflow_id=workflow_id, step_key=step.id,
                task_id=step_task_ids[step.id], validate_dependencies=False,
                agent_blueprint=blueprints[step.id],
            )
            if task["task_id"] != step_task_ids[step.id]:
                raise HTTPException(status_code=409, detail="Workflow idempotency collision.")
        tasks = conn.execute(
            "SELECT * FROM agent_tasks WHERE workflow_id=? ORDER BY created_at ASC",
            (workflow_id,),
        ).fetchall()
    return {"workflow_id": workflow_id, "name": body.name, "status": "queued",
            "tasks": [_task_dict(row) for row in tasks]}


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    with _db() as conn:
        workflow = conn.execute(
            "SELECT * FROM agent_workflows WHERE workflow_id=?", (workflow_id,)
        ).fetchone()
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        tasks = conn.execute(
            "SELECT * FROM agent_tasks WHERE workflow_id=? ORDER BY created_at ASC",
            (workflow_id,),
        ).fetchall()
    return {"workflow_id": workflow["workflow_id"], "name": workflow["name"],
            "status": workflow["status"], "created_at": workflow["created_at"],
            "updated_at": workflow["updated_at"], "tasks": [_task_dict(row) for row in tasks]}


@router.get("/approvals")
def list_approvals(status: str | None = Query(default=None, max_length=30),
                   limit: int = Query(default=100, ge=1, le=200)):
    with _db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM agent_approvals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_approvals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return {"items": [_approval_dict(row) for row in rows]}


@router.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: str, body: ApprovalDecision):
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        approval = conn.execute(
            "SELECT * FROM agent_approvals WHERE approval_id=?", (approval_id,)
        ).fetchone()
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        if approval["status"] != "pending":
            raise HTTPException(status_code=409, detail="Approval has already been decided")
        task = conn.execute(
            "SELECT * FROM agent_tasks WHERE task_id=?", (approval["task_id"],)
        ).fetchone()
        task_status = "queued" if body.decision == "approved" else "cancelled"
        now = _iso()
        conn.execute(
            """UPDATE agent_approvals SET status=?,updated_at=?,decided_at=?,decision_note=?
               WHERE approval_id=?""",
            (body.decision, now, now, body.note, approval_id),
        )
        task_payload = _decode(task["payload_json"], {})
        if body.decision == "approved":
            task_payload["user_approved"] = True
        conn.execute(
            "UPDATE agent_tasks SET status=?,updated_at=?,error=?,payload_json=? WHERE task_id=?",
            (task_status, now, None if body.decision == "approved" else "Rejected by human approval.",
             _json(task_payload), task["task_id"]),
        )
        _event(conn, task["task_id"], "approval", task_status,
               f"Human approval decision: {body.decision}.", {"note": body.note})
        _refresh_workflow(conn, task["workflow_id"])
        updated = conn.execute(
            "SELECT * FROM agent_approvals WHERE approval_id=?", (approval_id,)
        ).fetchone()
    return _approval_dict(updated)


@router.post("/memory", status_code=201)
def write_memory(body: MemoryWrite):
    _check_secrets(body.metadata, "metadata")
    memory_id = str(uuid.uuid4())
    now = _iso()
    with _db() as conn:
        conn.execute(
            """INSERT INTO agent_memory(memory_id,scope,memory_key,content,metadata_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(scope,memory_key) DO UPDATE SET
                 content=excluded.content,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
            (memory_id, body.scope, body.key, body.content, _json(body.metadata), now, now),
        )
        row = conn.execute(
            "SELECT * FROM agent_memory WHERE scope=? AND memory_key=?",
            (body.scope, body.key),
        ).fetchone()
    return {"memory_id": row["memory_id"], "scope": row["scope"], "key": row["memory_key"],
            "content": row["content"], "metadata": _decode(row["metadata_json"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


@router.get("/memory")
def search_memory(
    scope: str = Query(default="default", min_length=1, max_length=120),
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
):
    with _db() as conn:
        if query:
            rows = conn.execute(
                """SELECT * FROM agent_memory WHERE scope=? AND
                   (memory_key LIKE ? OR content LIKE ?) ORDER BY updated_at DESC LIMIT ?""",
                (scope, f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_memory WHERE scope=? ORDER BY updated_at DESC LIMIT ?",
                (scope, limit),
            ).fetchall()
    return {"items": [{
        "memory_id": row["memory_id"], "scope": row["scope"], "key": row["memory_key"],
        "content": row["content"], "metadata": _decode(row["metadata_json"], {}),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    } for row in rows]}


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str):
    with _db() as conn:
        result = conn.execute("DELETE FROM agent_memory WHERE memory_id=?", (memory_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Memory record not found")
    return {"memory_id": memory_id, "deleted": True}
