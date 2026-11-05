"""HTTP routes for the skill catalogue (`/v1/skills/*`).

Listing and search are cheap; running a skill always reports which engine ran and how long
it took, or refuses with `unavailable: ...` naming the missing dependency.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import skill_runners, skills
from .security import require_api_key

router = APIRouter(prefix="/v1/skills", tags=["skills"], dependencies=[Depends(require_api_key)])


class RunRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict,
                                description="Skill arguments; see GET /v1/skills/{id} for inputs")


@router.get("")
def list_skills(
    category: str | None = Query(default=None, max_length=40),
    subcategory: str | None = Query(default=None, max_length=60),
    source: str | None = Query(default=None, pattern="^(native|external)$"),
    level: str | None = Query(default=None, pattern="^(basic|intermediate|advanced)$"),
    available: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_external: bool = Query(default=True),
) -> dict[str, Any]:
    return skills.list_skills(category=category, subcategory=subcategory, source=source,
                              level=level, available=available, limit=limit, offset=offset,
                              include_external=include_external)


@router.get("/stats")
def stats() -> dict[str, Any]:
    return skills.stats()


@router.get("/categories")
def categories() -> dict[str, Any]:
    return skills.categories()


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=200),
           limit: int = Query(default=10, ge=1, le=50),
           include_external: bool = Query(default=True)) -> dict[str, Any]:
    return skills.search(q, limit=limit, include_external=include_external)


@router.post("/refresh")
def refresh() -> dict[str, Any]:
    return skills.refresh()


@router.get("/{skill_id}")
def get_skill(skill_id: str) -> dict[str, Any]:
    try:
        return skills.get(skill_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip('"')) from exc


@router.post("/{skill_id}/run")
def run_skill(skill_id: str, body: RunRequest) -> dict[str, Any]:
    try:
        return skills.run(skill_id, body.args)
    except skill_runners.SkillUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip('"')) from exc
    except skill_runners.SkillInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
