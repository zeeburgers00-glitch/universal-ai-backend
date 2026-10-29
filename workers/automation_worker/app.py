import os
import re
import secrets
from typing import Any

from celery import Celery
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/4")
celery_app = Celery("automation_worker", broker=REDIS_URL, backend=REDIS_URL, include=["automation_worker.tasks"])
celery_app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json",
                       accept_content=["json"], result_expires=86400, task_acks_late=True,
                       worker_prefetch_multiplier=1)
app = FastAPI(title="Universal AI Workflow Dispatcher", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("AUTOMATION_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="AUTOMATION_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


class WorkflowRun(BaseModel):
    task_id: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    workflow_id: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    workflow: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = False
    execution_mode: str = "async"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "workflow-dispatcher",
        "execution_mode": "explicit_action_dispatch",
        "configured_downstream_services": {
            key: bool(os.getenv(key, "").strip())
            for key in [
                "VOICE_WORKER_URL", "MEDIA_WORKER_URL", "YOUTUBE_WORKER_URL",
                "CHANNEL_WORKER_URL", "DESKTOP_AGENT_URL",
            ]
        },
    }


@app.post("/v1/workflows/run", status_code=202, dependencies=[Depends(require_worker_key)])
def run_workflow(request: WorkflowRun):
    workflow = request.workflow
    if workflow.get("id") != request.workflow_id:
        raise HTTPException(status_code=400, detail="Workflow ID does not match the registered workflow definition")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or len(steps) > 30:
        raise HTTPException(status_code=400, detail="Workflow must have at most 30 defined steps")
    if workflow.get("requires_human_approval") and not request.user_approved:
        raise HTTPException(status_code=409, detail="This workflow requires explicit human approval")
    action_list = request.inputs.get("actions", [])
    if not isinstance(action_list, list) or len(action_list) > 20:
        raise HTTPException(status_code=400, detail="inputs.actions must be a list with at most 20 explicit actions")
    if action_list and not request.dry_run and not request.user_approved:
        raise HTTPException(status_code=409, detail="Dispatching workflow actions requires explicit user_approved=true")
    task = celery_app.send_task("automation_worker.dispatch_workflow", kwargs={"payload": request.model_dump()}, task_id=request.task_id)
    return {
        "task_id": task.id,
        "status": "queued",
        "workflow_id": request.workflow_id,
        "dry_run": request.dry_run,
        "actions_requested": len(action_list),
        "poll_url": f"/v1/tasks/{task.id}",
        "note": "The workflow manifest is a template. To dispatch real steps, provide explicit typed inputs.actions and approve the exact external actions.",
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
        data.update({"status": "failed", "error": "Workflow dispatch failed; inspect private worker logs"})
    elif result.state == "PROGRESS":
        data["progress"] = result.info if isinstance(result.info, dict) else {}
    return data
