"""One command in, a finished video out.

    POST /v1/command {"command": "make a 12 minute video about tea farming"}

The command is planned (model-assisted when a key is configured, built-in parser
otherwise), converted into a scene timeline, and rendered to a single MP4 by the
videoengine package. Because rendering is scene-by-scene, length is limited only
by disk and time -- a three-hour video is just a longer timeline.

Nothing here fabricates media: if no image provider, stock key or voice worker is
configured, the render still completes using colour cards and burned captions,
and the response says exactly which env var would improve it.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from videoengine import build_timeline, plan as plan_command
from videoengine.assembly import FfmpegNotFound, find_ffmpeg, probe, render_timeline

from .security import require_api_key
from .vault import get_secret

router = APIRouter(prefix="/v1/command", tags=["command"])

DATA_DIR = Path(os.getenv("COMMAND_DATA_DIR", "data/command")).resolve()
JOB_DIR = DATA_DIR / "jobs"
OUTPUT_DIR = DATA_DIR / "output"
for _directory in (JOB_DIR, OUTPUT_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 200

# Deterministic card colours so the same scene always renders the same colour.
_PALETTE = [
    (0x10, 0x18, 0x20), (0x1B, 0x2A, 0x34), (0x23, 0x1A, 0x2E), (0x14, 0x2B, 0x28),
    (0x2B, 0x22, 0x14), (0x1E, 0x1E, 0x2B), (0x2A, 0x14, 0x18), (0x17, 0x25, 0x38),
]

_MODEL_CANDIDATES = (
    ("AI_BASE_URL", "AI_API_KEY", "AI_DEFAULT_MODEL", None),
    ("GROQ_BASE_URL", "GROQ_API_KEY", "GROQ_DEFAULT_MODEL", "https://api.groq.com/openai/v1"),
    ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_DEFAULT_MODEL", "https://api.openai.com/v1"),
)


class CommandRequest(BaseModel):
    command: str = Field(min_length=3, max_length=4000)
    render: bool = Field(default=True, description="Start rendering immediately")
    scene_seconds: float | None = Field(default=None, ge=2, le=60)
    fps: int = Field(default=30)
    captions: bool = Field(default=True)
    image_paths: list[str] = Field(default_factory=list, max_length=5000)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- keys
def _model_config() -> tuple[str, str, str] | None:
    for base_env, key_env, model_env, default_base in _MODEL_CANDIDATES:
        key = (get_secret(key_env) or "").strip()
        model = (os.getenv(model_env) or "").strip()
        base = (os.getenv(base_env) or "").strip() or (default_base or "")
        if key and model and base.startswith("https://"):
            return base.rstrip("/"), key, model
    return None


def _sync_model_call(system: str, user: str, *, max_tokens: int = 2000) -> str:
    config = _model_config()
    if config is None:
        raise RuntimeError("no model provider configured")
    base, key, model = config
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    with httpx.Client(timeout=httpx.Timeout(90, connect=10), follow_redirects=False) as client:
        response = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "temperature": 0.4,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("model provider returned no choices")
    return str((choices[0].get("message") or {}).get("content") or "").strip()


def capabilities() -> dict[str, Any]:
    """What the command layer can do right now, and what would upgrade it."""
    try:
        ffmpeg = find_ffmpeg()
        ffmpeg_ready = True
    except FfmpegNotFound:
        ffmpeg, ffmpeg_ready = None, False

    model = _model_config()
    upgrades: list[str] = []
    if model is None:
        upgrades.append("AI_API_KEY + AI_DEFAULT_MODEL (or GROQ_/OPENAI_ pair) for real scripts")
    if not (os.getenv("PEXELS_API_KEY") or "").strip():
        upgrades.append("PEXELS_API_KEY for real stock footage instead of colour cards")
    if not (os.getenv("VOICE_WORKER_URL") or "").strip():
        upgrades.append("VOICE_WORKER_URL for narration audio")
    if not (os.getenv("MEDIA_WORKER_URL") or "").strip():
        upgrades.append("MEDIA_WORKER_URL for AI-generated visuals and post-processing")

    return {
        "renderer": {"ready": ffmpeg_ready, "ffmpeg": ffmpeg},
        "script_writer": {
            "ready": model is not None,
            "provider_base": model[0] if model else None,
            "model": model[2] if model else None,
        },
        "works_without_keys": True,
        "fallbacks": {
            "script": "built-in planner (templated narration)",
            "visuals": "colour cards + burned captions",
        },
        "upgrades": upgrades,
        "limits": {
            "max_duration_seconds": int(os.getenv("COMMAND_MAX_DURATION_SECONDS", str(12 * 3600))),
            "note": "Length is bounded by disk and patience, not by the engine.",
        },
    }


# --------------------------------------------------------------------------- store
def _save(job: dict[str, Any]) -> None:
    with _LOCK:
        _JOBS[job["job_id"]] = job
        if len(_JOBS) > _MAX_JOBS:
            oldest = min(_JOBS.values(), key=lambda item: item["created_at"])
            if oldest["job_id"] != job["job_id"]:
                _JOBS.pop(oldest["job_id"], None)
    (JOB_DIR / f"{job['job_id']}.json").write_text(json.dumps(job, indent=2), encoding="utf-8")


def _load(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job:
        return job
    path = JOB_DIR / f"{job_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Command job not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _update(job_id: str, **fields: Any) -> dict[str, Any]:
    job = _load(job_id)
    job.update(fields)
    job["updated_at"] = _now()
    _save(job)
    return job


# --------------------------------------------------------------------------- render
def _card_for(index: int, width: int, height: int, ffmpeg: str) -> Path:
    """A stable gradient-free colour card used when no imagery is configured."""
    red, green, blue = _PALETTE[index % len(_PALETTE)]
    path = DATA_DIR / "cards" / f"card_{index % len(_PALETTE):02d}_{width}x{height}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        import subprocess

        subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi",
             "-i", f"color=c=0x{red:02x}{green:02x}{blue:02x}:s={width}x{height}:d=1",
             "-frames:v", "1", str(path)],
            capture_output=True, check=True, timeout=120,
        )
    return path


def _resolve_images(request: CommandRequest) -> list[Path]:
    """Only files inside the command data directory may be referenced."""
    allowed: list[Path] = []
    for raw in request.image_paths:
        candidate = Path(raw).resolve()
        if not str(candidate).startswith(str(DATA_DIR)):
            raise HTTPException(status_code=400, detail="image_paths must live under COMMAND_DATA_DIR")
        if not candidate.is_file():
            raise HTTPException(status_code=400, detail=f"image not found: {candidate.name}")
        allowed.append(candidate)
    return allowed


def _render_job(job_id: str, request: CommandRequest, plan_data: dict[str, Any], images: list[Path]) -> None:
    try:
        timeline = build_timeline(
            title=plan_data["title"],
            duration_seconds=plan_data["duration_seconds"],
            aspect_ratio=plan_data["aspect_ratio"],
            scene_seconds=request.scene_seconds or plan_data["scene_seconds"],
            beats=plan_data["beats"],
            visual_prompts=plan_data["visual_prompts"],
            fps=request.fps,
            metadata={"source": plan_data["source"], "language": plan_data["language"]},
        )
        _update(job_id, status="rendering", timeline=timeline.to_dict(), started_at=_now())

        binary = find_ffmpeg()
        cards: dict[int, Path] = {}

        def assets(scene):
            if images:
                return {"image": images[scene.index % len(images)], "ken_burns": True}
            if scene.index not in cards:
                cards[scene.index] = _card_for(scene.index, timeline.width, timeline.height, binary)
            return {"image": cards[scene.index], "ken_burns": True}

        def progress(fraction: float, message: str) -> None:
            _update(job_id, progress=round(fraction * 100, 1), stage=message)

        output = OUTPUT_DIR / f"{job_id}.mp4"
        info = render_timeline(
            timeline, assets, output,
            work_dir=DATA_DIR / "work" / job_id,
            ffmpeg=binary,
            captions=request.captions,
            progress=progress,
        )
        _update(
            job_id, status="completed", progress=100.0, stage="done", finished_at=_now(),
            output={"path": str(output), "url": f"/v1/command/{job_id}/video",
                    "duration": info["duration"], "size_bytes": info["size_bytes"],
                    "resolution": f"{timeline.width}x{timeline.height}"},
        )
    except Exception as exc:  # surface the real reason instead of a generic 500
        _update(job_id, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}",
                finished_at=_now())


# --------------------------------------------------------------------------- routes
@router.get("/capabilities")
def command_capabilities(_: bool = Depends(require_api_key)) -> dict[str, Any]:
    return capabilities()


@router.get("")
def list_jobs(limit: int = 20, _: bool = Depends(require_api_key)) -> dict[str, Any]:
    jobs = sorted(_JOBS.values(), key=lambda item: item["created_at"], reverse=True)
    return {"count": len(jobs), "jobs": jobs[: max(1, min(limit, 100))]}


@router.post("", status_code=202)
def create_command(request: CommandRequest, _: bool = Depends(require_api_key)) -> dict[str, Any]:
    try:
        plan_data = plan_command(request.command, _sync_model_call if _model_config() else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    images = _resolve_images(request)
    try:
        timeline = build_timeline(
            title=plan_data["title"],
            duration_seconds=plan_data["duration_seconds"],
            aspect_ratio=plan_data["aspect_ratio"],
            scene_seconds=request.scene_seconds or plan_data["scene_seconds"],
            beats=plan_data["beats"],
            visual_prompts=plan_data["visual_prompts"],
            fps=request.fps,
            metadata={"source": plan_data["source"], "language": plan_data["language"]},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = f"cmd-{uuid.uuid4().hex[:16]}"
    job = {
        "job_id": job_id,
        "command": request.command,
        "status": "planned",
        "progress": 0.0,
        "stage": "planned",
        "created_at": _now(),
        "updated_at": _now(),
        "plan": plan_data,
        "timeline": timeline.to_dict(),
        "capabilities": capabilities(),
    }
    _save(job)

    if request.render:
        threading.Thread(
            target=_render_job, args=(job_id, request, plan_data, images),
            name=f"render-{job_id}", daemon=True,
        ).start()
        job = _update(job_id, status="queued", stage="queued for rendering")
    return job


@router.get("/{job_id}")
def get_command(job_id: str, _: bool = Depends(require_api_key)) -> dict[str, Any]:
    return _load(job_id)


@router.get("/{job_id}/timeline")
def get_timeline(job_id: str, _: bool = Depends(require_api_key)) -> dict[str, Any]:
    job = _load(job_id)
    return {"job_id": job_id, "timeline": job["timeline"]}


@router.get("/{job_id}/video")
def get_video(
    job_id: str,
    key: str | None = None,
    x_api_key: str | None = Header(default=None),
):
    """Stream the render.

    A browser <video> tag cannot set headers, so this one route also accepts the
    key as `?key=` for in-page playback. Everything else requires the header.
    """
    import secrets as _secrets

    from fastapi.responses import FileResponse

    expected = os.getenv("BACKEND_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Backend API key is not configured on the server")
    supplied = (x_api_key or key or "").strip()
    if not supplied or not _secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    job = _load(job_id)
    path = Path((job.get("output") or {}).get("path", ""))
    if job.get("status") != "completed" or not path.is_file():
        raise HTTPException(status_code=409, detail=f"Video is not ready (status: {job.get('status')})")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")
