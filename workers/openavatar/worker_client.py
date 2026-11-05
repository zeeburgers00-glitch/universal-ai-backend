"""One-job-at-a-time OpenAvatar worker client for Kaggle, Lightning, and local CPU."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx


def _config() -> tuple[str, str, str]:
    api_url = os.getenv("OPENAVATAR_API_URL", "").rstrip("/")
    token = os.getenv("OPENAVATAR_WORKER_TOKEN", "")
    worker_id = os.getenv("OPENAVATAR_WORKER_ID", f"{os.getenv('OPENAVATAR_PROVIDER', 'worker')}-manual")
    if not api_url.startswith("https://") and not api_url.startswith("http://127.0.0.1"):
        raise RuntimeError("OPENAVATAR_API_URL must be HTTPS (localhost is allowed for development)")
    if len(token) < 32:
        raise RuntimeError("OPENAVATAR_WORKER_TOKEN must contain at least 32 characters")
    return api_url, token, worker_id


def _headers(token: str, worker_id: str | None = None) -> dict[str, str]:
    result = {"X-OpenAvatar-Worker-Token": token}
    if worker_id:
        result["X-OpenAvatar-Worker-Id"] = worker_id
    return result


def _request(method: str, url: str, token: str, **kwargs: Any) -> httpx.Response:
    response = httpx.request(method, url, headers={**_headers(token), **kwargs.pop("headers", {})}, timeout=kwargs.pop("timeout", 60), **kwargs)
    response.raise_for_status()
    return response


def _download_asset(api_url: str, token: str, asset_id: str, destination: Path) -> Path:
    response = _request("GET", f"{api_url}/internal/openavatar/assets/{asset_id}", token, timeout=120)
    if len(response.content) > 100 * 1024 * 1024:
        raise RuntimeError("Input asset exceeds the worker download limit")
    destination.write_bytes(response.content)
    return destination


def _run_sadtalker(job: dict[str, Any], image: Path, audio: Path, output_dir: Path) -> Path:
    root = Path(os.getenv("SADTALKER_ROOT", "")).expanduser()
    if not root.is_dir() or not (root / "inference.py").is_file():
        raise RuntimeError("SadTalker is not installed; set SADTALKER_ROOT to a prepared upstream checkout with checkpoints")
    options = job.get("options") or {}
    result_dir = output_dir / "sadtalker-results"
    result_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(root / "inference.py"),
        "--driven_audio", str(audio),
        "--source_image", str(image),
        "--result_dir", str(result_dir),
        "--size", str(options.get("size", 256)),
        "--preprocess", str(options.get("preprocess", "crop")),
    ]
    if options.get("still", False):
        command.append("--still")
    if options.get("enhancer") == "gfpgan":
        command.extend(["--enhancer", "gfpgan"])
    timeout = max(30, int(job.get("max_gpu_seconds", 60)) - 2) if job.get("provider") == "huggingface_zerogpu" else 1800
    subprocess.run(command, cwd=str(root), check=True, timeout=timeout, capture_output=True, text=True)
    outputs = sorted(result_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not outputs:
        raise RuntimeError("SadTalker finished without producing an MP4")
    return outputs[0]


def _run_musetalk(job: dict[str, Any], video: Path, audio: Path, output_dir: Path) -> Path:
    entrypoint = os.getenv("OPENAVATAR_MUSETALK_ADAPTER", "")
    if ":" not in entrypoint:
        raise RuntimeError("MuseTalk is not enabled: configure a reviewed OPENAVATAR_MUSETALK_ADAPTER=module:function")
    module_name, function_name = entrypoint.split(":", 1)
    function = getattr(importlib.import_module(module_name), function_name)
    output = output_dir / "musetalk-output.mp4"
    result = function(
        video_path=str(video),
        audio_path=str(audio),
        output_path=str(output),
        options=job.get("options") or {},
    )
    final_path = Path(result or output)
    if not final_path.is_file():
        raise RuntimeError("MuseTalk adapter did not return an existing video file")
    return final_path


def _run_whisper(job: dict[str, Any], audio: Path, output_dir: Path) -> tuple[Path, str]:
    binary = os.getenv("WHISPER_CPP_BIN", "whisper-cli")
    model = os.getenv("WHISPER_CPP_MODEL", "")
    if not model or not Path(model).is_file():
        raise RuntimeError("Set WHISPER_CPP_MODEL to a locally installed whisper.cpp model file")
    output_base = output_dir / "transcript"
    mode = "-osrt" if job["job_type"] == "captions" else "-otxt"
    subprocess.run(
        [binary, "-m", model, "-f", str(audio), mode, "-of", str(output_base)],
        check=True, timeout=1800, capture_output=True, text=True,
    )
    extension = ".srt" if job["job_type"] == "captions" else ".txt"
    result = output_base.with_suffix(extension)
    if not result.is_file():
        raise RuntimeError("whisper.cpp did not produce the requested transcript artifact")
    return result, "application/x-subrip" if extension == ".srt" else "text/plain"


def _run_openvoice(job: dict[str, Any], reference_audio: Path, output_dir: Path) -> Path:
    """Invoke an explicitly installed OpenVoice adapter; never accepts arbitrary commands."""
    entrypoint = os.getenv("OPENAVATAR_OPENVOICE_ADAPTER", "")
    if ":" not in entrypoint:
        raise RuntimeError("OpenVoice is not enabled: configure a reviewed OPENAVATAR_OPENVOICE_ADAPTER=module:function")
    module_name, function_name = entrypoint.split(":", 1)
    function = getattr(importlib.import_module(module_name), function_name)
    output = output_dir / "speech.wav"
    result = function(
        text=job.get("text", ""),
        reference_audio_path=str(reference_audio),
        output_path=str(output),
        options=job.get("options") or {},
    )
    final_path = Path(result or output)
    if not final_path.is_file():
        raise RuntimeError("OpenVoice adapter did not return an existing audio file")
    return final_path


def _run_ffmpeg(job: dict[str, Any], video: Path, audio: Path, output_dir: Path) -> Path:
    binary = os.getenv("FFMPEG_BIN", "ffmpeg")
    output = output_dir / "rendered.mp4"
    subprocess.run(
        [binary, "-y", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output)],
        check=True, timeout=1800, capture_output=True, text=True,
    )
    if not output.is_file():
        raise RuntimeError("FFmpeg did not produce an MP4")
    return output


def run_once(provider: str, capabilities: list[str]) -> dict[str, Any]:
    api_url, token, worker_id = _config()
    heartbeat = {
        "provider": provider,
        "worker_id": worker_id,
        "status": "online",
        "capabilities": capabilities,
        "gpu_name": os.getenv("OPENAVATAR_GPU_NAME"),
        "vram_mb": int(os.getenv("OPENAVATAR_GPU_VRAM_MB", "0") or "0"),
    }
    _request("POST", f"{api_url}/internal/openavatar/heartbeat", token, json=heartbeat)
    claimed = _request(
        "POST", f"{api_url}/internal/openavatar/jobs/claim", token,
        json={"provider": provider, "worker_id": worker_id, "capabilities": capabilities},
    ).json()
    job = claimed.get("job")
    if not job:
        return {"status": "idle", "reason": claimed.get("reason", "no_compatible_job"), "quota": claimed.get("quota")}
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="openavatar-") as temp:
            work = Path(temp)
            image = _download_asset(api_url, token, job["image_asset_id"], work / "portrait.png") if job.get("image_asset_id") else None
            audio = _download_asset(api_url, token, job["audio_asset_id"], work / "audio.wav") if job.get("audio_asset_id") else None
            video = _download_asset(api_url, token, job["video_asset_id"], work / "source.mp4") if job.get("video_asset_id") else None
            artifact_type = "video/mp4"
            if job["engine"] == "sadtalker" and image and audio:
                artifact = _run_sadtalker(job, image, audio, work)
            elif job["engine"] == "musetalk" and video and audio:
                artifact = _run_musetalk(job, video, audio, work)
            elif job["engine"] == "openvoice_v2" and audio:
                artifact = _run_openvoice(job, audio, work)
                artifact_type = "audio/wav"
            elif job["engine"] == "whisper_cpp" and audio:
                artifact, artifact_type = _run_whisper(job, audio, work)
            elif job["engine"] == "ffmpeg" and video and audio:
                artifact = _run_ffmpeg(job, video, audio, work)
            else:
                raise RuntimeError(f"Worker does not have the required inputs for engine {job.get('engine')}")
            elapsed = int(max(0, time.monotonic() - started)) if provider == "huggingface_zerogpu" else 0
            with artifact.open("rb") as source:
                _request(
                    "PUT", f"{api_url}/internal/openavatar/jobs/{job['job_id']}/artifact", token,
                    data=source,
                    headers={
                        "Content-Type": artifact_type,
                        "X-OpenAvatar-Worker-Id": worker_id,
                        "X-Filename": artifact.name,
                    },
                    timeout=300,
                )
            _request(
                "POST", f"{api_url}/internal/openavatar/jobs/{job['job_id']}/complete", token,
                json={"actual_gpu_seconds": elapsed, "artifact_name": artifact.name},
                headers={"X-OpenAvatar-Worker-Id": worker_id},
            )
            return {"status": "completed", "job_id": job["job_id"], "artifact": artifact.name, "gpu_seconds": elapsed}
    except Exception as exc:
        consumed = int(max(0, time.monotonic() - started)) if provider == "huggingface_zerogpu" else 0
        try:
            _request(
                "POST", f"{api_url}/internal/openavatar/jobs/{job['job_id']}/fail", token,
                json={"error": str(exc)[:1800], "consumed_gpu_seconds": consumed},
                headers={"X-OpenAvatar-Worker-Id": worker_id},
            )
        except Exception:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Process at most one OpenAvatar job; no paid provider fallback.")
    parser.add_argument("--provider", choices=["local_cpu", "kaggle", "lightning"], required=True)
    parser.add_argument("--capabilities", default="sadtalker,musetalk,whisper_cpp,ffmpeg")
    args = parser.parse_args()
    result = run_once(args.provider, [item.strip() for item in args.capabilities.split(",") if item.strip()])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
