import hmac
import os
import re
import secrets
from pathlib import Path

from celery import Celery
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
celery_app = Celery("youtube_worker", broker=REDIS_URL, backend=REDIS_URL, include=["youtube_worker.tasks"])
celery_app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json",
                       accept_content=["json"], result_expires=86400, task_acks_late=True,
                       worker_prefetch_multiplier=1)
app = FastAPI(title="Universal AI YouTube Worker", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("YOUTUBE_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="YOUTUBE_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


class PublishRequest(BaseModel):
    task_id: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    channel_connection_id: str = Field(min_length=3, max_length=300)
    video_asset_id: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    privacy_status: str = Field(default="private", pattern=r"^(private|unlisted|public)$")
    publish_at: str | None = Field(default=None, max_length=40)
    user_approved: bool = False
    execution_mode: str = "async"


@app.get("/health")
def health():
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
                "YOUTUBE_CHANNEL_ID", "YOUTUBE_CHANNEL_CONNECTION_ID"]
    return {
        "status": "ok",
        "service": "youtube-worker",
        "oauth_configured": all(os.getenv(k, "").strip() for k in required),
        "asset_root_configured": bool(os.getenv("YOUTUBE_MEDIA_ASSET_ROOT", "/data/assets/videos")),
    }


@app.post("/v1/youtube/publish", status_code=202, dependencies=[Depends(require_worker_key)])
def enqueue_publish(request: PublishRequest):
    if not request.user_approved:
        raise HTTPException(status_code=409, detail="Publishing requires explicit approval")
    configured_id = os.getenv("YOUTUBE_CHANNEL_CONNECTION_ID", "").strip()
    if not configured_id or not hmac.compare_digest(configured_id, request.channel_connection_id):
        raise HTTPException(status_code=403, detail="The requested YouTube channel connection is not configured for this worker")
    if not all(os.getenv(k, "").strip() for k in ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CHANNEL_ID"]):
        raise HTTPException(status_code=503, detail="YouTube OAuth credentials/channel are not configured")
    result = celery_app.send_task("youtube_worker.publish_video", kwargs={"payload": request.model_dump()}, task_id=request.task_id)
    return {"task_id": result.id, "status": "queued", "poll_url": f"/v1/tasks/{result.id}"}


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(require_worker_key)])
def task_status(task_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    result = celery_app.AsyncResult(task_id)
    payload = {"task_id": task_id, "status": result.state.lower()}
    if result.successful():
        value = result.result if isinstance(result.result, dict) else {}
        payload.update({"status": "succeeded", "video_id": value.get("video_id"),
                        "url": value.get("url"), "channel_id": value.get("channel_id")})
    elif result.failed():
        payload.update({"status": "failed", "error": "YouTube publish failed; inspect private worker logs"})
    return payload
