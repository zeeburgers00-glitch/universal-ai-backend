"""Routes for data backup / restore: `/v1/data/*`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .security import require_api_key
from . import backup

router = APIRouter(prefix="/v1/data", tags=["data"], dependencies=[Depends(require_api_key)])


class BackupRequest(BaseModel):
    include_media: bool = Field(default=False, description="Also archive video/audio outputs")
    label: str | None = Field(default=None, max_length=40)


class RestoreRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    snapshot_first: bool = Field(default=True, description="Backup current state before overwriting")


@router.get("/manifest")
def data_manifest() -> dict[str, Any]:
    """What is in the data directory right now."""

    return backup.manifest()


@router.post("/backup")
def data_backup(request: BackupRequest | None = None) -> dict[str, Any]:
    request = request or BackupRequest()
    try:
        return backup.create_backup(include_media=request.include_media, label=request.label)
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/backups")
def data_backups() -> dict[str, Any]:
    return backup.list_backups()


@router.post("/restore")
def data_restore(request: RestoreRequest) -> dict[str, Any]:
    try:
        return backup.restore_backup(request.name, snapshot_first=request.snapshot_first)
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/verify")
def data_verify(name: str) -> dict[str, Any]:
    try:
        return backup.verify_backup(name)
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/download")
def data_download(name: str) -> FileResponse:
    try:
        path = backup.backup_path(name)
    except backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FileResponse(path, media_type="application/gzip", filename=path.name)
