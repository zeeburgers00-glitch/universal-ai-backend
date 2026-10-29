"""Safe outbound gateway to workers hosted separately from Vercel.

Only server-configured base URLs are used. The browser cannot choose a target URL.
"""
import os
import re
from typing import Any

import httpx
from fastapi import HTTPException


SERVICES = {
    "voice": {"url_env": "VOICE_WORKER_URL", "key_env": "VOICE_WORKER_API_KEY"},
    "openvoice": {"url_env": "OPENVOICE_WORKER_URL", "key_env": "OPENVOICE_WORKER_API_KEY"},
    "media": {"url_env": "MEDIA_WORKER_URL", "key_env": "MEDIA_WORKER_API_KEY"},
    "automation": {"url_env": "AUTOMATION_WORKER_URL", "key_env": "AUTOMATION_WORKER_API_KEY"},
    "agents": {"url_env": "AGENT_WORKER_URL", "key_env": "AGENT_WORKER_API_KEY"},
    "desktop": {"url_env": "DESKTOP_AGENT_URL", "key_env": "DESKTOP_AGENT_API_KEY"},
    "youtube": {"url_env": "YOUTUBE_WORKER_URL", "key_env": "YOUTUBE_WORKER_API_KEY"},
    "channels": {"url_env": "CHANNEL_WORKER_URL", "key_env": "CHANNEL_WORKER_API_KEY"},
    "rea": {"url_env": "REA_WORKER_URL", "key_env": "REA_WORKER_API_KEY"},
}
SAFE_PATH = re.compile(r"^/v1/[a-zA-Z0-9/_-]{1,120}$")


def service_status() -> list[dict[str, Any]]:
    result = []
    for service_id, config in SERVICES.items():
        base_url = os.getenv(config["url_env"], "").strip()
        secret = os.getenv(config["key_env"], "").strip()
        result.append({
            "id": service_id,
            "configured": bool(base_url and secret),
            "url_configured": bool(base_url),
            "secret_configured": bool(secret),
            "url_env": config["url_env"],
            "secret_env": config["key_env"],
            "status": "configured" if base_url and secret else "not_configured",
            "note": "Only the configuration state is returned. Secret values and base URLs are never echoed.",
        })
    return result


def _worker_config(service: str) -> tuple[str, str]:
    config = SERVICES.get(service)
    if not config:
        raise HTTPException(status_code=400, detail="Unknown worker service")
    base_url = os.getenv(config["url_env"], "").strip().rstrip("/")
    api_key = os.getenv(config["key_env"], "").strip()
    if not base_url or not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"{service} worker is not configured. Set {config['url_env']} and {config['key_env']} in the server environment.",
        )
    if not base_url.startswith("https://"):
        allow_http = os.getenv("WORKER_ALLOW_INSECURE_HTTP", "").lower() == "true"
        is_local = base_url.startswith(("http://127.0.0.1", "http://localhost"))
        if not (allow_http and is_local):
            raise HTTPException(status_code=503, detail="Worker URL must use HTTPS outside explicitly enabled local development")
    return base_url, api_key


async def post_worker(
    service: str,
    path: str,
    payload: dict[str, Any],
    timeout_seconds: float = 90.0,
) -> tuple[int, str, bytes]:
    """POST a bounded JSON job to a server-configured worker endpoint.

    The worker should enqueue long-running work and return a job/task identifier.
    The Vercel API does not execute arbitrary repositories or keep durable job state.
    """
    if not SAFE_PATH.fullmatch(path) or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid worker route")
    base_url, api_key = _worker_config(service)
    timeout = httpx.Timeout(timeout_seconds, connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                base_url + path,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-Worker-Service": service,
                    "Content-Type": "application/json",
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"{service} worker timed out; check worker health and job status")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"{service} worker request failed: {type(exc).__name__}")

    if response.status_code >= 400:
        # Keep upstream response bodies private to avoid leaking provider/worker internals.
        raise HTTPException(status_code=502, detail=f"{service} worker returned HTTP {response.status_code}")
    content_type = response.headers.get("content-type", "application/octet-stream")
    return response.status_code, content_type, response.content


async def get_worker(service: str, path: str, timeout_seconds: float = 15.0) -> tuple[int, str, bytes]:
    """GET a worker status/health endpoint through a configured fixed service URL."""
    if not SAFE_PATH.fullmatch(path) or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid worker route")
    base_url, api_key = _worker_config(service)
    timeout = httpx.Timeout(timeout_seconds, connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(
                base_url + path,
                headers={"Authorization": f"Bearer {api_key}", "X-Worker-Service": service},
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"{service} worker timed out")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"{service} worker request failed: {type(exc).__name__}")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"{service} worker returned HTTP {response.status_code}")
    return response.status_code, response.headers.get("content-type", "application/octet-stream"), response.content
