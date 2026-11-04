from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import require_api_key
from .task_gateway import post_worker

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "catalog" / "earning_empire_fleet.json"
router = APIRouter(prefix="/v1/earning", tags=["earning-empire"])


def _manifest() -> dict[str, Any]:
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Earning fleet manifest is unavailable") from exc
    if data.get("agent_slots") != len(data.get("agents", [])):
        raise HTTPException(status_code=500, detail="Earning fleet manifest slot count is inconsistent")
    return data


class EarningRunRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=12000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = True
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/fleet")
def earning_fleet():
    data = _manifest()
    return {
        "name": data["name"],
        "version": data["version"],
        "agent_slots": data["agent_slots"],
        "department_count": data["department_count"],
        "default_max_parallel": data["default_max_parallel"],
        "monthly_budget_usd": data["monthly_budget_usd"],
        "execution_policy": data["execution_policy"],
        "departments": [
            {"id": d["id"], "name": d["name"], "capacity": d["capacity"], "mission": d["mission"]}
            for d in data["departments"]
        ],
        "note": "Blueprint capacity is not a count of running agents or generated income."
    }


@router.get("/departments")
def earning_departments():
    data = _manifest()
    return {"total": len(data["departments"]), "items": data["departments"]}


@router.get("/agents")
def earning_agents(department: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0):
    data = _manifest()
    items = data["agents"]
    if department:
        items = [x for x in items if x["department_id"] == department]
    if q:
        needle = q.casefold()
        items = [x for x in items if needle in json.dumps(x, ensure_ascii=False).casefold()]
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    return {"total": len(items), "limit": safe_limit, "offset": safe_offset,
            "items": items[safe_offset:safe_offset + safe_limit]}


@router.get("/workflows")
def earning_workflows():
    items = _manifest()["workflows"]
    return {"total": len(items), "items": items}


@router.post("/plan", dependencies=[Depends(require_api_key)])
async def plan_earning_work(request: EarningRunRequest):
    data = _manifest()
    max_parallel = min(max(int(os.getenv("EARNING_MAX_PARALLEL_AGENTS", str(data["default_max_parallel"]))), 1), 20)
    agent = {
        "id": "earning-chief-orchestrator",
        "name": "Earning Empire Chief Orchestrator",
        "description": "Classify a business objective, select specialist departments, produce a cost-aware plan and list approval gates. Do not claim revenue or execute external side effects.",
        "capabilities": ["business_routing", "work_breakdown", "budget_awareness", "approval_planning"],
        "risk_level": "medium",
        "permissions": ["read_assigned_inputs", "draft_outputs", "record_task_events"],
        "requires_human_approval": True,
    }
    payload = {
        "task_id": request.idempotency_key or __import__("uuid").uuid4().hex,
        "agent_id": agent["id"],
        "agent": agent,
        "objective": request.objective,
        "inputs": {
            **request.inputs,
            "available_departments": [{"id": d["id"], "name": d["name"], "skills": d["skills"]} for d in data["departments"]],
            "monthly_budget_usd": data["monthly_budget_usd"],
            "max_parallel_agents": max_parallel,
            "planning_only": True,
            "do_not_execute_external_actions": True,
        },
        "user_approved": False,
        "dry_run": True,
        "execution_mode": "async",
    }
    status_code, content_type, body = await post_worker("agents", "/v1/agents/run", payload, timeout_seconds=45)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="Agent worker returned a non-JSON planning response")
    try:
        result = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Agent worker returned invalid JSON") from exc
    return {"status_code": status_code, "plan": result, "fleet_slots_available": data["agent_slots"],
            "max_parallel_agents": max_parallel, "approval_policy": "External actions remain blocked until separately approved."}


@router.post("/agents/{agent_id}/run", dependencies=[Depends(require_api_key)])
async def run_earning_agent(agent_id: str, request: EarningRunRequest):
    data = _manifest()
    agent = next((x for x in data["agents"] if x["id"] == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Earning agent blueprint not found")
    if agent.get("risk_level") == "high" and not request.user_approved and not request.dry_run:
        raise HTTPException(status_code=409, detail="High-risk workflow requires explicit approval; use dry_run=true to preview.")
    task_id = request.idempotency_key or __import__("uuid").uuid4().hex
    payload = {
        "task_id": task_id, "agent_id": agent_id, "agent": agent,
        "objective": request.objective, "inputs": request.inputs,
        "user_approved": request.user_approved, "dry_run": request.dry_run,
        "execution_mode": "async",
    }
    status_code, content_type, body = await post_worker("agents", "/v1/agents/run", payload, timeout_seconds=45)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="Agent worker returned a non-JSON response")
    try:
        result = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Agent worker returned invalid JSON") from exc
    return {"status_code": status_code, "result": result, "agent": {"id": agent["id"], "name": agent["name"]}}
