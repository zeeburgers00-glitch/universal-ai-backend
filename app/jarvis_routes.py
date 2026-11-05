"""Routes for the JARVIS layer: `/v1/jarvis/*`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import jarvis
from .security import require_api_key

router = APIRouter(prefix="/v1/jarvis", tags=["jarvis"], dependencies=[Depends(require_api_key)])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session: str = Field(default="default", max_length=60)
    dry_run: bool = Field(default=False, description="Plan only: do not run tools")


class RememberRequest(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2000)


class PlanRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=1000)


@router.post("/chat")
def jarvis_chat(request: ChatRequest) -> dict[str, Any]:
    """One turn: memory, tools, and an honest answer."""

    try:
        return jarvis.chat(request.message, session=request.session, dry_run=request.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/plan")
def jarvis_plan(request: PlanRequest) -> dict[str, Any]:
    """What would run for this goal — nothing is executed."""

    return jarvis.plan(request.goal)


@router.get("/memory")
def jarvis_memory(
    q: str | None = Query(default=None, max_length=200, description="Optional relevance search"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    if q:
        return {"query": q, "results": jarvis.recall(q, limit=min(limit, 20))}
    return {"count": len(jarvis.facts(limit)), "facts": jarvis.facts(limit=limit)}


@router.post("/memory")
def jarvis_remember(request: RememberRequest) -> dict[str, Any]:
    """Store a fact explicitly (the chat also learns from plain sentences)."""

    try:
        return jarvis.remember(request.key, request.value, source="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/memory/{key}")
def jarvis_forget(key: str) -> dict[str, Any]:
    return jarvis.forget(key)


@router.get("/history")
def jarvis_history(
    session: str = Query(default="default", max_length=60),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    turns = jarvis.history(session=session, limit=limit)
    return {"session": session, "count": len(turns), "turns": turns}


@router.get("/status")
def jarvis_status() -> dict[str, Any]:
    """Memory size, whether a model is configured, how many agents are wired."""

    return jarvis.status()
