"""HTTP routes for the free tool belt (`/v1/belt/*`).

Not `/v1/tools`: that prefix already belongs to the GitHub tool catalogue in
`app/main.py`. Two registries, two prefixes, no shadowing.

Every response states what is really true right now: which tools are available on this
machine, which are missing and which install command fixes them, and what actually ran.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import anthropic, toolbelt
from .security import require_api_key

router = APIRouter(prefix="/v1/belt", tags=["toolbelt"], dependencies=[Depends(require_api_key)])


class RunRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict,
                                description="Tool arguments, see GET /v1/belt/{tool_id}")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, toolbelt.ToolUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
def list_tools(
    category: str | None = Query(default=None, max_length=40),
    available: bool = Query(default=False, description="Only tools that work right now"),
    runnable: bool = Query(default=False, description="Only tools with a runner wired"),
) -> dict[str, Any]:
    return toolbelt.list_tools(category=category, only_available=available, runnable_only=runnable)


@router.get("/status")
def tool_status() -> dict[str, Any]:
    return {"belt": toolbelt.summary(), "claude": anthropic.status()}


@router.get("/search")
def search_tools(q: str = Query(min_length=1, max_length=300), limit: int = Query(default=8, ge=1, le=25)) -> dict[str, Any]:
    return toolbelt.search(q, limit=limit)


@router.get("/claude-schema")
def claude_schema(only_available: bool = True) -> dict[str, Any]:
    definitions = toolbelt.claude_tools(only_available=only_available)
    return {"count": len(definitions), "tools": definitions}


@router.post("/refresh")
def refresh() -> dict[str, Any]:
    return toolbelt.refresh()


@router.get("/{tool_id}")
def get_tool(tool_id: str) -> dict[str, Any]:
    try:
        tool = toolbelt.get(tool_id)
    except toolbelt.ToolError as exc:
        raise _fail(exc) from exc
    ok, detail = toolbelt.availability(tool_id)
    return {**tool.to_dict(ok, detail), "catalogue_entry": {
        "install": tool.install, "test": tool.test, "needs": list(tool.needs)}}


@router.post("/{tool_id}/run")
def run_tool(tool_id: str, body: RunRequest) -> dict[str, Any]:
    try:
        return toolbelt.run(tool_id, body.args)
    except (toolbelt.ToolError, toolbelt.ToolUnavailable) as exc:
        raise _fail(exc) from exc


@router.post("/{tool_id}/verify")
def verify_tool(tool_id: str) -> dict[str, Any]:
    try:
        return toolbelt.verify(tool_id)
    except (toolbelt.ToolError, toolbelt.ToolUnavailable) as exc:
        raise _fail(exc) from exc
