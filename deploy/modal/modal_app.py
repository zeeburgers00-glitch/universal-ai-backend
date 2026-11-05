"""Deploy the GPU voice worker to Modal.

Why Modal for this worker: it hands out an HTTPS URL natively (the API rejects
plain http:// for any non-loopback worker), it scales to zero so an idle voice
worker costs nothing, and its free tier is $30/month of compute — roughly 50
hours of T4.

    pip install modal && modal token new
    modal secret create voice-worker-secret VOICE_WORKER_API_KEY=<long-random-string>
    modal deploy deploy/modal/modal_app.py

The worker is Celery-based: /v1/voice/tts queues a task and returns a task id, so
Redis and a Celery worker have to run inside the same container as the API. That
is what `_boot_worker` sets up.
"""

from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import modal

WORKER_DIR = Path(__file__).resolve().parents[2] / "workers" / "voice_worker"

app = modal.App("universal-ai-voice-worker")

# T4 (16 GB) is enough for MeloTTS and F5-TTS and is the cheapest GPU Modal
# offers. Never use gpu="any" here: "any" can land on an H100 at ~$3.95/hr when a
# T4 at ~$0.59/hr would have done the same job.
VOICE_GPU = "T4"

voice_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "redis-server", "git")
    .pip_install("torch==2.6.0", index_url="https://download.pytorch.org/whl/cu124")
    .pip_install(
        "fastapi>=0.115,<1.0",
        "uvicorn[standard]>=0.30,<1.0",
        "celery[redis]>=5.4,<6.0",
        "f5-tts>=1.1.0",
        "MeloTTS",
    )
    .add_local_dir(str(WORKER_DIR), remote_path="/srv/voice_worker")
)

# Model weights and generated audio survive container restarts here. Without a
# volume every cold start re-downloads several GB of TTS weights.
data = modal.Volume.from_name("universal-ai-voice-data", create_if_missing=True)

# Created once with `modal secret create voice-worker-secret ...`. Deploying
# without it fails loudly instead of starting an unauthenticated worker.
worker_secret = modal.Secret.from_name("voice-worker-secret")


def _run_celery() -> None:
    subprocess.run(
        [
            sys.executable, "-m", "celery",
            "-A", "voice_worker.app.celery_app", "worker",
            "--loglevel=INFO", "--concurrency=1", "--pool=solo",
        ],
        cwd="/srv",
        check=False,
    )


def _wait_for_redis(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 6379), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Redis did not become reachable within 30s")


def _boot_worker() -> None:
    """Prepare env, start Redis and a Celery worker inside this container."""
    os.environ.setdefault("PYTHONPATH", "/srv")
    os.environ.setdefault("VOICE_DATA_ROOT", "/data")
    os.environ.setdefault("HF_HOME", "/data/hf")
    os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    if not os.environ.get("VOICE_WORKER_API_KEY", "").strip():
        raise RuntimeError(
            "VOICE_WORKER_API_KEY is empty. Create the secret first:\n"
            "  modal secret create voice-worker-secret VOICE_WORKER_API_KEY=<random>"
        )

    for directory in ("/data/assets", "/data/generated", "/data/profiles", "/data/hf"):
        os.makedirs(directory, exist_ok=True)

    subprocess.Popen(
        ["redis-server", "--port", "6379", "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_redis()

    threading.Thread(target=_run_celery, name="celery", daemon=True).start()


@app.function(
    image=voice_image,
    gpu=VOICE_GPU,
    timeout=1800,
    scaledown_window=300,
    max_containers=2,
    volumes={"/data": data},
    secrets=[worker_secret],
)
@modal.asgi_app()
def voice_api():
    """HTTPS endpoint for the whole voice worker.

    Routes: /health (open), plus /v1/voice/* guarded by the worker key.
    """
    _boot_worker()
    from voice_worker.app import app as fastapi_app

    return fastapi_app


@app.function(image=voice_image, volumes={"/data": data}, timeout=1800, secrets=[worker_secret])
def prewarm() -> dict[str, str]:
    """Download TTS weights into the volume once, so the first real job is fast.

        modal run deploy/modal/modal_app.py::prewarm
    """
    os.environ.setdefault("HF_HOME", "/data/hf")
    os.makedirs("/data/hf", exist_ok=True)
    from huggingface_hub import snapshot_download

    paths: dict[str, str] = {}
    for repo in ("SWivid/F5-TTS", "myshell-ai/MeloTTS-English"):
        try:
            paths[repo] = snapshot_download(repo_id=repo)
        except Exception as exc:  # a missing optional repo must not fail prewarm
            paths[repo] = f"skipped: {type(exc).__name__}"
    data.commit()
    return paths


# --------------------------------------------------------------------------- #
# Optional: thumbnail images from a text prompt.
#
# Kept separate from the voice worker because it needs its own heavy image and a
# different GPU class. Runs Stable Diffusion 1.5 on a T4 (~$0.59/hr).
# Licence: CreativeML OpenRAIL-M — commercial use allowed, with use-based
# restrictions you must read before shipping. Weights are cached on the volume.
# --------------------------------------------------------------------------- #
image_gpu = "T4"

sd_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch==2.6.0", index_url="https://download.pytorch.org/whl/cu124")
    .pip_install("diffusers[torch]>=0.31", "transformers>=4.44", "accelerate", "safetensors", "fastapi")
)


@app.function(image=sd_image, gpu=image_gpu, timeout=600, scaledown_window=120, volumes={"/data": data})
def _generate_image(prompt: str, steps: int = 8, width: int = 768, height: int = 432) -> bytes:
    import io

    os.environ.setdefault("HF_HOME", "/data/hf")
    import torch
    from diffusers import StableDiffusionPipeline

    pipe = StableDiffusionPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        torch_dtype=torch.float16,
        safety_checker=None,
    ).to("cuda")
    image = pipe(prompt, num_inference_steps=max(4, min(steps, 30)), width=width, height=height).images[0]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data.commit()
    return buffer.getvalue()


@app.function(image=sd_image, gpu=image_gpu, timeout=600, scaledown_window=120, volumes={"/data": data})
@modal.fastapi_endpoint(method="POST", docs=True)
def thumbnail(payload: dict) -> dict:
    """POST {"prompt": "...", "steps": 8} -> {"image_base64": "..."}."""
    prompt = str((payload or {}).get("prompt") or "").strip()
    if not prompt:
        return {"error": "prompt is required"}
    png = _generate_image.remote(
        prompt,
        int((payload or {}).get("steps") or 8),
        int((payload or {}).get("width") or 768),
        int((payload or {}).get("height") or 432),
    )
    return {"image_base64": base64.b64encode(png).decode("ascii"), "mime": "image/png"}
