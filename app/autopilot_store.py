"""Durable chat run and activity persistence backed by private Supabase tables."""
from __future__ import annotations

import os
from typing import Any

import httpx


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())


def _request(method: str, table: str, *, params: dict[str, str] | None = None, body: Any = None) -> Any:
    if not configured():
        raise RuntimeError("Supabase durable chat storage is not configured")
    base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    with httpx.Client(timeout=12.0) as client:
        response = client.request(method, f"{base}/rest/v1/{table}", params=params, json=body, headers=headers)
        response.raise_for_status()
        return response.json() if response.content else None


def create_run(row: dict[str, Any]) -> None:
    _request("POST", "autopilot_runs", body=row)


def save_message(conversation_id: str, run_id: str, role: str, content: str) -> None:
    _request("POST", "autopilot_messages", body={"conversation_id": conversation_id, "run_id": run_id,
                                                "role": role, "content": content[:30000]})


def add_event(run_id: str, stage: str, message: str, status: str = "queued") -> None:
    _request("POST", "autopilot_events", body={"run_id": run_id, "event_type": "system",
        "stage": stage, "status": status, "message": message, "payload": {}})


def get_run(run_id: str) -> dict[str, Any] | None:
    rows = _request("GET", "autopilot_runs", params={"id": f"eq.{run_id}", "select": "*", "limit": "1"})
    return rows[0] if rows else None


def get_events(run_id: str) -> list[dict[str, Any]]:
    return _request("GET", "autopilot_events", params={"run_id": f"eq.{run_id}",
        "select": "id,stage,agent_id,status,message,payload,created_at", "order": "id.asc", "limit": "500"}) or []
