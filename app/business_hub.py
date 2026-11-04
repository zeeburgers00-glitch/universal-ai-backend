from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import require_api_key
from .task_gateway import post_worker

ROOT = Path(__file__).resolve().parent.parent
router = APIRouter(prefix="/v1/business", tags=["plugins-and-monetization"])


def _catalog(name: str) -> dict[str, Any]:
    try:
        return json.loads((ROOT / "catalog" / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"{name} catalog unavailable") from exc


class PluginAction(BaseModel):
    action: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = True


class TempInboxRequest(BaseModel):
    purpose: Literal["qa_testing", "owned_domain_staging"] = "qa_testing"
    project_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    ttl_minutes: int = Field(default=30, ge=5, le=1440)


class TempInboxReadRequest(BaseModel):
    inbox_id: str = Field(min_length=8, max_length=200)


class RevenueReportRequest(BaseModel):
    stream: Literal["adsense", "affiliate", "sponsorships", "services", "saas"]
    period_start: str = Field(min_length=10, max_length=30)
    period_end: str = Field(min_length=10, max_length=30)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    amount: float = Field(ge=0, le=100000000)
    report_reference: str = Field(min_length=4, max_length=240)
    verification: Literal["provider_statement", "verified_payment", "estimate"] = "estimate"


@router.get("/plugins")
def list_business_plugins():
    data = _catalog("business_plugins.json")
    return {"total": len(data["plugins"]), "policy": data["policy"], "items": data["plugins"],
            "note": "Catalog entries are not connected integrations. Connect and configure each provider before use."}


@router.post("/plugins/{plugin_id}/actions", dependencies=[Depends(require_api_key)])
async def run_plugin_action(plugin_id: str, request: PluginAction):
    data = _catalog("business_plugins.json")
    plugin = next((p for p in data["plugins"] if p["id"] == plugin_id), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    if plugin["status"] != "connected":
        raise HTTPException(status_code=409, detail="Plugin is not connected. Complete provider authorization and server-side configuration first.")
    if request.action in plugin.get("approval_required", []) and not request.user_approved:
        raise HTTPException(status_code=409, detail="This plugin action requires explicit user approval.")
    payload = {"plugin_id": plugin_id, "plugin": plugin, "action": request.action,
               "inputs": request.inputs, "user_approved": request.user_approved,
               "dry_run": request.dry_run}
    status, content_type, body = await post_worker("plugins", "/v1/plugins/execute", payload, timeout_seconds=45)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="Plugin worker returned a non-JSON response")
    try:
        result = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Plugin worker returned invalid JSON") from exc
    return {"status_code": status, "result": result}


@router.post("/testing/inboxes", dependencies=[Depends(require_api_key)])
async def create_testing_inbox(request: TempInboxRequest):
    if not os.getenv("MAIL_WORKER_URL") or not os.getenv("MAIL_WORKER_API_KEY"):
        raise HTTPException(status_code=503, detail="Temporary test inbox is not configured. Set MAIL_WORKER_URL and MAIL_WORKER_API_KEY.")
    payload = {"purpose": request.purpose, "project_id": request.project_id, "ttl_minutes": request.ttl_minutes,
               "allow_account_verification_bypass": False, "allow_bulk_signup": False}
    status, content_type, body = await post_worker("mail", "/v1/testing/inboxes", payload, timeout_seconds=20)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="Mail worker returned a non-JSON response")
    try:
        result = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Mail worker returned invalid JSON") from exc
    return {"status_code": status, "inbox": result,
            "notice": "Testing inboxes are for QA on systems you own or are authorized to test, not mass signups or bypassing third-party verification."}


@router.post("/testing/inboxes/read", dependencies=[Depends(require_api_key)])
async def read_testing_inbox(request: TempInboxReadRequest):
    if not os.getenv("MAIL_WORKER_URL") or not os.getenv("MAIL_WORKER_API_KEY"):
        raise HTTPException(status_code=503, detail="Temporary test inbox is not configured.")
    status, content_type, body = await post_worker("mail", "/v1/testing/inboxes/read",
        {"inbox_id": request.inbox_id}, timeout_seconds=20)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="Mail worker returned a non-JSON response")
    try:
        result = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Mail worker returned invalid JSON") from exc
    return {"status_code": status, "messages": result}


@router.get("/monetization")
def monetization_options():
    data = _catalog("monetization_streams.json")
    return {"policies": data["policies"], "streams": data["streams"]}


@router.post("/monetization/reports", dependencies=[Depends(require_api_key)])
async def record_revenue_report(request: RevenueReportRequest):
    payload = request.model_dump()
    payload["recognized_as_realized_revenue"] = request.verification in {"provider_statement", "verified_payment"}
    payload["source_reference"] = request.report_reference
    status, content_type, body = await post_worker("finance", "/v1/revenue/reports", payload, timeout_seconds=30)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="Finance worker returned a non-JSON response")
    try:
        result = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Finance worker returned invalid JSON") from exc
    return {"status_code": status, "result": result,
            "recognized_as_realized_revenue": payload["recognized_as_realized_revenue"]}


@router.get("/monetization/policy")
def monetization_policy():
    return _catalog("monetization_streams.json")["policies"]
