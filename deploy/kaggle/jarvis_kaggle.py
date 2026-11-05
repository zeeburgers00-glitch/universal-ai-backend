"""Run this backend (JARVIS + the tool belt) on a Kaggle notebook GPU box.

Kaggle gives you a free machine with no inbound ports: you cannot open port 8000 to the
internet. Two honest ways out, both used here:

1. ``cloudflared`` quick tunnel — a public ``https://<random>.trycloudflare.com`` URL with
   no account, valid while the notebook runs.
2. Keep it local and talk to it from the notebook cell itself (``--backend-only``).

Usage in a Kaggle cell::

    !python deploy/kaggle/jarvis_kaggle.py --port 8000

Secrets (Kaggle → Add-ons → Secrets) that this reads if present:
    ANTHROPIC_API_KEY  Claude brain (paid, your key)
    BACKEND_API_KEY    the key clients must send to /v1/*
    TELEGRAM_TOKEN     optional, for /v1/belt/telegram

Everything it cannot find is reported, never invented. If ANTHROPIC_API_KEY is absent the
backend still runs — JARVIS falls back to rules, or to a local Ollama server if you
started one (``ollama serve`` + ``--provider ollama``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
LOG_DIR = Path(os.getenv("KAGGLE_WORKING_DIR") or "/kaggle/working")
DATA_ROOT = str(LOG_DIR / "uai-data") if LOG_DIR.exists() else "/tmp/uai-data"


# --------------------------------------------------------------------------- #
# Small, testable pieces
# --------------------------------------------------------------------------- #

def public_url(line: str) -> str | None:
    """Pull the trycloudflare URL out of cloudflared's banner."""

    match = TUNNEL_RE.search(line or "")
    return match.group(0) if match else None


def read_secret(name: str) -> str:
    """Kaggle user secret first, then the environment. Empty string when missing."""

    try:  # only importable inside a Kaggle notebook
        from kaggle_secrets import UserSecretsClient

        value = UserSecretsClient().get_secret(name)
        if value:
            return str(value).strip()
    except Exception:  # noqa: BLE001 - not on Kaggle, or secret not attached
        pass
    return (os.getenv(name) or "").strip()


def which_cloudflared() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    local = Path("/tmp/cloudflared")
    return str(local) if local.exists() else None


def install_cloudflared() -> str:
    """Download the static binary once. Needs internet, which Kaggle can enable."""

    existing = which_cloudflared()
    if existing:
        return existing
    target = Path("/tmp/cloudflared")
    print("downloading cloudflared …", flush=True)
    urllib.request.urlretrieve(CLOUDFLARED_URL, target)  # noqa: S310 - fixed https URL
    target.chmod(0o755)
    return str(target)


def wait_for_health(base: str = "http://127.0.0.1:8000", timeout: float = 120.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                if client.get(f"{base}/health").status_code < 500:
                    return True
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(1.5)
    return False


# --------------------------------------------------------------------------- #
# Process orchestration
# --------------------------------------------------------------------------- #

def start_backend(port: int, api_key: str, provider_order: str) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "BACKEND_API_KEY": api_key,
        "UAI_DATA_ROOT": DATA_ROOT,
        "UAI_JOBS_DISABLE": "0",
        "PYTHONUNBUFFERED": "1",
    })
    if provider_order:
        env["AI_PROVIDER_ORDER"] = provider_order
    Path(DATA_ROOT).mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "backend.log", "w") if LOG_DIR.exists() else subprocess.DEVNULL
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
         "--port", str(port), "--log-level", "info"],
        cwd=str(REPO_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def start_tunnel(port: int) -> tuple[subprocess.Popen, str | None]:
    binary = install_cloudflared()
    log_path = (LOG_DIR / "tunnel.log") if LOG_DIR.exists() else Path("/tmp/tunnel.log")
    log = open(log_path, "w")
    process = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--url",
                                f"http://127.0.0.1:{port}"],
                               stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 45
    while time.time() < deadline and process.poll() is None:
        time.sleep(1.0)
        try:
            text = log_path.read_text(errors="replace")
        except OSError:
            continue
        url = public_url(text)
        if url:
            return process, url
    return process, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host this backend + tool belt on Kaggle")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--backend-only", action="store_true", help="no public tunnel")
    parser.add_argument("--provider", default="", help="AI_PROVIDER_ORDER, e.g. anthropic or ollama")
    parser.add_argument("--api-key", default="", help="client key; defaults to BACKEND_API_KEY secret")
    args = parser.parse_args(argv)

    api_key = args.api_key or read_secret("BACKEND_API_KEY") or "kaggle-local-key"
    claude = read_secret("ANTHROPIC_API_KEY")
    if claude:
        os.environ["ANTHROPIC_API_KEY"] = claude

    print(json.dumps({
        "repo": str(REPO_ROOT),
        "data_root": DATA_ROOT,
        "claude_key": "found" if claude else "missing (rules or Ollama will answer)",
        "provider_order": args.provider or "default",
    }, indent=2), flush=True)

    backend = start_backend(args.port, api_key, args.provider)
    base = f"http://127.0.0.1:{args.port}"
    if not wait_for_health(base):
        print("backend did not answer /health — tail of backend.log:", flush=True)
        log_path = LOG_DIR / "backend.log"
        if log_path.exists():
            print("\n".join(log_path.read_text(errors="replace").splitlines()[-30:]), flush=True)
        backend.terminate()
        return 1

    tunnel_process = None
    url = None
    if not args.backend_only:
        tunnel_process, url = start_tunnel(args.port)

    def shutdown(*_: object) -> None:
        for process in (tunnel_process, backend):
            if process and process.poll() is None:
                process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    result = {
        "local_url": base,
        "public_url": url or "unavailable: tunnel did not print a URL (see /kaggle/working/tunnel.log)",
        "api_key": api_key,
        "claude": bool(claude),
        "try": [
            f'curl -s {url or base}/v1/belt/status -H "X-API-Key: {api_key}"',
            f'curl -s -X POST {url or base}/v1/jarvis/chat -H "X-API-Key: {api_key}" '
            '-H "Content-Type: application/json" -d \'{"message":"kitne tools hain"}\'',
        ],
        "note": "Kaggle stops the notebook after ~9-12h and wipes /kaggle/working on restart; "
                "processes die when the session ends.",
    }
    print(json.dumps(result, indent=2), flush=True)
    try:
        backend.wait()
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
