"""Routes for the runnable agent runtime: `/v1/agents/runtime/*`.

Route order matters here: FastAPI matches in registration order, so every static path
(``/categories``, ``/blueprints``, ``/crew/run``, ``/runs/recent``) is declared *before*
``/{agent_id}`` — otherwise ``crew`` is read as an agent id and the call 404s.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import agents, governance, jobs
from .security import require_api_key

router = APIRouter(prefix="/v1/agents/runtime", tags=["agents"], dependencies=[Depends(require_api_key)])


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict, description="Agent-specific payload")


class SubmitRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int | None = Field(default=None, ge=1, le=10)


class CrewRequest(BaseModel):
    agents: list[str] = Field(min_length=1, max_length=10)
    input: dict[str, Any] = Field(default_factory=dict)


# --- static routes first ------------------------------------------------------

@router.get("")
def list_runtime_agents(
    category: str | None = Query(default=None, max_length=30),
    engine: str | None = Query(default=None, pattern="^(rules|ffmpeg|index|model)$"),
) -> dict[str, Any]:
    """Every agent that can actually run in this process."""

    body = agents.list_agents(category=category, engine=engine)
    body["fingerprint"] = agents.fingerprint()
    return body


@router.get("/categories")
def agent_categories() -> dict[str, Any]:
    return {"categories": agents.categories(), "total": len(agents.AGENTS)}


@router.get("/blueprints")
def agent_blueprints() -> dict[str, Any]:
    """The 42 catalog blueprints, with whether each one runs here."""

    return agents.blueprints()


@router.get("/runs/recent")
def recent_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """Agent activity pulled from the audit log (no separate store needed)."""

    log = governance.read_log(limit=limit, action="agent.run")
    return {"count": log["count"], "runs": log["entries"]}


@router.post("/crew/run")
def run_crew(request: CrewRequest) -> dict[str, Any]:
    """Chain agents: each one sees the previous result as `context`."""

    try:
        return agents.crew(request.agents, request.input)
    except agents.AgentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


# --- dynamic routes -----------------------------------------------------------

@router.get("/{agent_id}")
def describe_agent(agent_id: str) -> dict[str, Any]:
    try:
        return agents.describe(agent_id)
    except agents.AgentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/{agent_id}/run")
def run_agent(agent_id: str, request: RunRequest | None = Body(default=None)) -> dict[str, Any]:
    """Run one agent synchronously and return its result."""

    try:
        return agents.run(agent_id, (request.input if request else {}))
    except agents.AgentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/{agent_id}/submit")
def submit_agent(agent_id: str, request: SubmitRequest | None = None) -> dict[str, Any]:
    """Queue an agent run on the durable job queue (for slow or long agents)."""

    body = request or SubmitRequest()
    try:
        agents.describe(agent_id)
    except agents.AgentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    try:
        return jobs.submit(
            "agent.run",
            {"agent": agent_id, "input": body.input},
            max_attempts=body.max_attempts,
        )
    except jobs.JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
