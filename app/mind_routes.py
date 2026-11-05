"""HTTP routes for the self layer (`/v1/mind/*`).

Everything here reports measured state. `reflect` writes lessons and proposals; it never
edits code, and `decide` records a human's decision rather than applying it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import mind
from .security import require_api_key

router = APIRouter(prefix="/v1/mind", tags=["mind"], dependencies=[Depends(require_api_key)])


class JournalRequest(BaseModel):
    entry: str = Field(min_length=1, max_length=2000)
    mood: str = Field(default="", max_length=40)
    kind: str = Field(default="note", max_length=30)


class LessonRequest(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    source: str = Field(default="manual", max_length=40)
    evidence: str = Field(default="", max_length=300)


class DecideRequest(BaseModel):
    status: str = Field(pattern="^(open|accepted|rejected|done)$")
    note: str = Field(default="", max_length=300)


@router.get("/status")
def mind_status() -> dict[str, Any]:
    return mind.status()


@router.get("/self")
def self_model() -> dict[str, Any]:
    return mind.self_model()


@router.get("/stats")
def stats(window: int = 100) -> dict[str, Any]:
    return mind.stats(window)


@router.post("/reflect")
def reflect(window: int = 60) -> dict[str, Any]:
    return mind.reflect(window)


@router.get("/lessons")
def lessons(limit: int = 50) -> dict[str, Any]:
    return {"lessons": mind.lessons(limit)}


@router.post("/lessons")
def add_lesson(body: LessonRequest) -> dict[str, Any]:
    return mind.add_lesson(body.text, source=body.source, evidence=body.evidence)


@router.get("/proposals")
def proposals(status: str | None = None) -> dict[str, Any]:
    return {"proposals": mind.proposals(status)}


@router.post("/proposals/{proposal_id}/decide")
def decide(proposal_id: int, body: DecideRequest) -> dict[str, Any]:
    try:
        return mind.decide(proposal_id, body.status, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/journal")
def journal(limit: int = 20) -> dict[str, Any]:
    return {"journal": mind.entries(limit)}


@router.post("/journal")
def write_journal(body: JournalRequest) -> dict[str, Any]:
    return mind.journal(body.entry, mood=body.mood, kind=body.kind)
