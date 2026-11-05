#!/usr/bin/env python3
"""Run the GPU voice worker on a free Kaggle notebook and expose it over HTTPS.

Kaggle gives free T4 x2 GPUs, but notebooks have no public inbound port. So this
script starts the worker on localhost:8100 and opens a Cloudflare quick tunnel
(no account needed) which yields an https://<random>.trycloudflare.com URL.
The API only accepts a remote worker over HTTPS, so the tunnel is required --
plain http:// is rejected for anything other than 127.0.0.1.

Usage on Kaggle (a cell, with "Internet" enabled in notebook settings):

    !python run_voice_worker.py

Keep the cell running. It prints the tunnel URL and the worker key, which you
copy into the CPU VM's .env as VOICE_WORKER_URL / VOICE_WORKER_API_KEY.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

REPO_URL = os.getenv("REPO_URL", "https://github.com/zeeburgers00-glitch/universal-ai-backend.git")
WORK_DIR = os.getenv("WORK_DIR", "/kaggle/working")
REPO_DIR = os.path.join(WORK_DIR, "universal-ai-backend")
WORKER_PORT = int(os.getenv("WORKER_PORT", "8100"))
DATA_ROOT = os.getenv("VOICE_DATA_ROOT", os.path.join(WORK_DIR, "voice-data"))
INSTALL_F5 = os.getenv("INSTALL_F5_TTS", "1") == "1"
WORKER_KEY = os.getenv("VOICE_WORKER_API_KEY") or secrets.token_urlsafe(24)

procs: list[subprocess.Popen] = []


def log(msg: str) -> None:
    print(f"\n\033[1;36m[{time.strftime('%H:%M:%S')}] {msg}\033[0m", flush=True)


def warn(msg: str) -> None:
    print(f"\033[1;33m[warn] {msg}\033[0m", flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def check_gpu() -> None:
    try:
        import torch  # noqa: F401  (Kaggle ships it)
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
            log(f"GPU ready: {name} ({vram:.1f} GB)")
            return
        warn("No CUDA device. TTS will be extremely slow on CPU.")
    except Exception as exc:  # pragma: no cover - environment specific
        warn(f"Could not query torch: {exc}")


def install_python_deps() -> None:
    log("Installing worker dependencies (several minutes on first run)")
    base = ["fastapi>=0.115,<1.0", "uvicorn[standard]>=0.30,<1.0", "celery[redis]>=5.4,<6.0"]
    packages = list(base)
    if INSTALL_F5:
        packages.append("f5-tts>=1.1.0")
    packages.append("MeloTTS")
    run([sys.executable, "-m", "pip", "install", "-q", "--no-input", *packages])
    log("Python dependencies installed")


def start_redis() -> str:
    """Voice jobs are Celery tasks, so a broker is required."""
    if shutil.which("redis-server") is None:
        log("Installing redis-server")
        try:
            subprocess.run(["apt-get", "update", "-qq"], check=True)
            subprocess.run(["apt-get", "install", "-y", "-qq", "redis-server"], check=True)
        except subprocess.CalledProcessError:
            warn("apt-get failed; retrying with sudo")
            run(["sudo", "apt-get", "update", "-qq"])
            run(["sudo", "apt-get", "install", "-y", "-qq", "redis-server"])

    password = secrets.token_urlsafe(16)
    log("Starting Redis")
    subprocess.run(
        ["redis-server", "--daemonize", "yes", "--port", "6379",
         "--save", "", "--appendonly", "no", "--requirepass", password],
        check=True,
    )
    time.sleep(2)
    return f"redis://:{password}@127.0.0.1:6379/0"


def fetch_repo() -> None:
    if os.path.isdir(os.path.join(REPO_DIR, ".git")):
        log("Updating existing checkout")
        subprocess.run(["git", "-C", REPO_DIR, "fetch", "--all", "--prune"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "pull", "--ff-only"], check=False)
    else:
        log("Cloning the repository")
        run(["git", "clone", "--depth", "1", REPO_URL, REPO_DIR])


def spawn(name: str, cmd: list[str], env: dict[str, str], logfile: str) -> subprocess.Popen:
    log(f"Starting {name}")
    handle = open(logfile, "ab", buffering=0)
    proc = subprocess.Popen(cmd, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    procs.append(proc)
    return proc


def wait_for_health(timeout: float = 180.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{WORKER_PORT}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(3)
    return False


def start_tunnel() -> str | None:
    binary = os.path.join(WORK_DIR, "cloudflared")
    if not os.path.exists(binary):
        log("Downloading cloudflared")
        urllib.request.urlretrieve(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
            binary,
        )
        os.chmod(binary, 0o755)

    log("Opening the HTTPS tunnel")
    proc = subprocess.Popen(
        [binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{WORKER_PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    procs.append(proc)

    found: dict[str, str | None] = {"url": None}
    pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = pattern.search(line)
            if match and not found["url"]:
                found["url"] = match.group(0)

    threading.Thread(target=pump, daemon=True).start()

    for _ in range(60):
        if found["url"]:
            return found["url"]
        time.sleep(1)
    warn("Could not read the tunnel URL; check the cloudflared output above.")
    return None


def banner(url: str | None) -> None:
    host = url or f"http://127.0.0.1:{WORKER_PORT} (no tunnel)"
    print(
        "\n"
        + "=" * 74
        + "\n  VOICE WORKER IS LIVE\n"
        + "=" * 74
        + f"\n  Worker URL : {host}\n"
        + f"  Worker key : {WORKER_KEY}\n"
        + "\n  Paste these into the CPU VM:\n"
        + f"      VOICE_WORKER_URL={host}\n"
        + f"      VOICE_WORKER_API_KEY={WORKER_KEY}\n"
        + "\n  Then on the VM:\n"
        + "      docker compose restart api\n"
        + "      curl -s http://127.0.0.1:8000/v1/workers/status\n"
        + "\n  Or straight from your laptop:\n"
        + f"      curl -s {host}/health\n"
        + f"      curl -s -H 'Authorization: Bearer {WORKER_KEY}' {host}/v1/voice/providers\n"
        + "\n  Kaggle kills this session at 12h (and after ~20 min idle).\n"
        + "  Keep the notebook tab open. Re-run the cell to get a NEW url.\n"
        + "=" * 74
        + "\n",
        flush=True,
    )


def cleanup(*_: object) -> None:
    for proc in reversed(procs):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
    subprocess.run(["redis-cli", "-a", "unused", "shutdown", "nosave"],
                   capture_output=True, check=False)
    print("\nStopped.")


def main() -> int:
    print("=" * 74)
    print("  Universal AI Backend - GPU voice worker on free Kaggle GPU")
    print("=" * 74)

    check_gpu()
    os.makedirs(DATA_ROOT, exist_ok=True)
    install_python_deps()
    broker = start_redis()
    fetch_repo()

    env = dict(os.environ)
    env.update({
        "PYTHONPATH": os.path.join(REPO_DIR, "workers"),
        "VOICE_WORKER_API_KEY": WORKER_KEY,
        "VOICE_DATA_ROOT": DATA_ROOT,
        "CELERY_BROKER_URL": broker,
        "PYTHONUNBUFFERED": "1",
    })

    # Celery worker executes voice_worker.synthesize from tasks.py.
    spawn(
        "Celery worker",
        [sys.executable, "-m", "celery", "-A", "voice_worker.app.celery_app", "worker",
         "--loglevel=INFO", "--concurrency=1", "--pool=solo"],
        env,
        os.path.join(WORK_DIR, "celery.log"),
    )
    spawn(
        "Uvicorn API",
        [sys.executable, "-m", "uvicorn", "voice_worker.app:app",
         "--host", "0.0.0.0", "--port", str(WORKER_PORT)],
        env,
        os.path.join(WORK_DIR, "uvicorn.log"),
    )

    if not wait_for_health():
        warn("Worker did not become healthy. Tail of uvicorn.log:")
        try:
            with open(os.path.join(WORK_DIR, "uvicorn.log"), "rb") as fh:
                print(fh.read()[-4000:].decode("utf-8", "replace"))
        except OSError:
            pass
        return 1

    log("Worker health check passed")
    url = start_tunnel()
    banner(url)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    try:
        while True:
            time.sleep(600)
            alive = all(p.poll() is None for p in procs)
            log(f"still running (all processes alive: {alive})")
    except KeyboardInterrupt:
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
