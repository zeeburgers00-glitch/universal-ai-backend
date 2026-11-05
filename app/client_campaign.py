from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl, field_validator

from .security import require_api_key

router = APIRouter(prefix="/v1/campaigns/content-agency", tags=["client-content-campaign"])

LEADS_TABLE = "uaib_client_campaign_leads"
DRAFTS_TABLE = "uaib_client_campaign_drafts"


def _database_configured() -> bool:
    return bool(
        (os.getenv("SUPABASE_URL") or "").strip()
        and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    )


def _supabase_headers() -> dict[str, str]:
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _db_request(
    method: str,
    table: str,
    *,
    params: dict[str, str] | None = None,
    body: Any = None,
    prefer: str | None = None,
) -> Any:
    if not _database_configured():
        raise HTTPException(
            status_code=503,
            detail="Campaign CRM storage is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )

    base_url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not base_url.startswith("https://"):
        raise HTTPException(status_code=503, detail="Supabase URL must use HTTPS.")
    headers = _supabase_headers()
    if prefer:
        headers["Prefer"] = prefer

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
            response = await client.request(
                method,
                f"{base_url}/rest/v1/{table}",
                params=params,
                json=body,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Campaign CRM database request timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Campaign CRM database connection failed.") from exc

    if response.status_code == 404:
        raise HTTPException(
            status_code=503,
            detail="Campaign CRM database schema is missing. Apply the client campaign CRM migration first.",
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Campaign CRM database request failed (HTTP {response.status_code}).",
        )
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Campaign CRM database returned invalid JSON.") from exc


class LeadInput(BaseModel):
    campaign_id: str = Field(default="international-content-agency-2026-11", min_length=3, max_length=80,
                             pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    business_name: str = Field(min_length=2, max_length=180)
    website_url: HttpUrl
    source_url: HttpUrl
    contact_source_url: HttpUrl | None = None
    industry: str = Field(min_length=2, max_length=100)
    city: str = Field(default="", max_length=100)
    country: str = Field(min_length=2, max_length=100)
    public_contact: str = Field(default="", max_length=240)
    contact_method: Literal["business_email", "official_contact_form", "public_phone", "none"] = "none"
    qualification: Literal["A", "B", "C"] = "B"
    lead_status: Literal["research_needed", "qualified"] = "research_needed"
    fit_evidence: str = Field(min_length=10, max_length=1800)
    content_angle: str = Field(min_length=10, max_length=1200)
    verified_on: str = Field(min_length=10, max_length=10)
    notes: str = Field(default="", max_length=1200)

    @field_validator("website_url", "source_url", "contact_source_url")
    @classmethod
    def require_https(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and value.scheme != "https":
            raise ValueError("Only HTTPS URLs are accepted for public source records.")
        return value


class LeadImportRequest(BaseModel):
    leads: list[LeadInput] = Field(min_length=1, max_length=50)


class DraftCreateRequest(BaseModel):
    draft_type: Literal["first_touch", "sample_brief", "pilot_proposal", "retainer_proposal"]
    recipient: str = Field(default="", max_length=240)
    recipient_channel: Literal["business_email", "official_contact_form", "manual_only"] = "manual_only"
    subject: str = Field(default="", max_length=240)
    body: str = Field(min_length=20, max_length=12000)
    sample_concept: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=1200)


class DraftDecisionRequest(BaseModel):
    confirm: bool = False
    note: str = Field(default="", max_length=1200)


@router.get("/status", dependencies=[Depends(require_api_key)])
def campaign_status():
    ready = _database_configured()
    return {
        "campaign_id": "international-content-agency-2026-11",
        "storage": "configured" if ready else "not_configured",
        "monthly_spend_limit_usd": 100,
        "spend_recorded_usd": 0,
        "external_contact_sending_enabled": False,
        "policy": "Research and drafting are allowed. This API has no email/DM/form submission route. Draft approval only records approval; it never sends a message.",
        "note": "The USD 100 ceiling is a campaign policy target, not a payment-provider hard limit.",
    }


@router.post("/leads/import", dependencies=[Depends(require_api_key)])
async def import_leads(request: LeadImportRequest):
    rows = [lead.model_dump(mode="json") for lead in request.leads]
    result = await _db_request(
        "POST",
        LEADS_TABLE,
        params={"on_conflict": "campaign_id,website_url"},
        body=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )
    return {"imported": len(result or []), "items": result or [], "external_actions": "none"}


@router.get("/leads", dependencies=[Depends(require_api_key)])
async def list_leads(
    campaign_id: str = Query(default="international-content-agency-2026-11", min_length=3, max_length=80),
    qualification: Literal["A", "B", "C"] | None = None,
    lead_status: Literal["research_needed", "qualified", "draft_ready", "awaiting_approval",
                         "approved_to_send", "contacted", "replied", "won", "lost", "do_not_contact"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
):
    params = {
        "select": "*",
        "campaign_id": f"eq.{campaign_id}",
        "order": "updated_at.desc",
        "limit": str(limit),
        "offset": str(offset),
    }
    if qualification:
        params["qualification"] = f"eq.{qualification}"
    if lead_status:
        params["lead_status"] = f"eq.{lead_status}"
    rows = await _db_request("GET", LEADS_TABLE, params=params)
    return {"count": len(rows or []), "items": rows or []}


@router.get("/leads/{lead_id}", dependencies=[Depends(require_api_key)])
async def get_lead(lead_id: UUID):
    rows = await _db_request(
        "GET", LEADS_TABLE,
        params={"select": "*", "id": f"eq.{lead_id}", "limit": "1"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Campaign lead not found.")
    return rows[0]


@router.post("/leads/{lead_id}/drafts", dependencies=[Depends(require_api_key)])
async def create_lead_draft(lead_id: UUID, request: DraftCreateRequest):
    lead = await get_lead(lead_id)
    lead_status = lead.get("lead_status")
    if lead_status == "do_not_contact":
        raise HTTPException(status_code=409, detail="This business is marked do_not_contact.")
    row = {
        "lead_id": str(lead_id),
        "campaign_id": lead["campaign_id"],
        "draft_type": request.draft_type,
        "recipient": request.recipient,
        "recipient_channel": request.recipient_channel,
        "subject": request.subject,
        "body": request.body,
        "sample_concept": request.sample_concept,
        "notes": request.notes,
        "approval_status": "awaiting_approval",
    }
    result = await _db_request("POST", DRAFTS_TABLE, body=row)
    if isinstance(result, list):
        result = result[0] if result else {}
    return {
        "draft": result or {},
        "status": "awaiting_approval",
        "sent": False,
        "notice": "Draft saved for review only. No message or form was submitted.",
    }


@router.get("/drafts", dependencies=[Depends(require_api_key)])
async def list_drafts(
    campaign_id: str = Query(default="international-content-agency-2026-11", min_length=3, max_length=80),
    approval_status: Literal["awaiting_approval", "approved_to_send", "rejected"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    params = {
        "select": "*,lead:uaib_client_campaign_leads(business_name,website_url,industry,country)",
        "campaign_id": f"eq.{campaign_id}",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    if approval_status:
        params["approval_status"] = f"eq.{approval_status}"
    rows = await _db_request("GET", DRAFTS_TABLE, params=params)
    return {"count": len(rows or []), "items": rows or []}


@router.post("/drafts/{draft_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_draft(draft_id: UUID, request: DraftDecisionRequest):
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to record approval for this exact draft.")
    approved_at = datetime.now(timezone.utc).isoformat()
    rows = await _db_request(
        "PATCH",
        DRAFTS_TABLE,
        params={"id": f"eq.{draft_id}", "approval_status": "eq.awaiting_approval"},
        body={"approval_status": "approved_to_send", "approved_at": approved_at,
              "approval_note": request.note, "updated_at": approved_at},
    )
    if not rows:
        raise HTTPException(status_code=409, detail="Draft not found or it is no longer awaiting approval.")
    return {
        "draft": rows[0],
        "sent": False,
        "notice": "Approval was recorded only. This backend does not send email, DMs, or contact forms.",
    }


@router.post("/drafts/{draft_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_draft(draft_id: UUID, request: DraftDecisionRequest):
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to record rejection for this draft.")
    now = datetime.now(timezone.utc).isoformat()
    rows = await _db_request(
        "PATCH",
        DRAFTS_TABLE,
        params={"id": f"eq.{draft_id}", "approval_status": "eq.awaiting_approval"},
        body={"approval_status": "rejected", "approval_note": request.note, "updated_at": now},
    )
    if not rows:
        raise HTTPException(status_code=409, detail="Draft not found or it is no longer awaiting approval.")
    return {"draft": rows[0], "sent": False}
