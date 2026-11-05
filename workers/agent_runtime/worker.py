"""Polling worker for the Universal Agent Runtime.

Requires an explicitly attested no-card executor. It never provisions GPU
capacity or falls back to a paid provider.
"""
from __future__ import annotations

import json
import os
import re
import socket
import time
from threading import Event, Thread
from typing import Any

import httpx


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _executor_url() -> str:
    base = _required("AGENT_WORKER_URL").rstrip("/")
    if not base.startswith("https://"):
        local_ok = os.getenv("AGENT_RUNTIME_ALLOW_INSECURE_LOCAL_HTTP", "").lower() == "true"
        if not (local_ok and base.startswith(("http://127.0.0.1", "http://localhost"))):
            raise RuntimeError("AGENT_WORKER_URL must use HTTPS (local HTTP requires explicit opt-in)")
    return base


def _heartbeat_loop(api: httpx.Client, api_base: str, api_key: str,
                    worker_id: str, task_id: str, stop: Event, lease_seconds: int) -> None:
    interval = max(5, lease_seconds // 3)
    while not stop.wait(interval):
        try:
            response = api.post(
                f"{api_base}/v1/agent-runtime/workers/{worker_id}/tasks/{task_id}/heartbeat",
                headers={"X-API-Key": api_key},
                json={"extend_seconds": lease_seconds},
                timeout=15,
            )
            if response.status_code >= 400:
                stop.set()
                return
        except httpx.HTTPError:
            continue


def execute_one(api: httpx.Client, api_base: str, api_key: str,
                worker_id: str, executor_url: str, executor_key: str,
                executor_path: str, lease_seconds: int) -> bool:
    claim = api.post(
        f"{api_base}/v1/agent-runtime/workers/claim",
        headers={"X-API-Key": api_key},
        json={"worker_id": worker_id},
        timeout=20,
    )
    claim.raise_for_status()
    task = claim.json().get("task")
    if not task:
        return False

    task_id = task["task_id"]
    stop = Event()
    heartbeat = Thread(
        target=_heartbeat_loop,
        args=(api, api_base, api_key, worker_id, task_id, stop, lease_seconds),
        daemon=True,
    )
    heartbeat.start()
    try:
        payload = task.get("payload") or {}
        dispatch = {
            "agent": {"id": task.get("agent_id") or "general-agent"},
            "agent_id": task.get("agent_id"),
            "objective": task["objective"],
            "task_type": task.get("task_type", "agent"),
            "inputs": {
                **(payload.get("inputs") or {}),
                "runtime_task_id": task_id,
                "workflow_id": task.get("workflow_id"),
                "tool_allowlist": payload.get("tool_allowlist") or [],
                "no_paid_provider_fallback": True,
                "no_secrets_in_prompt": True,
            },
            "dry_run": bool(payload.get("dry_run", False)),
            "studio_policy": {
                "no_card_only": True,
                "no_paid_provider_fallback": True,
                "no_secrets_in_prompt": True,
            },
        }
        response = api.post(
            executor_url + executor_path,
            json=dispatch,
            headers={"Authorization": f"Bearer {executor_key}",
                     "X-Worker-Service": "agents", "Content-Type": "application/json"},
            timeout=httpx.Timeout(240, connect=10),
        )
        response.raise_for_status()
        try:
            result: Any = response.json()
        except ValueError:
            result = {"text": response.text[:20000]}
        complete = api.post(
            f"{api_base}/v1/agent-runtime/workers/{worker_id}/tasks/{task_id}/complete",
            headers={"X-API-Key": api_key},
            json={"result": {"executor_status": response.status_code, "output": result}},
            timeout=20,
        )
        complete.raise_for_status()
    except Exception as exc:
        try:
            api.post(
                f"{api_base}/v1/agent-runtime/workers/{worker_id}/tasks/{task_id}/fail",
                headers={"X-API-Key": api_key},
                json={"error": f"{type(exc).__name__}: {str(exc)[:1000]}", "retryable": True},
                timeout=20,
            )
        except httpx.HTTPError:
            pass
    finally:
        stop.set()
        heartbeat.join(timeout=2)
    return True


def main() -> None:
    if os.getenv("AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED", "false").lower() != "true":
        raise RuntimeError("Set AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED=true only after verifying a free/no-card executor.")
    api_base = _required("AGENT_RUNTIME_API_URL").rstrip("/")
    if not api_base.startswith("https://"):
        local_ok = os.getenv("AGENT_RUNTIME_ALLOW_INSECURE_LOCAL_HTTP", "").lower() == "true"
        if not (local_ok and api_base.startswith(("http://127.0.0.1", "http://localhost"))):
            raise RuntimeError("AGENT_RUNTIME_API_URL must use HTTPS outside explicitly enabled local development")
    api_key = _required("BACKEND_API_KEY")
    executor_url = _executor_url()
    executor_key = _required("AGENT_WORKER_API_KEY")
    executor_path = os.getenv("AGENT_RUNTIME_EXECUTOR_PATH", "/v1/agents/run")
    if not re.fullmatch(r"/v1/[A-Za-z0-9/._-]{1,150}", executor_path) or ".." in executor_path:
        raise RuntimeError("AGENT_RUNTIME_EXECUTOR_PATH is invalid")
    worker_id = os.getenv("AGENT_RUNTIME_WORKER_ID", socket.gethostname())[:128]
    lease_seconds = max(30, min(3600, int(os.getenv("AGENT_RUNTIME_LEASE_SECONDS", "300"))))
    poll_seconds = max(1, min(60, int(os.getenv("AGENT_RUNTIME_POLL_SECONDS", "5"))))
    with httpx.Client(timeout=30, follow_redirects=False) as api:
        while True:
            try:
                found = execute_one(
                    api, api_base, api_key, worker_id, executor_url, executor_key,
                    executor_path, lease_seconds,
                )
                if not found:
                    time.sleep(poll_seconds)
            except KeyboardInterrupt:
                return
            except httpx.HTTPError as exc:
                print(json.dumps({"level": "error", "error": type(exc).__name__}), flush=True)
                time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
