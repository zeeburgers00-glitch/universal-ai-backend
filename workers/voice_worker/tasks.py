import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voice_worker.app import ASSET_ROOT, OUTPUT_ROOT, celery_app


@celery_app.task(bind=True, name="voice_worker.synthesize", acks_late=True)
def synthesize(self, payload: dict[str, Any]) -> dict[str, Any]:
    engine = str(payload.get("engine", "")).lower()
    task_id = str(self.request.id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise ValueError("Invalid task identifier")
    text = str(payload.get("text", ""))
    if not text.strip() or len(text) > 12000:
        raise ValueError("Text must contain 1-12000 characters")

    if engine == "f5-tts":
        return _run_f5(task_id, payload)
    if engine == "melo-tts":
        return _run_melo(task_id, payload)
    raise ValueError(f"Engine {engine!r} is not installed in this worker")


def _resolve_reference(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    asset_id = payload.get("reference_audio_asset_id")
    if not asset_id:
        return None, None
    if not re.fullmatch(r"voice-ref-[a-f0-9]{32}", str(asset_id)):
        raise ValueError("Invalid reference audio asset ID")
    meta_path = ASSET_ROOT / f"{asset_id}.json"
    if not meta_path.is_file():
        raise ValueError("Reference audio asset is missing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected = str(payload.get("speaker_consent_record_id") or "")
    if not meta.get("speaker_consent_confirmed") or not expected or meta.get("consent_record_id") != expected:
        raise ValueError("Voice reference does not have a matching consent record")
    candidates = list(ASSET_ROOT.glob(f"{asset_id}.*"))
    candidates = [x for x in candidates if x.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"}]
    if len(candidates) != 1:
        raise ValueError("Reference audio file is missing or ambiguous")
    return str(candidates[0]), str(payload.get("reference_transcript") or "")


def _run_f5(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    import shutil
    command = shutil.which("f5-tts_infer-cli")
    if not command:
        raise RuntimeError("f5-tts_infer-cli is not installed")
    if payload.get("commercial_use") and os.getenv("F5_TTS_MODEL_LICENSE_CLASS", "").lower() != "commercial_approved":
        raise PermissionError("Commercial F5-TTS use is disabled until a compatible model checkpoint is configured and approved")

    output_path = OUTPUT_ROOT / f"{task_id}.wav"
    output_dir = tempfile.mkdtemp(prefix=f"f5-{task_id}-", dir=str(OUTPUT_ROOT))
    args = [
        command,
        "--model", os.getenv("F5_TTS_MODEL", "F5TTS_v1_Base"),
        "--gen_text", str(payload["text"]),
        "--output_dir", output_dir,
        "--output_file", output_path.name,
        "--device", os.getenv("F5_TTS_DEVICE", "cuda"),
    ]
    ref_audio, ref_text = _resolve_reference(payload)
    if ref_audio:
        args.extend(["--ref_audio", ref_audio])
        if ref_text:
            args.extend(["--ref_text", ref_text])
    if payload.get("output_format", "wav") != "wav":
        # The upstream inference CLI produces WAV; conversion is done by a separate ffmpeg step.
        raise ValueError("This worker build currently returns WAV; request output_format='wav'")
    max_seconds = int(os.getenv("F5_TTS_JOB_TIMEOUT_SECONDS", "240"))
    completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=max_seconds)
    if completed.returncode != 0:
        # Do not put raw logs into the job result; keep them in private worker logs.
        raise RuntimeError(f"F5-TTS inference failed with exit code {completed.returncode}")
    generated = Path(output_dir) / output_path.name
    if not generated.is_file():
        # Depending on installed CLI configuration, output_dir/output_file is the expected path.
        raise RuntimeError("F5-TTS completed without creating the expected WAV output")
    generated.replace(output_path)
    asset_id = "audio-" + __import__("uuid").uuid4().hex
    final_path = OUTPUT_ROOT / f"{asset_id}.wav"
    output_path.replace(final_path)
    metadata = {
        "asset_id": asset_id,
        "stored_filename": final_path.name,
        "mime_type": "audio/wav",
        "engine": "f5-tts",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "commercial_use": bool(payload.get("commercial_use")),
    }
    (OUTPUT_ROOT / f"{asset_id}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {"asset_id": asset_id, "mime_type": "audio/wav", "engine": "f5-tts"}


def _run_melo(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("reference_audio_asset_id"):
        raise ValueError("MeloTTS is a preset-speaker TTS engine in this worker; use a compatible voice-cloning engine for reference-audio cloning")
    try:
        from melo.api import TTS
    except ImportError as exc:
        raise RuntimeError("MeloTTS is not installed in this worker") from exc
    language = str(payload.get("language") or "EN")
    device = os.getenv("MELOTTS_DEVICE", "cuda")
    tts = TTS(language=language, device=device)
    speaker_ids = getattr(getattr(tts, "hps", None), "data", None)
    speaker_map = getattr(speaker_ids, "spk2id", {}) if speaker_ids else {}
    if not speaker_map:
        raise RuntimeError("MeloTTS did not expose any installed speaker presets")
    requested_speaker = str(payload.get("voice_profile_id") or "")
    speaker_id = speaker_map.get(requested_speaker, next(iter(speaker_map.values())))
    task_output = OUTPUT_ROOT / f"{task_id}.wav"
    tts.tts_to_file(str(payload["text"]), speaker_id, str(task_output), speed=1.0)
    if not task_output.is_file():
        raise RuntimeError("MeloTTS completed without creating a WAV file")
    asset_id = "audio-" + __import__("uuid").uuid4().hex
    final_path = OUTPUT_ROOT / f"{asset_id}.wav"
    task_output.replace(final_path)
    metadata = {
        "asset_id": asset_id,
        "stored_filename": final_path.name,
        "mime_type": "audio/wav",
        "engine": "melo-tts",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "commercial_use": bool(payload.get("commercial_use")),
    }
    (OUTPUT_ROOT / f"{asset_id}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {"asset_id": asset_id, "mime_type": "audio/wav", "engine": "melo-tts"}
