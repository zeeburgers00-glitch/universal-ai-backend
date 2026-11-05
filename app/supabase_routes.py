"""HTTP routes for the Supabase connection (`/v1/supabase/*`).

Read-only checks plus two explicit sync directions. No endpoint accepts a key in the body:
keys come from the environment or the vault, never from a request.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from . import supabase_db
from .security import require_api_key

router = APIRouter(prefix="/v1/supabase", tags=["supabase"], dependencies=[Depends(require_api_key)])


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, supabase_db.SupabaseUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/status")
def status() -> dict[str, Any]:
    return supabase_db.status()


@router.get("/ping")
def ping() -> dict[str, Any]:
    try:
        return supabase_db.ping()
    except supabase_db.SupabaseUnavailable as exc:
        raise _fail(exc) from exc


@router.get("/schema")
def schema() -> dict[str, Any]:
    try:
        return supabase_db.schema_report()
    except supabase_db.SupabaseUnavailable as exc:
        raise _fail(exc) from exc


@router.post("/sync")
def sync(limit: int = 500) -> dict[str, Any]:
    try:
        return supabase_db.push_jarvis(limit)
    except (supabase_db.SupabaseUnavailable, supabase_db.SupabaseError) as exc:
        raise _fail(exc) from exc


@router.post("/pull")
def pull(limit: int = 500) -> dict[str, Any]:
    try:
        return supabase_db.pull_facts(limit)
    except (supabase_db.SupabaseUnavailable, supabase_db.SupabaseError) as exc:
        raise _fail(exc) from exc
