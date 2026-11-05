"""OpenAvatar Studio API: a no-card-first, worker-based avatar/video job control plane.

The API never provisions paid GPU capacity and never accepts payment credentials.
GPU execution is delegated to explicitly enabled free-tier workers.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .security import require_api_key
from .task_gateway import post_worker, service_status

router = APIRouter()
api = APIRouter(prefix="/v1/openavatar", tags=["OpenAvatar Studio"])
internal = APIRouter(prefix="/internal/openavatar", tags=["OpenAvatar workers"])

_PROVIDER_NAMES = {"local_cpu", "huggingface_zerogpu", "kaggle", "lightning"}
_JOB_ENGINES = {
    "talking_head": "sadtalker",
    "lip_sync": "musetalk",
    "voice": "openvoice_v2",
    "transcribe": "whisper_cpp",
    "captions": "whisper_cpp",
    "render": "ffmpeg",
}
_CONTENT_TYPES = {
    "portrait": {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"},
    "audio": {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/flac": ".flac"},
    "video": {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"},
}
_ARTIFACT_TYPES = {
    "video/mp4": ".mp4",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "text/plain": ".txt",
    "application/json": ".json",
    "application/x-subrip": ".srt",
}
_MAX_UPLOAD_BYTES = {"portrait": 15 * 1024 * 1024, "audio": 40 * 1024 * 1024, "video": 100 * 1024 * 1024}
_MAX_ARTIFACT_BYTES = 150 * 1024 * 1024
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _data_dir() -> Path:
    return Path(os.getenv("OPENAVATAR_DATA_DIR", "/tmp/openavatar-studio")).expanduser().resolve()


def _db_path() -> Path:
    return Path(os.getenv("OPENAVATAR_DB_PATH") or str(_data_dir() / "openavatar.sqlite3")).expanduser().resolve()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    with _SCHEMA_LOCK:
        conn = sqlite3.connect(key, timeout=20)
        conn.row_factory = sqlite3.Row
        if key not in _SCHEMA_READY:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    commercial_use INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_until TEXT,
                    worker_id TEXT,
                    reservation_seconds INTEGER NOT NULL DEFAULT 0,
                    reservation_date TEXT,
                    actual_gpu_seconds INTEGER NOT NULL DEFAULT 0,
                    artifact_path TEXT,
                    artifact_type TEXT,
                    artifact_name TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_openavatar_jobs_queue
                    ON jobs(provider, status, created_at);
                CREATE TABLE IF NOT EXISTS quota (
                    provider TEXT NOT NULL,
                    quota_date TEXT NOT NULL,
                    used_seconds INTEGER NOT NULL DEFAULT 0,
                    reserved_seconds INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(provider, quota_date)
                );
                CREATE TABLE IF NOT EXISTS quota_windows (
                    provider TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    used_seconds INTEGER NOT NULL DEFAULT 0,
                    reserved_seconds INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(provider, window_start)
                );
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    capabilities TEXT NOT NULL,
                    gpu_name TEXT,
                    vram_mb INTEGER,
                    last_seen TEXT NOT NULL
                );
                """
            )
            conn.commit()
            _SCHEMA_READY.add(key)
        return conn


def _worker_auth(
    token: str | None = Header(default=None, alias="X-OpenAvatar-Worker-Token"),
) -> bool:
    expected = os.getenv("OPENAVATAR_WORKER_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="OpenAvatar worker token is not configured (minimum 32 characters)")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid OpenAvatar worker token")
    return True


def _lightning_enabled() -> bool:
    return (
        os.getenv("OPENAVATAR_LIGHTNING_ENABLED", "false").lower() == "true"
        and os.getenv("OPENAVATAR_LIGHTNING_NO_CARD_CONFIRMED", "false").lower() == "true"
    )


def _provider_enabled(provider: str) -> bool:
    if provider == "local_cpu":
        return True
    if provider == "huggingface_zerogpu":
        return os.getenv("OPENAVATAR_HF_ENABLED", "true").lower() == "true"
    if provider == "kaggle":
        return os.getenv("OPENAVATAR_KAGGLE_ENABLED", "false").lower() == "true"
    if provider == "lightning":
        return _lightning_enabled()
    return False


def _hf_budget() -> int:
    # Hugging Face documents 300 seconds/day for a free account. Keep a safety margin.
    configured = int(os.getenv("OPENAVATAR_HF_DAILY_BUDGET_SECONDS", "270"))
    return max(0, min(configured, 300))


def _hf_job_limit() -> int:
    # Keep individual jobs within the default ZeroGPU function duration unless deliberately changed in code.
    configured = int(os.getenv("OPENAVATAR_HF_MAX_JOB_SECONDS", "60"))
    return max(1, min(configured, 60))


def _quota_snapshot(conn: sqlite3.Connection, provider: str = "huggingface_zerogpu") -> dict[str, Any]:
    now = _now()
    row = conn.execute(
        "SELECT window_start, used_seconds, reserved_seconds FROM quota_windows WHERE provider=? ORDER BY window_start DESC LIMIT 1",
        (provider,),
    ).fetchone()
    active = row is not None and now - datetime.fromisoformat(row["window_start"]) < timedelta(hours=24)
    used = int(row["used_seconds"]) if active else 0
    reserved = int(row["reserved_seconds"]) if active else 0
    window_start = row["window_start"] if active else None
    reset_at = _iso(datetime.fromisoformat(window_start) + timedelta(hours=24)) if window_start else None
    budget = _hf_budget() if provider == "huggingface_zerogpu" else 0
    return {
        "budget_seconds": budget,
        "used_seconds": used,
        "reserved_seconds": reserved,
        "remaining_seconds": max(0, budget - used - reserved),
        "window_started_at": window_start,
        "resets_at": reset_at,
    }


def _settle_reservation(conn: sqlite3.Connection, job: sqlite3.Row, consumed: int) -> None:
    provider = job["provider"]
    reservation = int(job["reservation_seconds"] or 0)
    window_start = job["reservation_date"]
    if provider == "huggingface_zerogpu" and reservation and window_start:
        conn.execute(
            """
            INSERT INTO quota_windows(provider, window_start, used_seconds, reserved_seconds)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(provider, window_start) DO UPDATE SET
                used_seconds=used_seconds + excluded.used_seconds,
                reserved_seconds=MAX(0, reserved_seconds - ?)
            """,
            (provider, window_start, max(0, consumed), reservation),
        )


def _model_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "sadtalker",
            "purpose": "portrait_to_talking_head",
            "repository": "https://github.com/OpenTalker/SadTalker",
            "code_license": "Apache-2.0",
            "weights_and_dependencies": "review_required",
            "commercial_status": "review_required",
            "notes": "Upstream code license does not automatically license every checkpoint, dependency, or dataset.",
        },
        {
            "id": "musetalk",
            "purpose": "audio_driven_lip_sync",
            "repository": "https://github.com/TMElyralab/MuseTalk",
            "code_license": "MIT",
            "weights_and_dependencies": "review_required",
            "commercial_status": "review_required",
            "notes": "Review the exact checkpoint, dependencies, and dataset terms before commercial use.",
        },
        {
            "id": "openvoice_v2",
            "purpose": "voice_cloning_and_tts",
            "repository": "https://github.com/myshell-ai/OpenVoice",
            "code_license": "MIT",
            "weights_and_dependencies": "review_required",
            "commercial_status": "review_required",
            "notes": "Published native languages do not include Urdu; verify model artifacts and language quality separately.",
        },
        {
            "id": "whisper_cpp",
            "purpose": "transcription_and_subtitles",
            "repository": "https://github.com/ggml-org/whisper.cpp",
            "code_license": "MIT",
            "weights_and_dependencies": "review_required",
            "commercial_status": "review_required",
            "notes": "Review the selected Whisper model artifact and any additional codecs.",
        },
        {
            "id": "ffmpeg",
            "purpose": "video_and_audio_assembly",
            "repository": "https://ffmpeg.org/",
            "code_license": "LGPL-2.1-or-later_or_GPL",
            "weights_and_dependencies": "not_applicable",
            "commercial_status": "review_required",
            "notes": "The FFmpeg build configuration determines LGPL/GPL obligations; record build flags.",
        },
        {
            "id": "f5_tts",
            "purpose": "speech_generation",
            "repository": "https://github.com/SWivid/F5-TTS",
            "code_license": "MIT",
            "weights_and_dependencies": "CC-BY-NC",
            "commercial_status": "not_approved",
            "notes": "Do not enable commercial use with the published non-commercial pretrained weights without separate permission.",
        },
    ]


class JobCreate(BaseModel):
    job_type: Literal["talking_head", "lip_sync", "voice", "transcribe", "captions", "render"]
    provider: Literal["auto", "local_cpu", "huggingface_zerogpu", "kaggle", "lightning"] = "auto"
    image_asset_id: str | None = Field(default=None, min_length=8, max_length=80)
    audio_asset_id: str | None = Field(default=None, min_length=8, max_length=80)
    video_asset_id: str | None = Field(default=None, min_length=8, max_length=80)
    consent_confirmed: bool = False
    commercial_use: bool = False
    max_gpu_seconds: int = Field(default=60, ge=1, le=60)
    options: dict[str, Any] = Field(default_factory=dict)
    text: str | None = Field(default=None, min_length=1, max_length=12000)


class WorkerHeartbeat(BaseModel):
    provider: Literal["local_cpu", "huggingface_zerogpu", "kaggle", "lightning"]
    worker_id: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    status: Literal["online", "busy", "draining"] = "online"
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    gpu_name: str | None = Field(default=None, max_length=120)
    vram_mb: int | None = Field(default=None, ge=0, le=1_000_000)


class ClaimRequest(BaseModel):
    provider: Literal["local_cpu", "huggingface_zerogpu", "kaggle", "lightning"]
    worker_id: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    capabilities: list[str] = Field(min_length=1, max_length=20)


class CompleteRequest(BaseModel):
    actual_gpu_seconds: int = Field(default=0, ge=0, le=3600)
    artifact_name: str = Field(default="result", min_length=1, max_length=150)


class FailRequest(BaseModel):
    error: str = Field(min_length=1, max_length=2000)
    consumed_gpu_seconds: int = Field(default=0, ge=0, le=3600)


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "job_type": row["job_type"],
        "engine": row["engine"],
        "provider": row["provider"],
        "status": row["status"],
        "commercial_use": bool(row["commercial_use"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "actual_gpu_seconds": int(row["actual_gpu_seconds"] or 0),
        "error": row["error"],
        "artifact_available": bool(row["artifact_path"]),
        "artifact_content_type": row["artifact_type"],
        "payload": json.loads(row["payload"]),
    }


def _asset_row(conn: sqlite3.Connection, asset_id: str | None) -> sqlite3.Row | None:
    if not asset_id:
        return None
    return conn.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()


def _validate_payload_assets(conn: sqlite3.Connection, request: JobCreate) -> None:
    requirements = {
        "talking_head": {"image_asset_id": "portrait", "audio_asset_id": "audio"},
        "lip_sync": {"video_asset_id": "video", "audio_asset_id": "audio"},
        "voice": {"audio_asset_id": "audio"},
        "transcribe": {"audio_asset_id": "audio"},
        "captions": {"audio_asset_id": "audio"},
        "render": {"video_asset_id": "video", "audio_asset_id": "audio"},
    }[request.job_type]
    for attr, expected_kind in requirements.items():
        asset_id = getattr(request, attr)
        if not asset_id:
            raise HTTPException(status_code=422, detail=f"{attr} is required for {request.job_type}")
        row = _asset_row(conn, asset_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
        if row["kind"] != expected_kind:
            raise HTTPException(status_code=422, detail=f"{attr} must reference an {expected_kind} asset")


def _select_provider(request: JobCreate) -> str:
    if request.provider != "auto":
        selected = request.provider
    elif request.job_type == "talking_head":
        selected = "huggingface_zerogpu"
    elif request.job_type == "lip_sync":
        if _provider_enabled("kaggle"):
            selected = "kaggle"
        elif _provider_enabled("lightning"):
            selected = "lightning"
        else:
            raise HTTPException(status_code=503, detail="No optional no-card GPU worker is enabled for MuseTalk lip-sync jobs")
    elif request.job_type in {"voice", "transcribe", "captions", "render"}:
        selected = "local_cpu"
    else:
        selected = "local_cpu"
    if selected not in _PROVIDER_NAMES or not _provider_enabled(selected):
        raise HTTPException(status_code=503, detail=f"Provider {selected} is disabled or not configured for no-card use")
    if selected == "kaggle" and request.commercial_use:
        raise HTTPException(status_code=403, detail="Kaggle jobs must be personal and non-commercial under the provider's published terms")
    if selected == "lightning" and not _lightning_enabled():
        raise HTTPException(status_code=403, detail="Lightning worker is off; enable only after verifying your account can run without a payment card")
    if request.commercial_use:
        raise HTTPException(status_code=403, detail="Commercial rendering is disabled until the selected model, weights, dependencies, and media licenses are reviewed")
    return selected


@api.get("/status")
def status() -> dict[str, Any]:
    conn = _connect()
    try:
        workers = conn.execute("SELECT worker_id, provider, status, capabilities, gpu_name, vram_mb, last_seen FROM workers ORDER BY provider, worker_id").fetchall()
        now = _now()
        worker_list = []
        for row in workers:
            last_seen = datetime.fromisoformat(row["last_seen"])
            worker_list.append({
                "worker_id": row["worker_id"],
                "provider": row["provider"],
                "status": row["status"] if now - last_seen <= timedelta(minutes=5) else "stale",
                "capabilities": json.loads(row["capabilities"]),
                "gpu_name": row["gpu_name"],
                "vram_mb": row["vram_mb"],
                "last_seen": row["last_seen"],
            })
        return {
            "service": "OpenAvatar Studio",
            "no_card_only": True,
            "paid_provider_fallback": False,
            "workers": worker_list,
            "providers": _providers(),
            "limits": {"huggingface_daily_budget_seconds": _hf_budget(), "huggingface_max_job_seconds": _hf_job_limit()},
            "storage_mode": "ephemeral" if str(_db_path()).startswith("/tmp/") else "configured_path",
        }
    finally:
        conn.close()


def _providers() -> list[dict[str, Any]]:
    return [
        {"id": "huggingface_zerogpu", "enabled": _provider_enabled("huggingface_zerogpu"), "no_card_required": True, "mode": "shared_hosted_inference", "free_limit": "5 GPU minutes/day on eligible free accounts; local safety budget applies", "official_docs": "https://huggingface.co/docs/hub/spaces-zerogpu"},
        {"id": "local_cpu", "enabled": True, "no_card_required": True, "mode": "self_hosted_worker", "free_limit": "Limited by your own PC and electricity"},
        {"id": "kaggle", "enabled": _provider_enabled("kaggle"), "no_card_required": True, "mode": "manual_notebook_worker", "commercial_use": False, "free_limit": "Account quota and hardware vary; personal/non-commercial use only", "official_docs": "https://www.kaggle.com/docs/notebooks"},
        {"id": "lightning", "enabled": _provider_enabled("lightning"), "no_card_required": True, "mode": "manual_cloud_worker", "free_limit": "Introductory credits/hours are conditional and country availability varies", "official_docs": "https://lightning.ai/docs/platform/build/ai-studio"},
    ]


@api.get("/providers")
def providers() -> dict[str, Any]:
    return {"no_card_only": True, "paid_fallback": False, "providers": _providers()}


@api.get("/models")
def models() -> dict[str, Any]:
    return {"models": _model_registry(), "commercial_policy": "Blocked until code, model weights, dependencies, and data licenses are independently reviewed."}


@api.get("/quota", dependencies=[Depends(require_api_key)])
def quota() -> dict[str, Any]:
    conn = _connect()
    try:
        return {"huggingface_zerogpu": _quota_snapshot(conn)}
    finally:
        conn.close()


@api.post("/assets", status_code=201, dependencies=[Depends(require_api_key)])
async def upload_asset(
    request: Request,
    kind: Literal["portrait", "audio", "video"] = Query(...),
    filename: str = Header(default="upload.bin", alias="X-Filename"),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    extension = _CONTENT_TYPES[kind].get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail=f"Unsupported content type for {kind}")
    content_length = int(request.headers.get("content-length", "0") or "0")
    limit = _MAX_UPLOAD_BYTES[kind]
    if content_length > limit:
        raise HTTPException(status_code=413, detail="Asset exceeds the upload size limit")
    body = await request.body()
    if not body or len(body) > limit:
        raise HTTPException(status_code=413 if body else 400, detail="Empty asset or upload exceeds size limit")
    asset_id = uuid.uuid4().hex
    clean_name = Path(filename.replace("\\", "/")).name[:120] or f"asset{extension}"
    asset_path = _data_dir() / "assets" / f"{asset_id}{extension}"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(body)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO assets(asset_id, kind, filename, content_type, size_bytes, path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (asset_id, kind, clean_name, content_type, len(body), str(asset_path), _iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"asset_id": asset_id, "kind": kind, "filename": clean_name, "content_type": content_type, "size_bytes": len(body)}


@api.get("/assets/{asset_id}", dependencies=[Depends(require_api_key)])
def get_asset(asset_id: str):
    conn = _connect()
    try:
        row = _asset_row(conn, asset_id)
        if not row or not Path(row["path"]).is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(row["path"], media_type=row["content_type"], filename=row["filename"])
    finally:
        conn.close()


@api.post("/jobs", status_code=202, dependencies=[Depends(require_api_key)])
def create_job(request: JobCreate) -> dict[str, Any]:
    if request.job_type in {"talking_head", "lip_sync", "voice"} and not request.consent_confirmed:
        raise HTTPException(status_code=400, detail="Confirm that you own or have permission to use the face, video, and voice")
    allowed_options = {"size", "preprocess", "still", "enhancer"}
    if set(request.options) - allowed_options:
        raise HTTPException(status_code=422, detail="Unsupported rendering option")
    if request.options.get("size", 256) not in {256, 512}:
        raise HTTPException(status_code=422, detail="size must be 256 or 512")
    if request.options.get("preprocess", "crop") not in {"crop", "full"}:
        raise HTTPException(status_code=422, detail="preprocess must be crop or full")
    if request.options.get("enhancer") not in {None, "gfpgan"}:
        raise HTTPException(status_code=422, detail="enhancer must be omitted or gfpgan")
    if request.job_type == "voice" and not request.text:
        raise HTTPException(status_code=422, detail="text is required for voice generation")
    engine = _JOB_ENGINES[request.job_type]
    provider = _select_provider(request)
    supported_engines = {
        "local_cpu": {"openvoice_v2", "whisper_cpp", "ffmpeg"},
        "huggingface_zerogpu": {"sadtalker"},
        "kaggle": {"sadtalker", "musetalk", "openvoice_v2", "whisper_cpp", "ffmpeg"},
        "lightning": {"sadtalker", "musetalk", "openvoice_v2", "whisper_cpp", "ffmpeg"},
    }
    if engine not in supported_engines[provider]:
        raise HTTPException(status_code=422, detail=f"Engine {engine} is not supported by provider {provider}")
    if provider == "huggingface_zerogpu" and request.max_gpu_seconds > _hf_job_limit():
        raise HTTPException(status_code=422, detail=f"max_gpu_seconds exceeds the configured ZeroGPU limit ({_hf_job_limit()})")
    conn = _connect()
    try:
        _validate_payload_assets(conn, request)
        job_id = uuid.uuid4().hex
        payload = {
            "image_asset_id": request.image_asset_id,
            "audio_asset_id": request.audio_asset_id,
            "video_asset_id": request.video_asset_id,
            "text": request.text,
            "max_gpu_seconds": request.max_gpu_seconds,
            "options": request.options,
        }
        created = _iso()
        conn.execute(
            """
            INSERT INTO jobs(job_id, job_type, engine, provider, status, payload, commercial_use, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (job_id, request.job_type, engine, provider, json.dumps(payload), int(request.commercial_use), created, created),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _job_dict(row)
    finally:
        conn.close()


@api.get("/jobs", dependencies=[Depends(require_api_key)])
def list_jobs(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"jobs": [_job_dict(row) for row in rows]}
    finally:
        conn.close()


@api.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def get_job(job_id: str) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_dict(row)
    finally:
        conn.close()


@api.get("/jobs/{job_id}/artifact", dependencies=[Depends(require_api_key)])
def get_artifact(job_id: str):
    conn = _connect()
    try:
        row = conn.execute("SELECT artifact_path, artifact_type, artifact_name FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or not row["artifact_path"] or not Path(row["artifact_path"]).is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(row["artifact_path"], media_type=row["artifact_type"], filename=row["artifact_name"] or "result")
    finally:
        conn.close()


@internal.post("/heartbeat", dependencies=[Depends(_worker_auth)])
def worker_heartbeat(request: WorkerHeartbeat) -> dict[str, Any]:
    if not _provider_enabled(request.provider):
        raise HTTPException(status_code=403, detail="This no-card worker provider is disabled")
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO workers(worker_id, provider, status, capabilities, gpu_name, vram_mb, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET provider=excluded.provider, status=excluded.status,
                capabilities=excluded.capabilities, gpu_name=excluded.gpu_name, vram_mb=excluded.vram_mb,
                last_seen=excluded.last_seen
            """,
            (request.worker_id, request.provider, request.status, json.dumps(request.capabilities), request.gpu_name, request.vram_mb, _iso()),
        )
        conn.commit()
        return {"ok": True, "worker_id": request.worker_id, "provider": request.provider}
    finally:
        conn.close()


@internal.post("/jobs/claim", dependencies=[Depends(_worker_auth)])
def claim_job(request: ClaimRequest) -> dict[str, Any]:
    if not _provider_enabled(request.provider):
        raise HTTPException(status_code=403, detail="This no-card worker provider is disabled")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        now = _now()
        now_iso = _iso(now)
        expired = conn.execute(
            "SELECT * FROM jobs WHERE status='running' AND lease_until IS NOT NULL AND lease_until < ?",
            (now_iso,),
        ).fetchall()
        for row in expired:
            # Conservatively count the full reservation as consumed if a worker disappears mid-render.
            _settle_reservation(conn, row, int(row["reservation_seconds"] or 0))
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE job_id=?",
                ("Worker lease expired; create a new job after checking whether the output was produced.", now_iso, row["job_id"]),
            )
        rows = conn.execute(
            "SELECT * FROM jobs WHERE provider=? AND status IN ('queued','quota_wait') AND engine IN (%s) ORDER BY created_at LIMIT 10"
            % ",".join("?" for _ in request.capabilities),
            (request.provider, *request.capabilities),
        ).fetchall()
        if not rows:
            conn.commit()
            return {"job": None}
        selected = None
        for row in rows:
            if request.provider == "huggingface_zerogpu":
                budget = _hf_budget()
                quota_row = conn.execute(
                    "SELECT window_start, used_seconds, reserved_seconds FROM quota_windows WHERE provider=? ORDER BY window_start DESC LIMIT 1",
                    (request.provider,),
                ).fetchone()
                if quota_row is None or now - datetime.fromisoformat(quota_row["window_start"]) >= timedelta(hours=24):
                    window_start = now_iso
                    conn.execute(
                        "INSERT OR IGNORE INTO quota_windows(provider, window_start, used_seconds, reserved_seconds) VALUES (?, ?, 0, 0)",
                        (request.provider, window_start),
                    )
                    used = 0
                    reserved = 0
                else:
                    window_start = quota_row["window_start"]
                    used = int(quota_row["used_seconds"])
                    reserved = int(quota_row["reserved_seconds"])
                required = int(json.loads(row["payload"])["max_gpu_seconds"])
                if used + reserved + required > budget:
                    conn.execute("UPDATE jobs SET status='quota_wait', updated_at=? WHERE job_id=?", (now_iso, row["job_id"]))
                    continue
                conn.execute(
                    "UPDATE quota_windows SET reserved_seconds=reserved_seconds + ? WHERE provider=? AND window_start=?",
                    (required, request.provider, window_start),
                )
                conn.execute(
                    "UPDATE jobs SET reservation_seconds=?, reservation_date=? WHERE job_id=?",
                    (required, window_start, row["job_id"]),
                )
                row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
            selected = row
            break
        if not selected:
            conn.commit()
            return {"job": None, "reason": "daily_quota_exhausted", "quota": _quota_snapshot(conn)}
        lease_until = _iso(now + timedelta(seconds=180))
        conn.execute(
            "UPDATE jobs SET status='running', worker_id=?, lease_until=?, updated_at=? WHERE job_id=?",
            (request.worker_id, lease_until, now_iso, selected["job_id"]),
        )
        conn.execute("UPDATE workers SET status='busy', last_seen=? WHERE worker_id=?", (now_iso, request.worker_id))
        conn.commit()
        payload = json.loads(selected["payload"])
        return {
            "job": {
                "job_id": selected["job_id"],
                "job_type": selected["job_type"],
                "engine": selected["engine"],
                "provider": selected["provider"],
                "commercial_use": bool(selected["commercial_use"]),
                **payload,
            }
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@internal.post("/jobs/{job_id}/heartbeat", dependencies=[Depends(_worker_auth)])
def worker_job_heartbeat(
    job_id: str,
    worker_id: str = Header(alias="X-OpenAvatar-Worker-Id"),
) -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] != "running" or row["worker_id"] != worker_id:
            raise HTTPException(status_code=409, detail="Job is not leased to this worker")
        lease_until = _iso(_now() + timedelta(seconds=180))
        conn.execute(
            "UPDATE jobs SET lease_until=?, updated_at=? WHERE job_id=?",
            (lease_until, _iso(), job_id),
        )
        conn.execute("UPDATE workers SET status='busy', last_seen=? WHERE worker_id=?", (_iso(), worker_id))
        conn.commit()
        return {"ok": True, "job_id": job_id, "lease_until": lease_until}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@internal.get("/assets/{asset_id}", dependencies=[Depends(_worker_auth)])
def worker_get_asset(asset_id: str):
    conn = _connect()
    try:
        row = _asset_row(conn, asset_id)
        if not row or not Path(row["path"]).is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(row["path"], media_type=row["content_type"], filename=row["filename"])
    finally:
        conn.close()


@internal.put("/jobs/{job_id}/artifact", dependencies=[Depends(_worker_auth)])
async def worker_upload_artifact(
    job_id: str,
    request: Request,
    worker_id: str = Header(alias="X-OpenAvatar-Worker-Id"),
    filename: str = Header(default="result", alias="X-Filename"),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    extension = _ARTIFACT_TYPES.get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail="Unsupported output artifact type")
    length = int(request.headers.get("content-length", "0") or "0")
    if length > _MAX_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="Artifact exceeds the upload size limit")
    body = await request.body()
    if not body or len(body) > _MAX_ARTIFACT_BYTES:
        raise HTTPException(status_code=413 if body else 400, detail="Empty artifact or upload exceeds size limit")
    conn = _connect()
    try:
        job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not job or job["status"] != "running" or job["worker_id"] != worker_id:
            raise HTTPException(status_code=409, detail="Job is not leased to this worker")
        artifact_path = _data_dir() / "artifacts" / f"{job_id}{extension}"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(body)
        clean_name = Path(filename.replace("\\", "/")).name[:150] or f"result{extension}"
        conn.execute(
            "UPDATE jobs SET artifact_path=?, artifact_type=?, artifact_name=?, updated_at=? WHERE job_id=?",
            (str(artifact_path), content_type, clean_name, _iso(), job_id),
        )
        conn.commit()
        return {"ok": True, "job_id": job_id, "size_bytes": len(body)}
    finally:
        conn.close()


@internal.post("/jobs/{job_id}/complete", dependencies=[Depends(_worker_auth)])
def worker_complete(
    job_id: str,
    request: CompleteRequest,
    worker_id: str = Header(alias="X-OpenAvatar-Worker-Id"),
) -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] != "running" or row["worker_id"] != worker_id:
            raise HTTPException(status_code=409, detail="Job is not leased to this worker")
        if not row["artifact_path"] or not Path(row["artifact_path"]).is_file():
            raise HTTPException(status_code=400, detail="Upload an artifact before completing the job")
        _settle_reservation(conn, row, min(request.actual_gpu_seconds, int(row["reservation_seconds"] or request.actual_gpu_seconds)))
        conn.execute(
            "UPDATE jobs SET status='completed', actual_gpu_seconds=?, updated_at=?, lease_until=NULL WHERE job_id=?",
            (request.actual_gpu_seconds, _iso(), job_id),
        )
        conn.execute("UPDATE workers SET status='online', last_seen=? WHERE worker_id=?", (_iso(), worker_id))
        conn.commit()
        return {"ok": True, "job_id": job_id, "status": "completed"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@internal.post("/jobs/{job_id}/fail", dependencies=[Depends(_worker_auth)])
def worker_fail(
    job_id: str,
    request: FailRequest,
    worker_id: str = Header(alias="X-OpenAvatar-Worker-Id"),
) -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] != "running" or row["worker_id"] != worker_id:
            raise HTTPException(status_code=409, detail="Job is not leased to this worker")
        _settle_reservation(conn, row, min(request.consumed_gpu_seconds, int(row["reservation_seconds"] or request.consumed_gpu_seconds)))
        conn.execute(
            "UPDATE jobs SET status='failed', error=?, actual_gpu_seconds=?, updated_at=?, lease_until=NULL WHERE job_id=?",
            (request.error, request.consumed_gpu_seconds, _iso(), job_id),
        )
        conn.execute("UPDATE workers SET status='online', last_seen=? WHERE worker_id=?", (_iso(), worker_id))
        conn.commit()
        return {"ok": True, "job_id": job_id, "status": "failed"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()




# ---- OpenAvatar Studio specialist-agent fleet ---------------------------------
_FLEET_PATH = Path(__file__).resolve().parent.parent / "catalog" / "openavatar_agent_fleet.json"


def _agent_fleet() -> dict[str, Any]:
    try:
        data = json.loads(_FLEET_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="OpenAvatar agent fleet manifest is unavailable") from exc
    agents = data.get("agents", [])
    departments = data.get("departments", [])
    if (
        data.get("agent_slots") != len(agents)
        or data.get("department_count") != len(departments)
        or len({item.get("id") for item in agents}) != len(agents)
    ):
        raise HTTPException(status_code=500, detail="OpenAvatar agent fleet manifest failed its integrity check")
    return data


def _agent_worker_no_card_confirmed() -> bool:
    return os.getenv("OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED", "false").lower() == "true"


def _agent_worker_configured() -> bool:
    if not _agent_worker_no_card_confirmed():
        return False
    try:
        worker = next((item for item in service_status() if item.get("id") == "agents"), None)
        return bool(worker and worker.get("configured"))
    except Exception:
        return False


class OpenAvatarAgentRun(BaseModel):
    objective: str = Field(min_length=3, max_length=12000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = True
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class OpenAvatarTeamRun(BaseModel):
    objective: str = Field(min_length=3, max_length=12000)
    agent_ids: list[str] = Field(min_length=1, max_length=120)
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_parallel: int = Field(default=5, ge=1, le=20)
    user_approved: bool = False
    dry_run: bool = True
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


def _agent_by_id(data: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    return next((item for item in data["agents"] if item.get("id") == agent_id), None)


def _agent_worker_payload(
    *,
    task_id: str,
    agent: dict[str, Any],
    objective: str,
    inputs: dict[str, Any],
    user_approved: bool,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "agent_id": agent["id"],
        "agent": agent,
        "objective": objective,
        "inputs": {
            **inputs,
            "studio": "openavatar",
            "studio_policy": {
                "no_card_only": True,
                "no_paid_provider_fallback": True,
                "never_expose_provider_secrets": True,
                "commercial_model_use": "blocked_until_license_review",
                "face_and_voice_processing": "requires_documented_consent",
            },
        },
        "user_approved": user_approved,
        "dry_run": dry_run,
        "execution_mode": "async",
    }


async def _dispatch_openavatar_agent(
    *,
    task_id: str,
    agent: dict[str, Any],
    objective: str,
    inputs: dict[str, Any],
    user_approved: bool,
    dry_run: bool,
) -> dict[str, Any]:
    risk = agent.get("risk_level", "high")
    if not _agent_worker_no_card_confirmed():
        return {
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "status": "blocked_no_card_gate",
            "detail": "Set OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED=true only after verifying the configured agent worker uses free/no-card infrastructure.",
        }
    if risk in {"high", "critical"} and not dry_run and not user_approved:
        return {
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "status": "approval_required",
            "detail": "High-risk or critical agent work requires explicit user approval.",
        }
    payload = _agent_worker_payload(
        task_id=task_id,
        agent=agent,
        objective=objective,
        inputs=inputs,
        user_approved=user_approved,
        dry_run=dry_run,
    )
    try:
        status_code, content_type, body = await post_worker(
            "agents", "/v1/agents/run", payload, timeout_seconds=45
        )
        if "application/json" not in content_type:
            return {
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "status": "worker_error",
                "detail": "Agent worker returned a non-JSON response.",
            }
        try:
            result = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            return {
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "status": "worker_error",
                "detail": "Agent worker returned invalid JSON.",
            }
        return {
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "status": "accepted" if status_code < 400 else "worker_error",
            "worker_status_code": status_code,
            "task_id": task_id,
            "result": result,
        }
    except HTTPException as exc:
        return {
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "status": "worker_unavailable" if exc.status_code in {502, 503, 504} else "rejected",
            "detail": exc.detail,
        }


@api.get("/fleet")
def openavatar_agent_fleet() -> dict[str, Any]:
    data = _agent_fleet()
    return {
        "name": data["name"],
        "version": data["version"],
        "agent_slots": data["agent_slots"],
        "department_count": data["department_count"],
        "workflow_count": len(data.get("workflows", [])),
        "default_max_parallel": data["default_max_parallel"],
        "max_parallel_hard_cap": data["max_parallel_hard_cap"],
        "execution_policy": data["execution_policy"],
        "no_card_policy": data["no_card_policy"],
        "worker": {
            "service": "agents",
            "configured": _agent_worker_configured(),
            "no_card_attested": _agent_worker_no_card_confirmed(),
            "execution_mode": "on_demand_delegated_worker",
        },
        "departments": [
            {"id": item["id"], "name": item["name"], "capacity": item["capacity"], "mission": item["mission"]}
            for item in data["departments"]
        ],
        "note": "These are role templates, not 120 always-running agent processes. Only dispatched tasks execute.",
    }


@api.get("/departments")
def openavatar_agent_departments() -> dict[str, Any]:
    items = _agent_fleet()["departments"]
    return {"total": len(items), "items": items}


@api.get("/agents")
def openavatar_agents(
    q: str | None = None,
    department: str | None = None,
    risk_level: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items = _agent_fleet()["agents"]
    if department:
        items = [item for item in items if item["department_id"] == department]
    if risk_level:
        items = [item for item in items if item["risk_level"] == risk_level.casefold()]
    if q:
        needle = q.casefold()
        items = [item for item in items if needle in json.dumps(item, ensure_ascii=False).casefold()]
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": items[offset:offset + limit],
    }


@api.get("/agents/{agent_id}")
def openavatar_agent_detail(agent_id: str) -> dict[str, Any]:
    agent = _agent_by_id(_agent_fleet(), agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="OpenAvatar agent blueprint not found")
    return {"agent": agent}


@api.get("/workflows")
def openavatar_agent_workflows() -> dict[str, Any]:
    items = _agent_fleet().get("workflows", [])
    return {"total": len(items), "items": items}


@api.post("/plan", dependencies=[Depends(require_api_key)])
async def openavatar_plan(request: OpenAvatarAgentRun) -> dict[str, Any]:
    data = _agent_fleet()
    orchestrator = _agent_by_id(data, "oa-openavatar-chief-orchestrator")
    if not orchestrator:
        raise HTTPException(status_code=500, detail="OpenAvatar chief orchestrator is missing")
    available = [
        {"id": item["id"], "name": item["name"], "department_id": item["department_id"],
         "capabilities": item["capabilities"], "risk_level": item["risk_level"]}
        for item in data["agents"]
    ]
    inputs = {
        **request.inputs,
        "available_openavatar_agents": available,
        "available_workflows": data.get("workflows", []),
        "planning_only": True,
        "do_not_dispatch_subagents": True,
        "do_not_execute_external_actions": True,
        "max_parallel_agents": min(
            int(os.getenv("OPENAVATAR_MAX_PARALLEL_AGENTS", str(data["default_max_parallel"]))),
            int(data["max_parallel_hard_cap"]),
        ),
    }
    task_id = request.idempotency_key or uuid.uuid4().hex
    return await _dispatch_openavatar_agent(
        task_id=task_id,
        agent=orchestrator,
        objective=request.objective,
        inputs=inputs,
        user_approved=False,
        dry_run=True,
    )


@api.post("/agents/{agent_id}/run", dependencies=[Depends(require_api_key)])
async def run_openavatar_agent(agent_id: str, request: OpenAvatarAgentRun) -> dict[str, Any]:
    data = _agent_fleet()
    agent = _agent_by_id(data, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="OpenAvatar agent blueprint not found")
    if agent.get("risk_level") == "critical" and not request.user_approved and not request.dry_run:
        raise HTTPException(status_code=409, detail="Critical-risk agent requires explicit approval or dry_run=true.")
    task_id = request.idempotency_key or uuid.uuid4().hex
    return await _dispatch_openavatar_agent(
        task_id=task_id,
        agent=agent,
        objective=request.objective,
        inputs=request.inputs,
        user_approved=request.user_approved,
        dry_run=request.dry_run,
    )


@api.post("/teams/run", status_code=202, dependencies=[Depends(require_api_key)])
async def run_openavatar_team(request: OpenAvatarTeamRun) -> dict[str, Any]:
    data = _agent_fleet()
    if len(set(request.agent_ids)) != len(request.agent_ids):
        raise HTTPException(status_code=422, detail="agent_ids must not contain duplicates")
    agents = []
    for agent_id in request.agent_ids:
        agent = _agent_by_id(data, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Unknown OpenAvatar agent: {agent_id}")
        agents.append(agent)
    high_risk = [item["id"] for item in agents if item["risk_level"] in {"high", "critical"}]
    if high_risk and not request.user_approved and not request.dry_run:
        raise HTTPException(
            status_code=409,
            detail={"message": "Team contains high-risk or critical roles; explicitly approve or submit as dry_run.", "approval_required_agents": high_risk},
        )
    configured_parallel = int(os.getenv("OPENAVATAR_MAX_PARALLEL_AGENTS", str(data["default_max_parallel"])))
    effective_parallel = max(1, min(request.max_parallel, configured_parallel, int(data["max_parallel_hard_cap"])))
    semaphore = asyncio.Semaphore(effective_parallel)
    base_task_id = request.idempotency_key or uuid.uuid4().hex

    async def run_one(index: int, agent: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await _dispatch_openavatar_agent(
                task_id=f"{base_task_id}-{index + 1}",
                agent=agent,
                objective=request.objective,
                inputs=request.inputs,
                user_approved=request.user_approved,
                dry_run=request.dry_run,
            )

    results = await asyncio.gather(*(run_one(index, agent) for index, agent in enumerate(agents)))
    accepted = sum(1 for item in results if item["status"] == "accepted")
    return {
        "team_task_id": base_task_id,
        "studio": "openavatar",
        "selected_agents": len(agents),
        "accepted": accepted,
        "not_accepted": len(agents) - accepted,
        "max_parallel": effective_parallel,
        "dry_run": request.dry_run,
        "results": results,
        "note": "Accepted means the worker accepted the task; it does not mean the agent has completed its work.",
    }

router.include_router(api)
router.include_router(internal)
