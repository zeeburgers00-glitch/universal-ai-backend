"""Optional Supabase PostgREST persistence store for Universal AI Backend."""
from __future__ import annotations

import os
from typing import Any

import httpx


def supabase_configured() -> bool:
    return bool(
        (os.getenv("SUPABASE_URL") or "").strip()
        and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    )


def _headers() -> dict[str, str]:
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }


def _rest_url(table: str) -> str:
    base = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    return f"{base}/rest/v1/{table}"


async def save_custom_tool(tool: dict[str, Any]) -> bool:
    if not supabase_configured():
        return False
    row = {
        "id": str(tool.get("id") or ""),
        "name": str(tool.get("name") or ""),
        "category": str(tool.get("category") or "custom"),
        "protocol": str(tool.get("protocol") or tool.get("kind") or "rest"),
        "description": str(tool.get("description") or ""),
        "payload": tool,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                _rest_url("uaib_custom_tools"),
                params={"on_conflict": "id"},
                json=row,
                headers=_headers(),
            )
            return resp.status_code < 300
    except httpx.HTTPError:
        return False


async def record_execution_log(job_type: str, target_id: str, status: str, summary: dict[str, Any]) -> bool:
    if not supabase_configured():
        return False
    row = {
        "job_type": job_type[:80],
        "target_id": target_id[:160],
        "status": status[:40],
        "summary": summary,
    }
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                _rest_url("uaib_execution_logs"),
                json=row,
                headers=_headers(),
            )
            return resp.status_code < 300
    except httpx.HTTPError:
        return False
