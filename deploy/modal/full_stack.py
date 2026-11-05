"""Deploy the WHOLE backend to Modal — control plane + every HTTP worker.

Why Modal for this: it gives an HTTPS URL per service (the gateway refuses plain
http:// for anything that is not loopback), it scales to zero so an idle stack
costs $0, and the free plan includes $30/month of compute — roughly 50 hours of
T4. No credit card is required to start.

    pip install modal
    modal token new                                   # one-time login
    modal secret create uai-backend \\
        BACKEND_API_KEY=<long-random> \\
        VOICE_WORKER_API_KEY=<long-random> \\
        MEDIA_WORKER_API_KEY=<long-random> \\
        ...                                            # any provider keys you have
    modal deploy deploy/modal/full_stack.py

Then smoke-test everything that came up:

    python deploy/modal/smoke.py --base https://<workspace>--uai-api.modal.run

What is NOT deployed here, on purpose: `autopilot_worker` is a Celery *consumer*
with no HTTP port. Modal runs request-scoped containers, so a long-lived consumer
belongs on a small always-on box (or Upstash Redis + a $5 VPS). Everything that
answers HTTP is covered below.
"""

from __future__ import annotations

import os
import sys

import modal

# --------------------------------------------------------------------------- #
# Image
# --------------------------------------------------------------------------- #
APP_NAME = "universal-ai-backend"
ROOT = "."

# ffmpeg is required by media/video paths; redis-server lets the Celery-backed
# workers queue and consume inside their own container without external infra.
base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "redis-server", "ca-certificates", "git")
    .pip_install(
        "fastapi>=0.115,<1.0",
        "uvicorn[standard]>=0.30,<1.0",
        "httpx>=0.27,<1.0",
        "pydantic>=2.7,<3.0",
        "celery[redis]>=5.4,<6.0",
        "redis>=5.0,<7.0",
        "python-multipart>=0.0.9,<1.0",
        "python-dotenv>=1.0,<2.0",
        "imageio-ffmpeg>=0.5,<1.0",
        "numpy>=1.26,<3.0",
    )
    .add_local_dir("app", remote_path="/root/app")
    .add_local_dir("catalog", remote_path="/root/catalog")
    .add_local_dir("videoengine", remote_path="/root/videoengine")
    .add_local_dir("workers", remote_path="/root/workers")
    .workdir("/root")
    .env({"PYTHONPATH": "/root:/root/workers"})
)

app = modal.App(APP_NAME)

#: Everything that answers HTTP. GPU only where it earns its keep.
SERVICES: dict[str, dict] = {
    # name: module:attribute, port, gpu, extra env
    "api": {"module": "app.main", "attr": "app", "port": 8000, "gpu": None},
    "voice": {"module": "voice_worker.app", "attr": "app", "port": 8100, "gpu": "T4"},
    "media": {"module": "media_worker.app", "attr": "app", "port": 8400, "gpu": None},
    "youtube": {"module": "youtube_worker.app", "attr": "app", "port": 8200, "gpu": None},
    "channel": {"module": "channel_worker.app", "attr": "app", "port": 8300, "gpu": None},
    "agent": {"module": "agent_worker.app", "attr": "app", "port": 8500, "gpu": None},
    "automation": {"module": "automation_worker.app", "attr": "app", "port": 8600, "gpu": None},
    "rea": {"module": "rea_worker.app", "attr": "app", "port": 8700, "gpu": None},
}


def _boot(service: str) -> None:
    """Per-container preparation: writable data dirs + an in-container Redis.

    The Celery-backed workers call `send_task`, which fails with a clean 503 when
    no broker exists. Starting redis-server inside the same container keeps the
    deploy dependency-free while still letting those routes work.
    """

    import subprocess
    import time

    data_root = f"/tmp/uai-{service}"
    os.makedirs(data_root, exist_ok=True)
    for name in ("VOICE_DATA_ROOT", "MEDIA_DATA_ROOT", "YOUTUBE_MEDIA_ASSET_ROOT",
                 "REA_ALLOWED_WORKSPACE_ROOT", "WINDOWS_AGENT_WORKSPACE"):
        os.environ.setdefault(name, data_root)
    os.environ.setdefault("UAI_DATA_ROOT", data_root)

    if os.getenv("UAI_START_REDIS", "1") == "1" and service != "api":
        try:
            subprocess.Popen(
                ["redis-server", "--port", "6379", "--save", "", "--appendonly", "no"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
        except OSError:
            # No redis binary: the worker still serves /health and returns 503 on
            # enqueue instead of crashing. Never silently pretend it worked.
            pass


def _load(module: str, attr: str):
    import importlib

    return getattr(importlib.import_module(module), attr)


# --------------------------------------------------------------------------- #
# Control plane (public API)
# --------------------------------------------------------------------------- #
@app.function(
    image=base_image,
    timeout=900,
    scaledown_window=300,
    secrets=[modal.Secret.from_name("uai-backend", required=False)],
)
@modal.asgi_app()
def api():
    _boot("api")
    sys.path.insert(0, "/root")
    return _load("app.main", "app")


# --------------------------------------------------------------------------- #
# GPU: voice worker (TTS + cloning)
# --------------------------------------------------------------------------- #
@app.function(
    image=base_image,
    gpu="T4",              # never "any": that can land on an H100 at ~$3.95/hr
    timeout=1800,
    scaledown_window=180,
    secrets=[modal.Secret.from_name("uai-backend", required=False)],
)
@modal.asgi_app()
def voice():
    _boot("voice")
    sys.path.insert(0, "/root/workers")
    return _load("voice_worker.app", "app")


# --------------------------------------------------------------------------- #
# CPU workers
# --------------------------------------------------------------------------- #
@app.function(image=base_image, timeout=1800, scaledown_window=180,
              secrets=[modal.Secret.from_name("uai-backend", required=False)])
@modal.asgi_app()
def media():
    _boot("media")
    sys.path.insert(0, "/root/workers")
    return _load("media_worker.app", "app")


@app.function(image=base_image, timeout=900, scaledown_window=180,
              secrets=[modal.Secret.from_name("uai-backend", required=False)])
@modal.asgi_app()
def youtube():
    _boot("youtube")
    sys.path.insert(0, "/root/workers")
    return _load("youtube_worker.app", "app")


@app.function(image=base_image, timeout=900, scaledown_window=180,
              secrets=[modal.Secret.from_name("uai-backend", required=False)])
@modal.asgi_app()
def channel():
    _boot("channel")
    sys.path.insert(0, "/root/workers")
    return _load("channel_worker.app", "app")


@app.function(image=base_image, timeout=900, scaledown_window=180,
              secrets=[modal.Secret.from_name("uai-backend", required=False)])
@modal.asgi_app()
def agent():
    _boot("agent")
    sys.path.insert(0, "/root/workers")
    return _load("agent_worker.app", "app")


@app.function(image=base_image, timeout=900, scaledown_window=180,
              secrets=[modal.Secret.from_name("uai-backend", required=False)])
@modal.asgi_app()
def automation():
    _boot("automation")
    sys.path.insert(0, "/root/workers")
    return _load("automation_worker.app", "app")


@app.function(image=base_image, timeout=900, scaledown_window=180,
              secrets=[modal.Secret.from_name("uai-backend", required=False)])
@modal.asgi_app()
def rea():
    _boot("rea")
    sys.path.insert(0, "/root/workers")
    return _load("rea_worker.app", "app")


# --------------------------------------------------------------------------- #
# One-shot video job (no server, pure function call) + persistent render volume
# --------------------------------------------------------------------------- #
render_volume = modal.Volume.from_name("uai-renders", create_if_missing=True)


@app.function(
    image=base_image,
    timeout=1800,
    volumes={"/renders": render_volume},
    secrets=[modal.Secret.from_name("uai-backend", required=False)],
)
def render_command(command: str, scene_seconds: float = 6.0, wait_seconds: int = 900) -> dict:
    """Render one command to a finished MP4 using the real API code path.

    It drives `/v1/command` in-process instead of re-implementing the pipeline, so
    the function cannot drift from what the HTTP API actually does.
    """

    import time

    _boot("render")
    os.environ.setdefault("UAI_DATA_ROOT", "/renders/data")
    sys.path.insert(0, "/root")

    from fastapi.testclient import TestClient

    from app.main import app as control_plane

    key = (os.getenv("BACKEND_API_KEY") or "").strip()
    headers = {"X-API-Key": key} if key else {}

    with TestClient(control_plane) as client:
        created = client.post(
            "/v1/command",
            json={"command": command, "scene_seconds": scene_seconds},
            headers=headers,
        )
        if created.status_code >= 400:
            return {"ok": False, "stage": "create", "status": created.status_code,
                    "detail": created.text[:500]}

        job_id = created.json()["job_id"]
        deadline = time.time() + wait_seconds
        job: dict = {}
        while time.time() < deadline:
            time.sleep(2)
            polled = client.get(f"/v1/command/{job_id}", headers=headers)
            if polled.status_code != 200:
                return {"ok": False, "stage": "poll", "status": polled.status_code}
            job = polled.json()
            if job.get("stage") in {"done", "failed"}:
                break

        if job.get("stage") != "done":
            return {"ok": False, "stage": job.get("stage"), "job_id": job_id,
                    "error": job.get("error")}

        video = client.get(f"/v1/command/{job_id}/video", headers=headers)
        if video.status_code >= 400:
            return {"ok": False, "stage": "download", "status": video.status_code}

        target = f"/renders/{job_id}.mp4"
        with open(target, "wb") as handle:
            handle.write(video.content)

    render_volume.commit()
    return {
        "ok": True,
        "job_id": job_id,
        "volume_path": target,
        "size_bytes": os.path.getsize(target),
        "note": "Pull it with: modal volume get uai-renders <job_id>.mp4",
    }
