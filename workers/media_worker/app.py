import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from celery import Celery
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

DATA_ROOT = Path(os.getenv("MEDIA_DATA_ROOT", "/data")).resolve()
ASSET_ROOT = DATA_ROOT / "assets"
for directory in (ASSET_ROOT / "videos", ASSET_ROOT / "audio", ASSET_ROOT / "images", ASSET_ROOT / "subtitles", ASSET_ROOT / "other", DATA_ROOT / "workflows"):
    directory.mkdir(parents=True, exist_ok=True)
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/2")
celery_app = Celery("media_worker", broker=REDIS_URL, backend=REDIS_URL, include=["media_worker.tasks"])
celery_app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json",
                       accept_content=["json"], result_expires=86400, task_acks_late=True,
                       worker_prefetch_multiplier=1)
app = FastAPI(title="Universal AI Media Worker", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("MEDIA_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="MEDIA_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


class MediaJob(BaseModel):
    task_type: Literal["image", "video", "audio", "music", "lip_sync", "captions", "render", "transcribe", "thumbnail"]
    inputs: dict[str, Any] = Field(default_factory=dict)
    commercial_use: bool = True
    user_approved: bool = False
    task_id: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


ALLOWED_UPLOADS = {
    "video/mp4": (".mp4", "videos"),
    "video/webm": (".webm", "videos"),
    "video/quicktime": (".mov", "videos"),
    "audio/wav": (".wav", "audio"),
    "audio/x-wav": (".wav", "audio"),
    "audio/mpeg": (".mp3", "audio"),
    "audio/ogg": (".ogg", "audio"),
    "audio/flac": (".flac", "audio"),
    "image/png": (".png", "images"),
    "image/jpeg": (".jpg", "images"),
    "image/webp": (".webp", "images"),
    "text/plain": (".txt", "other"),
    "text/srt": (".srt", "subtitles"),
    "application/x-subrip": (".srt", "subtitles"),
    "application/json": (".json", "other"),
}
MAX_UPLOAD_BYTES = int(os.getenv("MEDIA_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))


@app.get("/health")
def health():
    import shutil
    return {
        "status": "ok",
        "service": "media-worker",
        "ffmpeg_installed": shutil.which("ffmpeg") is not None,
        "comfyui_configured": bool(os.getenv("COMFYUI_BASE_URL", "").strip()),
        "asset_root": str(ASSET_ROOT),
    }


@app.post("/v1/assets/upload", status_code=201, dependencies=[Depends(require_worker_key)])
async def upload_asset(file: UploadFile = File(...)):
    mime = (file.content_type or "").split(";")[0].strip().lower()
    allowed = ALLOWED_UPLOADS.get(mime)
    if not allowed:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    extension, folder = allowed
    asset_id = "asset-" + uuid4().hex
    target_dir = (ASSET_ROOT / folder).resolve()
    if ASSET_ROOT.resolve() not in target_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid storage target")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{asset_id}{extension}"
    written = 0
    try:
        with target_path.open("wb") as dest:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    dest.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"Upload exceeds worker limit of {MAX_UPLOAD_BYTES} bytes")
                dest.write(chunk)
    finally:
        await file.close()
    if written == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")
    meta = {
        "asset_id": asset_id,
        "asset_type": folder,
        "mime_type": mime,
        "stored_filename": target_path.name,
        "relative_path": str(target_path.relative_to(ASSET_ROOT)),
        "size_bytes": written,
        "original_filename": Path(file.filename or "upload").name[:180],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Videos store their metadata sidecar next to the media so the YouTube worker can share the volume.
    metadata_path = target_dir / f"{asset_id}.json"
    metadata_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


@app.get("/v1/assets/{asset_id}", dependencies=[Depends(require_worker_key)])
def get_asset(asset_id: str):
    if not re.fullmatch(r"asset-[a-f0-9]{32}", asset_id):
        raise HTTPException(status_code=400, detail="Invalid asset identifier")
    for folder in ("videos", "audio", "images", "subtitles", "other"):
        candidate = ASSET_ROOT / folder / f"{asset_id}.json"
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Asset not found")


@app.get("/v1/assets/{asset_id}/download", dependencies=[Depends(require_worker_key)])
def download_asset(asset_id: str):
    if not re.fullmatch(r"asset-[a-f0-9]{32}", asset_id):
        raise HTTPException(status_code=400, detail="Invalid asset identifier")
    for folder in ("videos", "audio", "images", "subtitles", "other"):
        meta_path = ASSET_ROOT / folder / f"{asset_id}.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            stored = str(meta.get("stored_filename", ""))
            if Path(stored).name != stored:
                raise HTTPException(status_code=500, detail="Invalid stored asset metadata")
            file_path = (ASSET_ROOT / folder / stored).resolve()
            if ASSET_ROOT.resolve() not in file_path.parents or not file_path.is_file():
                raise HTTPException(status_code=404, detail="Asset file is missing")
            return FileResponse(file_path, media_type=str(meta.get("mime_type", "application/octet-stream")), filename=stored)
    raise HTTPException(status_code=404, detail="Asset not found")


@app.post("/v1/media/jobs", status_code=202, dependencies=[Depends(require_worker_key)])
def enqueue_media_job(request: MediaJob):
    task_id = request.task_id or secrets.token_hex(16)
    result = celery_app.send_task("media_worker.process_media", kwargs={"payload": request.model_dump()}, task_id=task_id)
    return {"task_id": result.id, "status": "queued", "poll_url": f"/v1/tasks/{result.id}"}


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(require_worker_key)])
def task_status(task_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    result = celery_app.AsyncResult(task_id)
    data: dict[str, Any] = {"task_id": task_id, "status": result.state.lower()}
    if result.successful():
        value = result.result if isinstance(result.result, dict) else {}
        data.update({"status": "succeeded", "assets": value.get("assets", []), "result": value.get("result", {})})
    elif result.failed():
        data.update({"status": "failed", "error": "Media job failed; inspect private worker logs"})
    elif result.state == "PROGRESS":
        data["progress"] = result.info if isinstance(result.info, dict) else {}
    return data
