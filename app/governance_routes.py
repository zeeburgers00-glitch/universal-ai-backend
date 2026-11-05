"""Routes for scopes, audit log and approval gates: `/v1/governance/*` + `/v1/tools/*`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import governance, tool_search
from .security import require_api_key

router = APIRouter(tags=["governance"])


class ApprovalRequest(BaseModel):
    path: str = Field(min_length=3, max_length=120, description="Operation to approve, e.g. /v1/data/restore")
    reason: str = Field(min_length=3, max_length=200)


@router.get("/v1/governance/whoami")
def who_am_i(
    _key: bool = Depends(require_api_key),
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Which scopes this key has and whether approvals are switched on."""

    return governance.whoami(x_api_key)


@router.get("/v1/governance/audit")
def audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    action: str | None = Query(default=None, max_length=60),
    _key: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """Append-only log of every write and admin action."""

    return governance.read_log(limit=limit, action=action)


@router.get("/v1/governance/approvals")
def list_approvals(_key: bool = Depends(require_api_key)) -> dict[str, Any]:
    return governance.approvals()


@router.post("/v1/governance/approvals")
def create_approval(
    request: ApprovalRequest,
    _key: bool = Depends(require_api_key),
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Issue a single-use token for one dangerous operation."""

    if not any(request.path.startswith(prefix) for prefix in governance.DANGEROUS):
        raise HTTPException(status_code=400, detail=f"path must be one of {list(governance.DANGEROUS)}")
    return governance.grant(request.path, request.reason, key=x_api_key)


@router.get("/v1/tools/search")
def tools_search(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    _key: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """BM25 search over the 205-repo catalog: 'kaun sa tool ye kaam karega'."""

    return tool_search.search_tools(q, limit=limit)


@router.get("/v1/tools/routes")
def routes_search(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    _key: bool = Depends(require_api_key),
) -> dict[str, Any]:
    """BM25 search over this API's own routes."""

    from .main import app  # local import avoids a cycle at module load

    return tool_search.search_routes(q, app.openapi(), limit=limit)


@router.get("/v1/tools/capabilities")
def capabilities(_key: bool = Depends(require_api_key)) -> dict[str, Any]:
    return tool_search.capabilities()
