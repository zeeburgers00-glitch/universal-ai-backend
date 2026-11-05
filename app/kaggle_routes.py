"""HTTP routes for Kaggle batch jobs (`/v1/kaggle/*`).

These submit notebooks through the Kaggle API. They are batch, not a live service — the
status payload says so on every response that could be mistaken for one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import kaggle_runner
from .security import require_api_key

router = APIRouter(prefix="/v1/kaggle", tags=["kaggle"], dependencies=[Depends(require_api_key)])


class JobRequest(BaseModel):
    kind: str = Field(description="toolbelt | transcribe | video | assistant")
    params: dict[str, Any] = Field(default_factory=dict)
    dataset_sources: list[str] = Field(default_factory=list,
                                       description="e.g. ['ali/my-video-dataset']")
    enable_gpu: bool | None = None
    private: bool = True


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, kaggle_runner.KaggleUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/status")
def status() -> dict[str, Any]:
    return kaggle_runner.status()


@router.get("/templates")
def templates() -> dict[str, Any]:
    return {"templates": [
        {"kind": kind, **spec} for kind, spec in kaggle_runner.TEMPLATES.items()
    ]}


@router.get("/templates/{kind}/estimate")
def estimate(kind: str) -> dict[str, Any]:
    try:
        return kaggle_runner.estimate(kind)
    except kaggle_runner.KaggleError as exc:
        raise _fail(exc) from exc


@router.post("/jobs")
def submit(body: JobRequest) -> dict[str, Any]:
    try:
        return kaggle_runner.submit(body.kind, body.params,
                                    dataset_sources=body.dataset_sources,
                                    enable_gpu=body.enable_gpu, private=body.private)
    except (kaggle_runner.KaggleError, kaggle_runner.KaggleUnavailable) as exc:
        raise _fail(exc) from exc


@router.get("/jobs")
def list_jobs(limit: int = 20) -> dict[str, Any]:
    return kaggle_runner.list_jobs(limit)


@router.get("/jobs/{job_id}")
def job(job_id: int) -> dict[str, Any]:
    jobs = {row["id"]: row for row in kaggle_runner.list_jobs(100)["jobs"]}
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"no job with id {job_id}")
    return jobs[job_id]


@router.post("/jobs/{job_id}/refresh")
def refresh(job_id: int) -> dict[str, Any]:
    try:
        return kaggle_runner.refresh(job_id)
    except kaggle_runner.KaggleError as exc:
        raise _fail(exc) from exc


@router.post("/jobs/{job_id}/output")
def output(job_id: int) -> dict[str, Any]:
    try:
        return kaggle_runner.fetch_output(job_id)
    except kaggle_runner.KaggleError as exc:
        raise _fail(exc) from exc
