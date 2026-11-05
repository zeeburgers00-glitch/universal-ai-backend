"""Routes for the editor's git panel: `/v1/git/*`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import git_tools, governance
from .security import require_api_key

router = APIRouter(prefix="/v1/git", tags=["git"], dependencies=[Depends(require_api_key)])


class CommitRequest(BaseModel):
    message: str = Field(min_length=3, max_length=200)
    paths: list[str] = Field(default_factory=list, max_length=200)
    add_all: bool = False


@router.get("/status")
def git_status() -> dict[str, Any]:
    """Branch, ahead/behind and the working tree, as the editor shows it."""

    try:
        return git_tools.status()
    except git_tools.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/diff")
def git_diff(
    path: str | None = Query(default=None, max_length=300),
    staged: bool = False,
) -> dict[str, Any]:
    try:
        return git_tools.diff(path=path, staged=staged)
    except git_tools.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/log")
def git_log(limit: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
    try:
        return git_tools.log(limit=limit)
    except git_tools.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/commit")
def git_commit(request: CommitRequest) -> dict[str, Any]:
    """Local commit only. Approval-gated when UAI_REQUIRE_APPROVAL=1."""

    try:
        result = git_tools.commit(request.message, paths=request.paths, add_all=request.add_all)
    except git_tools.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    governance.record("git.commit", target=result.get("sha"), detail={"subject": request.message[:120]})
    return result
