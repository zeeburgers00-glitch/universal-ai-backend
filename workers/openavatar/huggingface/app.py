"""Hugging Face ZeroGPU Space worker for OpenAvatar Studio.

Deploy this directory as a Gradio ZeroGPU Space, set its secrets, and press
"Process one queued job" to execute one backend job. It does not poll forever.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import gradio as gr
import requests
import spaces


API_URL = os.getenv("OPENAVATAR_API_URL", "").rstrip("/")
WORKER_TOKEN = os.getenv("OPENAVATAR_WORKER_TOKEN", "")
WORKER_ID = os.getenv("OPENAVATAR_WORKER_ID", "huggingface-zero-gpu")
SADTALKER_ROOT = Path(os.getenv("SADTALKER_ROOT", "/app/SadTalker")).expanduser()


def _headers() -> dict[str, str]:
    if not API_URL.startswith("https://"):
        raise RuntimeError("Set OPENAVATAR_API_URL to the public HTTPS backend URL")
    if len(WORKER_TOKEN) < 32:
        raise RuntimeError("Set OPENAVATAR_WORKER_TOKEN as a Space secret (32+ characters)")
    return {"X-OpenAvatar-Worker-Token": WORKER_TOKEN}


def _post(path: str, payload: dict):
    response = requests.post(f"{API_URL}{path}", headers={**_headers(), "Content-Type": "application/json"}, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def _download_asset(asset_id: str, destination: Path) -> Path:
    response = requests.get(f"{API_URL}/internal/openavatar/assets/{asset_id}", headers=_headers(), timeout=120)
    response.raise_for_status()
    if len(response.content) > 100 * 1024 * 1024:
        raise RuntimeError("Input asset exceeds the worker limit")
    destination.write_bytes(response.content)
    return destination


@spaces.GPU(duration=lambda job, image, audio: int(job.get("max_gpu_seconds", 60)))
def _run_sadtalker(job: dict, image: str, audio: str) -> tuple[str, int]:
    if not (SADTALKER_ROOT / "inference.py").is_file():
        raise RuntimeError("SadTalker checkout is missing; follow the Space README to install it and its checkpoints")
    options = job.get("options") or {}
    output_dir = Path(tempfile.mkdtemp(prefix="openavatar-sadtalker-"))
    results_dir = output_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(SADTALKER_ROOT / "inference.py"),
        "--driven_audio", audio,
        "--source_image", image,
        "--result_dir", str(results_dir),
        "--size", str(options.get("size", 256)),
        "--preprocess", str(options.get("preprocess", "crop")),
    ]
    if options.get("still", False):
        command.append("--still")
    if options.get("enhancer") == "gfpgan":
        command.extend(["--enhancer", "gfpgan"])
    started = time.monotonic()
    subprocess.run(command, cwd=str(SADTALKER_ROOT), check=True, timeout=max(30, int(job.get("max_gpu_seconds", 60)) - 2), capture_output=True, text=True)
    videos = sorted(results_dir.rglob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not videos:
        raise RuntimeError("SadTalker completed without producing an MP4")
    return str(videos[0]), int(max(1, time.monotonic() - started))


def process_one_job() -> str:
    current_job = None
    gpu_started = False
    try:
        _post("/internal/openavatar/heartbeat", {
            "provider": "huggingface_zerogpu",
            "worker_id": WORKER_ID,
            "status": "online",
            "capabilities": ["sadtalker"],
            "gpu_name": "NVIDIA RTX Pro 6000 Blackwell (ZeroGPU allocation)",
            "vram_mb": 49152,
        })
        claimed = _post("/internal/openavatar/jobs/claim", {
            "provider": "huggingface_zerogpu",
            "worker_id": WORKER_ID,
            "capabilities": ["sadtalker"],
        })
        job = claimed.get("job")
        current_job = job
        if not job:
            reason = claimed.get("reason", "No compatible queued jobs")
            return f"Idle: {reason}. No GPU job was executed."
        with tempfile.TemporaryDirectory(prefix="openavatar-input-") as folder:
            work = Path(folder)
            image = _download_asset(job["image_asset_id"], work / "portrait.png")
            audio = _download_asset(job["audio_asset_id"], work / "speech.wav")
            gpu_started = True
            video_path, gpu_seconds = _run_sadtalker(job, str(image), str(audio))
            artifact = Path(video_path)
            with artifact.open("rb") as stream:
                response = requests.put(
                    f"{API_URL}/internal/openavatar/jobs/{job['job_id']}/artifact",
                    headers={**_headers(), "X-OpenAvatar-Worker-Id": WORKER_ID, "X-Filename": artifact.name, "Content-Type": "video/mp4"},
                    data=stream,
                    timeout=300,
                )
                response.raise_for_status()
            response = requests.post(
                f"{API_URL}/internal/openavatar/jobs/{job['job_id']}/complete",
                headers={**_headers(), "X-OpenAvatar-Worker-Id": WORKER_ID},
                json={"actual_gpu_seconds": gpu_seconds, "artifact_name": artifact.name},
                timeout=60,
            )
            response.raise_for_status()
            return f"Completed job {job['job_id']} in approximately {gpu_seconds} GPU seconds."
    except Exception as exc:
        if current_job:
            try:
                requests.post(
                    f"{API_URL}/internal/openavatar/jobs/{current_job['job_id']}/fail",
                    headers={**_headers(), "X-OpenAvatar-Worker-Id": WORKER_ID},
                    json={"error": f"{type(exc).__name__}: {str(exc)[:1500]}", "consumed_gpu_seconds": int(current_job.get("max_gpu_seconds", 60)) if gpu_started else 0},
                    timeout=30,
                )
            except Exception:
                pass
        return f"Worker error: {type(exc).__name__}: {str(exc)[:700]}"


with gr.Blocks(title="OpenAvatar ZeroGPU Worker") as demo:
    gr.Markdown(
        "# OpenAvatar Studio — ZeroGPU Worker\n"
        "This Space processes one queued portrait-to-talking-head job per click. "
        "The free ZeroGPU allowance is shared and quota-limited; this is not an always-on GPU server."
    )
    run_button = gr.Button("Process one queued job", variant="primary")
    output = gr.Textbox(label="Worker result", lines=4)
    run_button.click(process_one_job, inputs=[], outputs=output)

demo.queue(default_concurrency_limit=1).launch()
