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
from videoengine.avatar import AvatarSpec, evaluate as evaluate_avatar
from videoengine.effects import effect_summary, grade_filter, caption_style as caption_style_for
from videoengine.seo import seo_pack

from .ai_router import chain as ai_chain, complete as ai_complete
from .security import require_api_key
from .vault import get_secret

router = APIRouter(prefix="/v1/command", tags=["command"])

def _resolve_data_dir() -> Path:
    """Pick a writable directory.

    Serverless filesystems are read-only apart from /tmp, so a relative default
    would raise on import before the app could even answer /health.
    """
    explicit = (os.getenv("COMMAND_DATA_DIR") or "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend([Path.cwd() / "data" / "command", Path("/tmp/universal-ai-command")])
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate.resolve()
        except OSError:
            continue
    raise RuntimeError("No writable directory for command output; set COMMAND_DATA_DIR.")


DATA_DIR = _resolve_data_dir()
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

class CommandRequest(BaseModel):
    command: str = Field(min_length=3, max_length=4000)
    render: bool = Field(default=True, description="Start rendering immediately")
    scene_seconds: float | None = Field(default=None, ge=2, le=60)
    fps: int = Field(default=30)
    captions: bool = True
    image_paths: list[str] = Field(default_factory=list, max_length=5000)
    grade: str = Field(default="cinematic", max_length=32)
    caption_style: str = Field(default="bold", max_length=32)
    logo_path: str | None = Field(default=None, max_length=1000)
    seo: bool = True
    avatar: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_config():
    """First usable provider from the router, or None when no key is configured."""
    routes = ai_chain()
    return routes[0] if routes else None


def _sync_model_call(system: str, user: str, *, max_tokens: int = 2000) -> str:
    return ai_complete(system, user, max_tokens=max_tokens)["text"]


def capabilities() -> dict[str, Any]:
    """What the command layer can do right now, and what would upgrade it."""
    try:
        ffmpeg = find_ffmpeg()
        ffmpeg_ready = True
    except FfmpegNotFound:
        ffmpeg, ffmpeg_ready = None, False

    routes = ai_chain()
    model = routes[0] if routes else None
    upgrades: list[str] = []
    if model is None:
        upgrades.append("a model key (GROQ_ / GEMINI_ / MISTRAL_ / OPENROUTER_ / ZAI_ / HF_) for real scripts")
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
            "provider": model.id if model else None,
            "provider_base": model.base if model else None,
            "model": model.model if model else None,
            "fallback_chain": [route.id for route in routes],
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


def _resolve_logo(raw: str | None) -> Path | None:
    if not raw:
        return None
    candidate = Path(raw).resolve()
    if not str(candidate).startswith(str(DATA_DIR)):
        raise HTTPException(status_code=400, detail="logo_path must live under COMMAND_DATA_DIR")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"logo not found: {candidate.name}")
    return candidate


def _render_job(
    job_id: str,
    request: CommandRequest,
    plan_data: dict[str, Any],
    images: list[Path],
    logo: Path | None = None,
) -> None:
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
            caption_style=caption_style_for(request.caption_style),
            grade=grade_filter(request.grade),
            logo=logo,
            logo_position="br",
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
    logo = _resolve_logo(request.logo_path)
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

    avatar_status = evaluate_avatar(AvatarSpec.from_dict(request.avatar))
    seo = None
    if request.seo:
        seo = seo_pack(plan_data, timeline, _sync_model_call if _model_config() else None)

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
        "seo": seo,
        "avatar": avatar_status,
        "effects": effect_summary(request.grade, request.caption_style, logo is not None),
        "capabilities": capabilities(),
    }
    _save(job)

    serverless = bool(os.getenv("VERCEL")) or os.getenv("COMMAND_SYNC_RENDER") == "1"
    max_sync = float(os.getenv("COMMAND_SYNC_MAX_SECONDS", "90"))

    if request.render and serverless:
        # Serverless freezes the instance once a response is sent, so a
        # background thread would silently die. Render inline instead, but only
        # when the video fits inside the function timeout.
        if timeline.duration <= max_sync:
            _render_job(job_id, request, plan_data, images, logo)
            return _load(job_id)
        return _update(
            job_id,
            status="planned",
            stage="too long for this host",
            hint=(
                f"This deployment renders up to {int(max_sync)}s inline. For "
                "{int(timeline.duration)}s, use a long-running host "
                "(deploy/runpod, deploy/cpu-free or render.yaml). The plan and SEO "
                "pack are saved and can be rendered there unchanged."
            ),
        )

    if request.render:
        threading.Thread(
            target=_render_job, args=(job_id, request, plan_data, images, logo),
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
