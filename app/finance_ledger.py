from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .security import require_api_key

router = APIRouter(prefix="/v1/finance", tags=["finance-ledger"])
ENTRIES = "uaib_finance_entries"
PAYOUTS = "uaib_payout_requests"


def _config() -> tuple[str, str]:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key or not url.startswith("https://"):
        raise HTTPException(status_code=503, detail="Finance ledger requires HTTPS Supabase URL and backend-only service role key.")
    return url, key


async def _db(method: str, table: str, *, params: dict[str, str] | None = None,
              body: Any = None, prefer: str = "return=representation") -> Any:
    url, key = _config()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": prefer}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
            response = await client.request(method, f"{url}/rest/v1/{table}", params=params, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Finance database timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Finance database connection failed.") from exc
    if response.status_code >= 400:
        if response.status_code == 404:
            raise HTTPException(status_code=503, detail="Finance ledger migration is not installed.")
        raise HTTPException(status_code=502, detail=f"Finance database returned HTTP {response.status_code}.")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Finance database returned invalid JSON.") from exc


class EntryCreate(BaseModel):
    entry_type: Literal["income", "expense"]
    stream: Literal["services", "freelance", "adsense", "affiliate", "sponsorships", "saas", "youtube", "tools", "hosting", "other"]
    amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    verification: Literal["estimate", "invoice", "provider_statement", "verified_payment", "receipt"] = "estimate"
    reference: str = Field(min_length=4, max_length=240)
    note: str = Field(default="", max_length=1200)
    occurred_at: datetime | None = None


class PayoutCreate(BaseModel):
    provider: Literal["paypal", "payoneer", "bank_transfer", "other"]
    amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    note: str = Field(default="", max_length=1000)


class PayoutDecision(BaseModel):
    confirm: bool = False
    note: str = Field(default="", max_length=1000)


@router.get("/summary", dependencies=[Depends(require_api_key)])
async def finance_summary():
    entries = await _db("GET", ENTRIES, params={"select": "entry_type,amount,currency,verification", "limit": "5000"})
    totals: dict[str, dict[str, Decimal]] = {}
    for row in entries or []:
        currency = str(row.get("currency") or "USD")
        bucket = totals.setdefault(currency, {"income": Decimal("0"), "expense": Decimal("0"), "verified_income": Decimal("0")})
        amount = Decimal(str(row.get("amount") or "0"))
        kind = row.get("entry_type")
        if kind in {"income", "expense"}:
            bucket[kind] += amount
        if kind == "income" and row.get("verification") in {"provider_statement", "verified_payment"}:
            bucket["verified_income"] += amount
    return {"currencies": {k: {n: str(v) for n, v in vals.items()} for k, vals in totals.items()},
            "note": "Only provider_statement and verified_payment income counts as verified income. Estimates are not earnings."}


@router.get("/entries", dependencies=[Depends(require_api_key)])
async def list_finance_entries(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    rows = await _db("GET", ENTRIES, params={"select": "*", "order": "occurred_at.desc", "limit": str(limit), "offset": str(offset)})
    return {"count": len(rows or []), "items": rows or []}


@router.post("/entries", dependencies=[Depends(require_api_key)], status_code=201)
async def create_finance_entry(request: EntryCreate):
    now = datetime.now(timezone.utc).isoformat()
    row = {"id": str(uuid4()), **request.model_dump(mode="json"),
           "occurred_at": (request.occurred_at or datetime.now(timezone.utc)).isoformat(),
           "created_at": now,
           "recognized_as_realized_revenue": request.entry_type == "income" and request.verification in {"provider_statement", "verified_payment"}}
    rows = await _db("POST", ENTRIES, body=row)
    return {"item": (rows or [row])[0], "recognized_as_realized_revenue": row["recognized_as_realized_revenue"]}


@router.get("/payout-requests", dependencies=[Depends(require_api_key)])
async def list_payout_requests():
    rows = await _db("GET", PAYOUTS, params={"select": "*", "order": "created_at.desc", "limit": "200"})
    return {"count": len(rows or []), "items": rows or [],
            "notice": "Requests are records only; this API never connects to a wallet or transfers funds."}


@router.post("/payout-requests", dependencies=[Depends(require_api_key)], status_code=201)
async def create_payout_request(request: PayoutCreate):
    now = datetime.now(timezone.utc).isoformat()
    row = {"id": str(uuid4()), "provider": request.provider, "amount": str(request.amount),
           "currency": request.currency, "note": request.note, "status": "awaiting_approval",
           "created_at": now, "updated_at": now, "approved_at": None, "approval_note": None}
    rows = await _db("POST", PAYOUTS, body=row)
    return {"item": (rows or [row])[0], "transferred": False,
            "notice": "Payout request recorded only. No payment credentials, destination account details, or funds are handled."}


@router.post("/payout-requests/{payout_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_payout_request(payout_id: UUID, request: PayoutDecision):
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to approve this exact payout request.")
    now = datetime.now(timezone.utc).isoformat()
    rows = await _db("PATCH", PAYOUTS,
        params={"id": f"eq.{payout_id}", "status": "eq.awaiting_approval"},
        body={"status": "approved_for_manual_processing", "approved_at": now,
              "approval_note": request.note, "updated_at": now})
    if not rows:
        raise HTTPException(status_code=409, detail="Payout request not found or no longer awaiting approval.")
    return {"item": rows[0], "transferred": False,
            "notice": "Approval recorded; manually process the payout in your own provider account."}
