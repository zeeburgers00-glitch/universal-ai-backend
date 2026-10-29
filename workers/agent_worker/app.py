import os
import re
import secrets
from typing import Any

from celery import Celery
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/3")
celery_app = Celery("agent_worker", broker=REDIS_URL, backend=REDIS_URL, include=["agent_worker.tasks"])
celery_app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json",
                       accept_content=["json"], result_expires=86400, task_acks_late=True,
                       worker_prefetch_multiplier=1)
app = FastAPI(title="Universal AI Agent Planner", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("AGENT_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="AGENT_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


class AgentRun(BaseModel):
    task_id: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    agent_id: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    agent: dict[str, Any]
    objective: str = Field(min_length=3, max_length=12000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = True
    execution_mode: str = "plan_only"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "agent-planner",
        "model_configured": bool(
            (os.getenv("AGENT_MODEL_BASE_URL") or os.getenv("AI_BASE_URL") or "").strip()
            and (os.getenv("AGENT_MODEL_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
            and (os.getenv("AGENT_DEFAULT_MODEL") or os.getenv("AI_DEFAULT_MODEL") or "").strip()
        ),
        "execution_mode": "plan_only",
        "note": "The planner does not run shell commands, arbitrary code, or unreviewed side-effectful tools.",
    }


@app.post("/v1/agents/run", status_code=202, dependencies=[Depends(require_worker_key)])
def run_agent(request: AgentRun):
    agent_risk = str(request.agent.get("risk_level", "unknown")).lower()
    if agent_risk == "critical" and not request.user_approved:
        raise HTTPException(status_code=409, detail="Critical-risk agent requests require explicit approval")
    task = celery_app.send_task("agent_worker.plan_agent", kwargs={"payload": request.model_dump()}, task_id=request.task_id)
    return {
        "task_id": task.id,
        "status": "queued",
        "agent_id": request.agent_id,
        "execution_mode": "plan_only",
        "poll_url": f"/v1/tasks/{task.id}",
        "note": "The agent returns a typed action plan. Public posts, messages, file writes, and computer actions must then be separately reviewed and sent to dedicated endpoints.",
    }


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(require_worker_key)])
def task_status(task_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    result = celery_app.AsyncResult(task_id)
    data: dict[str, Any] = {"task_id": task_id, "status": result.state.lower()}
    if result.successful():
        value = result.result if isinstance(result.result, dict) else {}
        data.update({"status": value.get("status", "succeeded"), "result": value})
    elif result.failed():
        data.update({"status": "failed", "error": "Agent planning failed; inspect private worker logs"})
    elif result.state == "PROGRESS":
        data["progress"] = result.info if isinstance(result.info, dict) else {}
    return data
