"""Routes for the SQLite job queue: `/v1/jobs/*`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .security import require_api_key
from . import jobs

router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_key)])


class SubmitRequest(BaseModel):
    kind: str = Field(min_length=2, max_length=80, description="Handler name, e.g. video.cut_silence")
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/kinds")
def job_kinds() -> dict[str, Any]:
    """Which job types this build can run, plus queue stats."""

    return {"total": len(jobs.HANDLERS), "kinds": sorted(jobs.HANDLERS), "queue": jobs.stats()}


@router.post("")
def job_submit(request: SubmitRequest) -> dict[str, Any]:
    """Queue a job. Returns immediately; poll `GET /v1/jobs/{id}` for progress."""

    try:
        return jobs.submit(request.kind, request.payload)
    except jobs.JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def job_list(
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    return jobs.list_jobs(status=status, limit=limit)


@router.get("/{job_id}")
def job_get(job_id: str) -> dict[str, Any]:
    try:
        return jobs.get(job_id)
    except jobs.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{job_id}/cancel")
def job_cancel(job_id: str) -> dict[str, Any]:
    try:
        return jobs.cancel(job_id)
    except jobs.JobError as exc:
        message = str(exc)
        raise HTTPException(status_code=404 if "not found" in message else 409, detail=message)


@router.post("/run-once")
def job_run_once() -> dict[str, Any]:
    """Drain exactly one job synchronously — handy in tests and cron ticks."""

    worked = jobs.run_once()
    return {"worked": worked, **jobs.stats()}
