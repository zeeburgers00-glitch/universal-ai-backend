"""Persistent runtime secret vault backed by Supabase PostgREST (`uaib_runtime_secrets`).

Allows model-provider API keys, worker credentials, and publishing-channel tokens
to be configured dynamically from the UI without exposing any secret values in
responses or logs.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")

_MEMORY_SECRETS: dict[str, dict[str, Any]] = {}
_LAST_SYNC_TS: float = 0.0
_CACHE_TTL_SECONDS: float = 8.0


def _supabase_creds() -> tuple[str, str]:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return url, key


def vault_persistence_ready() -> bool:
    url, key = _supabase_creds()
    return bool(url and key)


def invalidate_vault_cache() -> None:
    global _LAST_SYNC_TS
    _LAST_SYNC_TS = 0.0


def mask_secret(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 6:
        return "••••••"
    return f"••••••{cleaned[-4:]}"


def _sync_from_supabase_if_stale(force: bool = False) -> None:
    global _LAST_SYNC_TS
    now = time.monotonic()
    if not force and _LAST_SYNC_TS > 0 and (now - _LAST_SYNC_TS) < _CACHE_TTL_SECONDS:
        return
    url, key = _supabase_creds()
    if not (url and key):
        _LAST_SYNC_TS = now
        return
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{url}/rest/v1/uaib_runtime_secrets",
                params={"select": "env_name,secret_value,category,target_id,is_custom,updated_at"},
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                },
            )
            if resp.status_code < 300:
                rows = resp.json()
                if isinstance(rows, list):
                    fresh: dict[str, dict[str, Any]] = {}
                    for row in rows:
                        if isinstance(row, dict) and row.get("env_name") and row.get("secret_value"):
                            fresh[str(row["env_name"])] = {
                                "value": str(row["secret_value"]),
                                "category": str(row.get("category") or "general"),
                                "target_id": str(row.get("target_id") or ""),
                                "is_custom": bool(row.get("is_custom", True)),
                                "updated_at": row.get("updated_at"),
                            }
                    _MEMORY_SECRETS.update(fresh)
    except httpx.HTTPError:
        pass
    finally:
        _LAST_SYNC_TS = now


def get_secret(env_name: str) -> str:
    """Return effective secret from OS env first, then runtime vault."""
    direct = os.getenv(env_name, "").strip()
    if direct:
        return direct
    _sync_from_supabase_if_stale()
    entry = _MEMORY_SECRETS.get(env_name)
    if entry and entry.get("value"):
        return str(entry["value"]).strip()
    return ""


def get_secret_source(env_name: str) -> str:
    """Return 'env', 'vault', or 'none' without exposing secret value."""
    if os.getenv(env_name, "").strip():
        return "env"
    _sync_from_supabase_if_stale()
    entry = _MEMORY_SECRETS.get(env_name)
    if entry and entry.get("value"):
        return "vault"
    return "none"


def has_secret(env_name: str) -> bool:
    return bool(get_secret(env_name))


async def set_runtime_secrets(
    secrets_map: dict[str, str],
    category: str = "general",
    target_id: str = "",
) -> dict[str, Any]:
    global _LAST_SYNC_TS
    if not secrets_map:
        raise ValueError("No secrets provided")

    rows_to_upsert: list[dict[str, Any]] = []
    saved_keys: list[dict[str, str]] = []
    safe_cat = (category or "general").strip()[:40]
    safe_target = (target_id or "").strip()[:120]

    for raw_name, raw_val in secrets_map.items():
        name = str(raw_name or "").strip().upper()
        if not ENV_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {raw_name!r}")
        val = str(raw_val or "").strip()
        if not val:
            continue
        _MEMORY_SECRETS[name] = {
            "value": val,
            "category": safe_cat,
            "target_id": safe_target,
            "is_custom": True,
        }
        rows_to_upsert.append(
            {
                "env_name": name,
                "secret_value": val,
                "category": safe_cat,
                "target_id": safe_target,
                "is_custom": True,
            }
        )
        saved_keys.append({"env_name": name, "masked": mask_secret(val)})

    persisted = False
    url, key = _supabase_creds()
    if url and key and rows_to_upsert:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{url}/rest/v1/uaib_runtime_secrets",
                    params={"on_conflict": "env_name"},
                    json=rows_to_upsert,
                    headers={
                        "apikey": key,
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal,resolution=merge-duplicates",
                    },
                )
                persisted = resp.status_code < 300
        except httpx.HTTPError:
            persisted = False
    _LAST_SYNC_TS = time.monotonic()
    return {
        "status": "saved",
        "saved_count": len(saved_keys),
        "persisted_to_supabase": persisted,
        "keys": saved_keys,
    }


async def delete_runtime_secret(env_name: str) -> dict[str, Any]:
    global _LAST_SYNC_TS
    name = env_name.strip().upper()
    if not ENV_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid environment variable name: {env_name!r}")
    _MEMORY_SECRETS.pop(name, None)
    deleted_remote = False
    url, key = _supabase_creds()
    if url and key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.delete(
                    f"{url}/rest/v1/uaib_runtime_secrets",
                    params={"env_name": f"eq.{name}"},
                    headers={
                        "apikey": key,
                        "Authorization": f"Bearer {key}",
                    },
                )
                deleted_remote = resp.status_code < 300
        except httpx.HTTPError:
            deleted_remote = False
    _LAST_SYNC_TS = time.monotonic()
    return {"status": "deleted", "env_name": name, "deleted_from_supabase": deleted_remote}


def list_configured_vault_keys() -> list[dict[str, Any]]:
    _sync_from_supabase_if_stale()
    items: list[dict[str, Any]] = []
    for name, meta in sorted(_MEMORY_SECRETS.items()):
        val = str(meta.get("value") or "")
        if not val:
            continue
        items.append(
            {
                "env_name": name,
                "masked": mask_secret(val),
                "category": meta.get("category", "general"),
                "target_id": meta.get("target_id", ""),
                "source": "env" if os.getenv(name, "").strip() else "vault",
            }
        )
    return items
