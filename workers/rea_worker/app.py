from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/5")

try:
    from celery import Celery  # type: ignore[import-not-found]

    celery_app: Any = Celery(
        "rea_worker",
        broker=REDIS_URL,
        backend=REDIS_URL,
        include=["rea_worker.tasks"],
    )
    celery_app.conf.update(
        task_track_started=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=86400,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )
except ImportError:  # pragma: no cover - lightweight control-plane test envs without Celery
    class _UnavailableCelery:
        def task(self, *args: Any, **kwargs: Any):
            def _decorator(fn: Any) -> Any:
                return fn
            return _decorator

        def send_task(self, *args: Any, **kwargs: Any) -> Any:
            raise HTTPException(status_code=503, detail="Celery broker runtime is not installed in this environment")

        def AsyncResult(self, task_id: str) -> Any:
            raise HTTPException(status_code=503, detail="Celery broker runtime is not installed in this environment")

    celery_app = _UnavailableCelery()


ALLOWED_OPERATIONS = (
    "capabilities",
    "doctor",
    "inspect-desktop-application",
    "analyze-javascript-application",
    "inspect-model-artifact",
    "inspect-gpu-code-objects",
    "inspect-python-pyc",
    "inspect-sqlite-database",
    "inspect-pe-imports",
    "inspect-pe-certificates",
    "inspect-elf-notes",
    "inspect-go-binary",
    "inspect-rust-binary",
    "inspect-wasm-artifact",
)

TARGETLESS_OPERATIONS = {"capabilities", "doctor"}

app = FastAPI(title="Universal AI REA Inspection Worker", version="0.1.0")


def require_worker_key(authorization: str | None = Header(default=None)) -> bool:
    expected = os.getenv("REA_WORKER_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="REA_WORKER_API_KEY is not configured")
    received = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not received or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    return True


def resolve_safe_target(relative_path: str) -> str:
    workspace_root = Path(os.getenv("REA_ALLOWED_WORKSPACE_ROOT", "/workspace/targets")).resolve()
    cleaned = relative_path.strip().lstrip("/\\")
    if not cleaned or ".." in Path(cleaned).parts:
        raise HTTPException(status_code=400, detail="target_path must be a relative path inside REA_ALLOWED_WORKSPACE_ROOT")
    candidate = (workspace_root / cleaned).resolve()
    if candidate != workspace_root and workspace_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="target_path escapes REA_ALLOWED_WORKSPACE_ROOT")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="Target artifact or directory not found in worker workspace")
    return str(candidate)


class ReaInspectJob(BaseModel):
    task_id: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    operation: Literal[
        "capabilities",
        "doctor",
        "inspect-desktop-application",
        "analyze-javascript-application",
        "inspect-model-artifact",
        "inspect-gpu-code-objects",
        "inspect-python-pyc",
        "inspect-sqlite-database",
        "inspect-pe-imports",
        "inspect-pe-certificates",
        "inspect-elf-notes",
        "inspect-go-binary",
        "inspect-rust-binary",
        "inspect-wasm-artifact",
    ]
    target_path: str | None = Field(default=None, max_length=400)
    authorized_target_confirmed: bool = False
    user_approved: bool = False
    dry_run: bool = False


@app.get("/health")
def health():
    workspace_root = Path(os.getenv("REA_ALLOWED_WORKSPACE_ROOT", "/workspace/targets")).resolve()
    return {
        "status": "ok",
        "service": "rea-inspection-worker",
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "workspace_exists": workspace_root.exists(),
        "execution_mode": "static_allowlisted_cli_only",
        "note": "Runs allowlisted static REA CLI inspections inside REA_ALLOWED_WORKSPACE_ROOT without shell execution.",
    }


@app.post("/v1/rea/inspect", status_code=202, dependencies=[Depends(require_worker_key)])
def enqueue_rea_inspection(request: ReaInspectJob):
    if not request.authorized_target_confirmed:
        raise HTTPException(
            status_code=400,
            detail="REA inspection requires authorized_target_confirmed=true under upstream DISCLAIMER.md.",
        )
    if not request.user_approved:
        raise HTTPException(
            status_code=409,
            detail="REA worker inspection requires explicit user_approved=true.",
        )
    resolved_target: str | None = None
    if request.operation not in TARGETLESS_OPERATIONS:
        if not request.target_path:
            raise HTTPException(status_code=400, detail=f"target_path is required for {request.operation}")
        resolved_target = resolve_safe_target(request.target_path)

    if request.dry_run:
        return {
            "task_id": request.task_id,
            "status": "dry_run_validated",
            "operation": request.operation,
            "resolved_target_present": resolved_target is not None,
        }

    payload = {
        "task_id": request.task_id,
        "operation": request.operation,
        "resolved_target": resolved_target,
    }
    task = celery_app.send_task("rea_worker.run_inspection", kwargs={"payload": payload}, task_id=request.task_id)
    return {
        "task_id": task.id,
        "status": "queued",
        "operation": request.operation,
        "poll_url": f"/v1/tasks/{task.id}",
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
        data.update({"status": "failed", "error": "REA inspection failed; inspect private worker logs"})
    return data
