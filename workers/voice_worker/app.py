import base64
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from celery import Celery
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

DATA_ROOT = Path(os.getenv("VOICE_DATA_ROOT", "/data")).resolve()
ASSET_ROOT = DATA_ROOT / "assets"
OUTPUT_ROOT = DATA_ROOT / "generated"
PROFILE_ROOT = DATA_ROOT / "profiles"
for directory in (ASSET_ROOT, OUTPUT_ROOT, PROFILE_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery("voice_worker", broker=REDIS_URL, backend=REDIS_URL, include=["voice_worker.tasks"])
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

app = FastAPI(title="Universal AI Voice Worker", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("VOICE_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="VOICE_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


class VoiceAssetUpload(BaseModel):
    asset_type: Literal["voice_reference"] = "voice_reference"
    filename: str = Field(min_length=1, max_length=180)
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/mp3", "audio/ogg", "audio/flac", "audio/x-wav"]
    content_base64: str = Field(min_length=40, max_length=4_000_000)
    speaker_consent_confirmed: bool = False
    consent_record_id: str = Field(min_length=8, max_length=300)
    consent_scope: str = Field(default="voice_cloning_and_tts", min_length=3, max_length=160)


class VoiceJob(BaseModel):
    task_id: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    engine: str = Field(min_length=2, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    text: str = Field(min_length=1, max_length=12000)
    language: str | None = Field(default=None, max_length=40)
    voice_profile_id: str | None = Field(default=None, max_length=200)
    reference_audio_asset_id: str | None = Field(default=None, max_length=100)
    reference_transcript: str | None = Field(default=None, max_length=5000)
    speaker_consent_confirmed: bool = False
    speaker_consent_record_id: str | None = Field(default=None, max_length=300)
    commercial_use: bool = True
    output_format: Literal["wav", "mp3", "ogg", "flac"] = "wav"


class CloneRequest(BaseModel):
    engine: str = Field(min_length=2, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    reference_audio_asset_id: str = Field(min_length=10, max_length=100)
    reference_transcript: str | None = Field(default=None, max_length=5000)
    speaker_consent_confirmed: bool = False
    speaker_consent_record_id: str = Field(min_length=8, max_length=300)
    commercial_use: bool = True
    voice_profile_name: str = Field(min_length=2, max_length=100)


def _check_consent(asset_id: str, consent_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"voice-ref-[a-f0-9]{32}", asset_id):
        raise HTTPException(status_code=400, detail="Invalid voice asset identifier")
    meta_path = ASSET_ROOT / f"{asset_id}.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="Voice reference asset not found")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="Voice asset metadata is unavailable")
    if not hmac.compare_digest(str(meta.get("consent_record_id", "")), consent_id):
        raise HTTPException(status_code=403, detail="Consent record does not match this voice asset")
    if not meta.get("speaker_consent_confirmed") or meta.get("asset_type") != "voice_reference":
        raise HTTPException(status_code=403, detail="Voice reference asset has no valid consent record")
    return meta


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "voice-worker",
        "queue_configured": bool(REDIS_URL),
        "asset_store": "local_persistent_volume",
        "engines": {
            "f5-tts": {"installed": _command_available("f5-tts_infer-cli"), "mode": "gpu_cli"},
            "melo-tts": {"installed": _module_available("melo"), "mode": "python_api"},
        },
    }


def _command_available(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


def _module_available(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


@app.get("/v1/voice/providers", dependencies=[Depends(require_worker_key)])
def voice_engines():
    return {
        "engines": [
            {
                "id": "f5-tts",
                "installed": _command_available("f5-tts_infer-cli"),
                "supports_reference_audio": True,
                "default_pretrained_model_class": "noncommercial_unless_separately_licensed",
            },
            {
                "id": "melo-tts",
                "installed": _module_available("melo"),
                "supports_reference_audio": False,
                "notes": "Uses a built-in speaker preset; review the exact model/voice assets before commercial use.",
            },
        ],
        "other_engines": "Catalog entries for OpenVoice, CosyVoice, GPT-SoVITS, XTTS, RVC and hosted APIs require their engine adapter/model or provider credentials to be configured.",
    }


@app.post("/v1/voice/assets", status_code=201, dependencies=[Depends(require_worker_key)])
def upload_voice_reference(request: VoiceAssetUpload):
    if not request.speaker_consent_confirmed:
        raise HTTPException(status_code=400, detail="Explicit speaker consent is required before storing a voice reference")
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except (ValueError, base64.binascii.Error):
        raise HTTPException(status_code=400, detail="content_base64 must be valid Base64")
    if not content or len(content) > 3_000_000:
        raise HTTPException(status_code=413, detail="Voice reference must be at most 3 MB after Base64 decoding")
    extension_by_mime = {
        "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3", "audio/ogg": ".ogg", "audio/flac": ".flac",
    }
    extension = extension_by_mime[request.mime_type]
    asset_id = "voice-ref-" + uuid4().hex
    asset_path = ASSET_ROOT / f"{asset_id}{extension}"
    # Avoid arbitrary file names/paths from the caller; server creates the path.
    asset_path.write_bytes(content)
    metadata = {
        "asset_id": asset_id,
        "asset_type": request.asset_type,
        "mime_type": request.mime_type,
        "filename_original": Path(request.filename).name[:180],
        "size_bytes": len(content),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "speaker_consent_confirmed": True,
        "consent_record_id": request.consent_record_id,
        "consent_scope": request.consent_scope,
    }
    (ASSET_ROOT / f"{asset_id}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {"asset_id": asset_id, "consent_record_id": request.consent_record_id, "metadata": metadata}


@app.post("/v1/voice/clone", status_code=201, dependencies=[Depends(require_worker_key)])
def register_voice_profile(request: CloneRequest):
    if not request.speaker_consent_confirmed:
        raise HTTPException(status_code=400, detail="Voice cloning requires explicit speaker consent")
    _check_consent(request.reference_audio_asset_id, request.speaker_consent_record_id)
    if request.engine == "f5-tts" and request.commercial_use and os.getenv("F5_TTS_MODEL_LICENSE_CLASS", "").lower() != "commercial_approved":
        raise HTTPException(status_code=403, detail="Configure an F5-TTS checkpoint with approved commercial rights before commercial use")
    profile_id = "voice-profile-" + uuid4().hex
    profile = {
        "voice_profile_id": profile_id,
        "engine": request.engine,
        "reference_audio_asset_id": request.reference_audio_asset_id,
        "reference_transcript": request.reference_transcript,
        "speaker_consent_record_id": request.speaker_consent_record_id,
        "speaker_consent_confirmed": True,
        "commercial_use": request.commercial_use,
        "profile_name": request.voice_profile_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_zero_shot_inference",
        "note": "This stores a consented reference profile; it does not fine-tune or train new model weights.",
    }
    (PROFILE_ROOT / f"{profile_id}.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


@app.post("/v1/voice/tts", status_code=202, dependencies=[Depends(require_worker_key)])
def submit_tts_job(request: VoiceJob):
    engine = request.engine.lower()
    known = {"f5-tts", "melo-tts"}
    if engine not in known:
        raise HTTPException(status_code=501, detail=f"Voice engine {engine!r} is in the catalog but is not installed in this worker build")
    if request.reference_audio_asset_id:
        if not (request.speaker_consent_confirmed and request.speaker_consent_record_id):
            raise HTTPException(status_code=400, detail="Using a reference voice requires a consent record")
        _check_consent(request.reference_audio_asset_id, request.speaker_consent_record_id)
    if request.voice_profile_id:
        if not (request.speaker_consent_confirmed and request.speaker_consent_record_id):
            raise HTTPException(status_code=400, detail="Using a saved voice profile requires an explicit consent record")
        if not re.fullmatch(r"voice-profile-[a-f0-9]{32}", request.voice_profile_id):
            raise HTTPException(status_code=400, detail="Invalid voice profile ID")
        profile_path = PROFILE_ROOT / f"{request.voice_profile_id}.json"
        if not profile_path.is_file():
            raise HTTPException(status_code=404, detail="Voice profile was not found")
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if not profile.get("speaker_consent_confirmed") or not hmac.compare_digest(
            str(profile.get("speaker_consent_record_id", "")), request.speaker_consent_record_id
        ):
            raise HTTPException(status_code=403, detail="Voice profile consent record does not match")
    if engine == "f5-tts" and request.commercial_use and os.getenv("F5_TTS_MODEL_LICENSE_CLASS", "").lower() != "commercial_approved":
        raise HTTPException(status_code=403, detail="F5-TTS pretrained weights may be non-commercial; configure a compatible commercial checkpoint first")
    task_id = request.task_id or secrets.token_hex(16)
    async_result = celery_app.send_task("voice_worker.synthesize", kwargs={"payload": request.model_dump()}, task_id=task_id)
    return {"task_id": async_result.id, "status": "queued", "engine": engine, "poll_url": f"/v1/tasks/{async_result.id}"}


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(require_worker_key)])
def voice_task_status(task_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    result = celery_app.AsyncResult(task_id)
    data: dict[str, Any] = {"task_id": task_id, "status": result.state.lower()}
    if result.successful():
        value = result.result if isinstance(result.result, dict) else {}
        data.update({"status": "succeeded", "asset_id": value.get("asset_id"), "mime_type": value.get("mime_type", "audio/wav")})
    elif result.failed():
        # Never return raw task exceptions or tracebacks to clients.
        data.update({"status": "failed", "error": "Voice job failed; inspect private worker logs"})
    elif result.state == "PROGRESS":
        data["progress"] = result.info if isinstance(result.info, dict) else {}
    return data


@app.get("/v1/voice/results/{task_id}", dependencies=[Depends(require_worker_key)])
def get_voice_result(task_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    result = celery_app.AsyncResult(task_id)
    if not result.successful():
        raise HTTPException(status_code=409, detail=f"Audio is not ready (task state: {result.state.lower()})")
    value = result.result if isinstance(result.result, dict) else {}
    asset_id = value.get("asset_id")
    if not isinstance(asset_id, str) or not re.fullmatch(r"audio-[a-f0-9]{32}", asset_id):
        raise HTTPException(status_code=500, detail="Worker result has no valid audio asset id")
    meta_path = OUTPUT_ROOT / f"{asset_id}.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="Audio result asset not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    path = (OUTPUT_ROOT / str(meta.get("stored_filename", ""))).resolve()
    if OUTPUT_ROOT.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file is unavailable")
    return FileResponse(path, media_type=str(meta.get("mime_type", "audio/wav")), filename=path.name)
