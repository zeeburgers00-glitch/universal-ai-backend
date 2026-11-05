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
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit

import httpx


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _secure_service_url(name: str) -> str:
    base = _required(name).rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme == "https" and parsed.hostname:
        return base
    local_ok = os.getenv("AGENT_RUNTIME_ALLOW_INSECURE_LOCAL_HTTP", "").lower() == "true"
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"} and local_ok:
        return base
    private_ok = os.getenv("AGENT_RUNTIME_ALLOW_PRIVATE_NETWORK_HTTP", "").lower() == "true"
    private_hosts = {
        host.strip().lower()
        for host in os.getenv("AGENT_RUNTIME_PRIVATE_HTTP_HOSTS", "").split(",")
        if host.strip()
    }
    if parsed.scheme == "http" and parsed.hostname and parsed.hostname.lower() in private_hosts and private_ok:
        return base
    raise RuntimeError(
        f"{name} must use HTTPS; HTTP is allowed only for explicitly allowlisted private hosts or local development."
    )


def _executor_url() -> str:
    return _secure_service_url("AGENT_WORKER_URL")


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
    try:
        lease_until = datetime.fromisoformat(task["lease_until"])
        initial_lease = max(15, int((lease_until - datetime.now(timezone.utc)).total_seconds()))
    except (KeyError, TypeError, ValueError):
        initial_lease = 180
    heartbeat_lease = max(15, min(lease_seconds, initial_lease))
    stop = Event()
    heartbeat = Thread(
        target=_heartbeat_loop,
        args=(api, api_base, api_key, worker_id, task_id, stop, heartbeat_lease),
        daemon=True,
    )
    heartbeat.start()
    try:
        payload = task.get("payload") or {}
        agent = payload.get("agent") or {
            "id": task.get("agent_id") or "general-agent",
            "name": "General Agent",
            "mission": "Produce a bounded, reviewable action plan.",
            "risk_level": task.get("risk_level", "medium"),
        }
        agent_id = task.get("agent_id") or agent.get("id") or "general-agent"
        dispatch = {
            "task_id": task_id,
            "agent": agent,
            "agent_id": agent_id,
            "objective": task["objective"],
            "inputs": {
                **(payload.get("inputs") or {}),
                "runtime_task_id": task_id,
                "workflow_id": task.get("workflow_id"),
                "tool_allowlist": payload.get("tool_allowlist") or [],
                "no_paid_provider_fallback": True,
                "no_secrets_in_prompt": True,
            },
            "user_approved": bool(payload.get("user_approved", False)),
            "dry_run": bool(payload.get("dry_run", True)),
            "execution_mode": "plan_only",
        }
        response = api.post(
            executor_url + executor_path,
            json=dispatch,
            headers={"Authorization": f"Bearer {executor_key}",
                     "X-Worker-Service": "agents", "Content-Type": "application/json"},
            timeout=httpx.Timeout(240, connect=10),
        )
        response.raise_for_status()
        if response.status_code == 202:
            accepted = response.json()
            executor_task_id = str(accepted.get("task_id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", executor_task_id):
                raise RuntimeError("Executor returned HTTP 202 without a valid task_id; cannot confirm completion.")
            status_template = os.getenv(
                "AGENT_RUNTIME_EXECUTOR_STATUS_PATH_TEMPLATE", "/v1/tasks/{task_id}"
            )
            status_path = status_template.replace("{task_id}", executor_task_id)
            if not re.fullmatch(r"/v1/[A-Za-z0-9/._-]{1,150}", status_path) or ".." in status_path:
                raise RuntimeError("AGENT_RUNTIME_EXECUTOR_STATUS_PATH_TEMPLATE is invalid.")
            max_wait = max(30, min(21600, int(os.getenv("AGENT_RUNTIME_EXECUTOR_MAX_WAIT_SECONDS", "3600"))))
            poll_seconds = max(1, min(60, int(os.getenv("AGENT_RUNTIME_EXECUTOR_POLL_SECONDS", "5"))))
            deadline = time.monotonic() + max_wait
            result_data: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                poll = api.get(
                    executor_url + status_path,
                    headers={"Authorization": f"Bearer {executor_key}", "X-Worker-Service": "agents"},
                    timeout=20,
                )
                poll.raise_for_status()
                status_data = poll.json()
                state = str(status_data.get("status") or "").lower()
                if state in {"failed", "revoked", "cancelled"}:
                    raise RuntimeError(f"Agent executor task ended with status={state}.")
                if state in {"plan_created", "succeeded", "success", "completed"}:
                    result_data = status_data.get("result") if isinstance(status_data.get("result"), dict) else status_data
                    break
                time.sleep(poll_seconds)
            if result_data is None:
                raise TimeoutError("Agent executor did not finish before AGENT_RUNTIME_EXECUTOR_MAX_WAIT_SECONDS.")
            result = result_data
        else:
            try:
                result = response.json()
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
    api_base = _secure_service_url("AGENT_RUNTIME_API_URL")
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
