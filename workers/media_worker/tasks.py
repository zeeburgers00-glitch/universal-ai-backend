import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from media_worker.app import ASSET_ROOT, DATA_ROOT, celery_app

WORKFLOW_ROOT = DATA_ROOT / "workflows"
OUTPUT_ROOT = ASSET_ROOT / "videos"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def _asset(asset_id: str) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"asset-[a-f0-9]{32}", asset_id):
        raise ValueError("Invalid asset ID")
    for folder in ("videos", "audio", "images", "subtitles", "other"):
        meta_path = ASSET_ROOT / folder / f"{asset_id}.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = str(meta.get("stored_filename", ""))
            if Path(name).name != name:
                raise ValueError("Invalid asset metadata")
            path = (ASSET_ROOT / folder / name).resolve()
            if ASSET_ROOT.resolve() not in path.parents or not path.is_file():
                raise FileNotFoundError("Asset file is not present")
            return path, meta
    raise FileNotFoundError("Asset was not found")


def _store_output(path: Path, asset_id: str, mime: str) -> dict[str, Any]:
    meta = {
        "asset_id": asset_id,
        "asset_type": "videos" if mime.startswith("video/") else ("audio" if mime.startswith("audio/") else "images"),
        "mime_type": mime,
        "stored_filename": path.name,
        "relative_path": str(path.relative_to(ASSET_ROOT)),
        "size_bytes": path.stat().st_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generated_by_worker": "media_worker",
    }
    folder = path.parent
    (folder / f"{asset_id}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _run_ffmpeg(args: list[str], timeout: int = 900) -> None:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("FFmpeg is not installed in this worker image")
    completed = subprocess.run([executable, *args], capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        # Do not return raw command output or local paths to the public API.
        raise RuntimeError(f"FFmpeg failed with exit code {completed.returncode}")


@celery_app.task(bind=True, name="media_worker.process_media", acks_late=True)
def process_media(self, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(self.request.id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise ValueError("Invalid task ID")
    task_type = str(payload.get("task_type", ""))
    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")

    if task_type in {"render", "thumbnail", "audio", "captions"}:
        return _run_ffmpeg_job(task_id, task_type, inputs)
    if task_type in {"image", "video", "music", "lip_sync"}:
        return _run_comfyui_job(task_id, task_type, inputs, bool(payload.get("commercial_use", True)))
    if task_type == "transcribe":
        return _run_asr_job(task_id, inputs)
    raise ValueError(f"Unsupported media task type {task_type!r}")


def _run_ffmpeg_job(task_id: str, task_type: str, inputs: dict[str, Any]) -> dict[str, Any]:
    source_id = str(inputs.get("source_asset_id", ""))
    src, src_meta = _asset(source_id)
    asset_id = "asset-" + uuid4().hex
    if task_type == "thumbnail":
        out_dir = ASSET_ROOT / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{asset_id}.jpg"
        timestamp = inputs.get("timestamp_seconds", 1)
        if not isinstance(timestamp, (int, float)) or timestamp < 0 or timestamp > 86400:
            raise ValueError("timestamp_seconds must be between 0 and 86400")
        _run_ffmpeg(["-y", "-ss", str(float(timestamp)), "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)], timeout=180)
        meta = _store_output(out, asset_id, "image/jpeg")
        return {"assets": [meta], "result": {"operation": "thumbnail"}}

    if task_type == "audio":
        operation = str(inputs.get("operation", "extract"))
        out_dir = ASSET_ROOT / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{asset_id}.mp3"
        if operation == "extract":
            _run_ffmpeg(["-y", "-i", str(src), "-vn", "-codec:a", "libmp3lame", "-b:a", "192k", str(out)])
        elif operation == "normalize":
            _run_ffmpeg(["-y", "-i", str(src), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-codec:a", "libmp3lame", "-b:a", "192k", str(out)])
        else:
            raise ValueError("audio operation must be extract or normalize")
        meta = _store_output(out, asset_id, "audio/mpeg")
        return {"assets": [meta], "result": {"operation": operation}}

    if task_type == "captions":
        subtitle_id = str(inputs.get("subtitle_asset_id", ""))
        subtitle_path, subtitle_meta = _asset(subtitle_id)
        if not subtitle_path.suffix.lower() == ".srt":
            raise ValueError("subtitle_asset_id must refer to an SRT asset")
        out_dir = ASSET_ROOT / "videos"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{asset_id}.mp4"
        # Uploaded assets receive generated names with no spaces; escape literal path syntax.
        vf = "subtitles=" + str(subtitle_path).replace("\\", "\\\\").replace(":", "\\:")
        _run_ffmpeg(["-y", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                     "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
        meta = _store_output(out, asset_id, "video/mp4")
        return {"assets": [meta], "result": {"operation": "burn_subtitles"}}

    preset = str(inputs.get("preset", "standard"))
    out_dir = ASSET_ROOT / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{asset_id}.mp4"
    if preset == "short_vertical":
        args = ["-y", "-i", str(src), "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    elif preset == "compress":
        args = ["-y", "-i", str(src), "-c:v", "libx264", "-preset", "medium", "-crf", "27",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    elif preset == "standard":
        args = ["-y", "-i", str(src), "-vf", "scale=1920:-2:force_original_aspect_ratio=decrease",
                "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    else:
        raise ValueError("Unknown render preset; allowed: standard, short_vertical, compress")
    _run_ffmpeg(args)
    meta = _store_output(out, asset_id, "video/mp4")
    return {"assets": [meta], "result": {"operation": "render", "preset": preset}}


def _run_asr_job(task_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("ASR_WORKER_URL", "").strip().rstrip("/")
    api_key = os.getenv("ASR_WORKER_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("ASR_WORKER_URL and ASR_WORKER_API_KEY must be configured for transcription")
    source_id = str(inputs.get("source_asset_id", ""))
    path, meta = _asset(source_id)
    with httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False) as client:
        with path.open("rb") as stream:
            response = client.post(
                f"{base_url}/v1/transcribe",
                files={"file": (path.name, stream, meta.get("mime_type", "application/octet-stream"))},
                data={"task_id": task_id, "language": str(inputs.get("language") or "")},
                headers={"Authorization": f"Bearer {api_key}"},
            )
    response.raise_for_status()
    return {"assets": [], "result": response.json()}


def _replace_template(value: Any, prompt: str, negative_prompt: str, seed: int) -> Any:
    if isinstance(value, dict):
        return {key: _replace_template(item, prompt, negative_prompt, seed) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_template(item, prompt, negative_prompt, seed) for item in value]
    if value == "{{PROMPT}}":
        return prompt
    if value == "{{NEGATIVE_PROMPT}}":
        return negative_prompt
    if value == "{{SEED}}":
        return seed
    return value


def _run_comfyui_job(task_id: str, task_type: str, inputs: dict[str, Any], commercial_use: bool) -> dict[str, Any]:
    base_url = os.getenv("COMFYUI_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("COMFYUI_BASE_URL is not configured; generation is not running in the Vercel process")
    workflow_id = str(inputs.get("workflow_id", ""))
    if not re.fullmatch(r"[a-zA-Z0-9_-]{2,120}", workflow_id):
        raise ValueError("workflow_id must identify a reviewed server-side ComfyUI workflow")
    workflow_path = (WORKFLOW_ROOT / f"{workflow_id}.json").resolve()
    if WORKFLOW_ROOT.resolve() not in workflow_path.parents or not workflow_path.is_file():
        raise FileNotFoundError("Reviewed ComfyUI workflow template not found")
    graph = json.loads(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise ValueError("ComfyUI workflow template must be a JSON object")
    prompt = str(inputs.get("prompt", "")).strip()
    if not prompt or len(prompt) > 6000:
        raise ValueError("prompt must contain 1-6000 characters")
    negative_prompt = str(inputs.get("negative_prompt", ""))[:3000]
    seed = inputs.get("seed", 1)
    if not isinstance(seed, int) or seed < 0 or seed > 2**53:
        raise ValueError("seed must be a non-negative integer")
    graph = _replace_template(graph, prompt, negative_prompt, seed)
    client_id = task_id
    api_key = os.getenv("COMFYUI_API_KEY", "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
        response = client.post(f"{base_url}/prompt", json={"prompt": graph, "client_id": client_id}, headers=headers)
        response.raise_for_status()
        queue_result = response.json()
        prompt_id = str(queue_result.get("prompt_id", ""))
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return a prompt_id")
        deadline = time.time() + float(os.getenv("COMFYUI_JOB_TIMEOUT_SECONDS", "900"))
        history: dict[str, Any] = {}
        while time.time() < deadline:
            time.sleep(2)
            poll = client.get(f"{base_url}/history/{prompt_id}", headers=headers)
            poll.raise_for_status()
            hist = poll.json()
            if prompt_id in hist:
                history = hist[prompt_id]
                break
        if not history:
            raise TimeoutError("ComfyUI job timed out")
        outputs = history.get("outputs", {})
        saved: list[dict[str, Any]] = []
        # Save the first output media from each ComfyUI node; multiple outputs are supported.
        for node_output in outputs.values():
            for key in ("images", "gifs", "videos", "audio"):
                for item in node_output.get(key, []) if isinstance(node_output, dict) else []:
                    filename = str(item.get("filename", ""))
                    subfolder = str(item.get("subfolder", ""))
                    outtype = str(item.get("type", "output"))
                    if not filename or Path(filename).name != filename or ".." in subfolder:
                        continue
                    view = client.get(f"{base_url}/view", params={"filename": filename, "subfolder": subfolder, "type": outtype}, headers=headers)
                    view.raise_for_status()
                    suffix = Path(filename).suffix.lower()
                    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".wav", ".mp3", ".flac"}:
                        continue
                    if suffix in {".mp4", ".webm"}:
                        folder = ASSET_ROOT / "videos"
                    elif suffix in {".wav", ".mp3", ".flac"}:
                        folder = ASSET_ROOT / "audio"
                    else:
                        folder = ASSET_ROOT / "images"
                    folder.mkdir(parents=True, exist_ok=True)
                    asset_id = "asset-" + uuid4().hex
                    path = folder / f"{asset_id}{suffix}"
                    path.write_bytes(view.content)
                    mime = ("video/mp4" if suffix == ".mp4" else "video/webm") if suffix in {".mp4", ".webm"} else ("audio/wav" if suffix == ".wav" else "audio/mpeg" if suffix == ".mp3" else "audio/flac" if suffix == ".flac" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png" if suffix == ".png" else "image/webp")
                    saved.append(_store_output(path, asset_id, mime))
        if not saved:
            raise RuntimeError("ComfyUI job completed but returned no supported output assets")
    return {"assets": saved, "result": {"workflow_id": workflow_id, "comfyui_prompt_id": prompt_id, "task_type": task_type}}


def _unused_fallback_marker() -> None:
    # Keep the media worker's safe preset list explicit; arbitrary ffmpeg filters/commands are not accepted.
    return None
