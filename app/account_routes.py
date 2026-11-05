"""HTTP routes for connected mail accounts (`/v1/accounts/*`).

Consent first: `/oauth/start` sends the owner to Google, `/oauth/finish` stores what Google
returns. There is no endpoint that accepts a password, and no endpoint that returns a token.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import accounts
from .security import require_api_key

router = APIRouter(prefix="/v1/accounts", tags=["accounts"], dependencies=[Depends(require_api_key)])


class StartRequest(BaseModel):
    label: str = Field(default="primary", max_length=40,
                       description="Your name for this account, e.g. 'work' or 'personal'")
    allow_send: bool = Field(default=False,
                             description="Also request gmail.send (still needs confirm + approval)")


class FinishRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=200)


class MessagesRequest(BaseModel):
    query: str = Field(default="is:unread", max_length=200)
    limit: int = Field(default=10, ge=1, le=25)


class SendRequest(BaseModel):
    account_id: int = Field(ge=1)
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=20000)
    confirm: bool = Field(default=False,
                          description="Must be true. Read the draft first — this is irreversible.")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, accounts.AccountUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
def list_accounts() -> dict[str, Any]:
    return accounts.list_accounts()


@router.get("/status")
def account_status() -> dict[str, Any]:
    return accounts.status()


@router.post("/oauth/start")
def oauth_start(body: StartRequest) -> dict[str, Any]:
    scopes = accounts.DEFAULT_SCOPES + ((accounts.SEND_SCOPE,) if body.allow_send else ())
    try:
        return accounts.auth_url(body.label, scopes=scopes)
    except (accounts.AccountError, accounts.AccountUnavailable) as exc:
        raise _fail(exc) from exc


@router.get("/oauth/callback")
def oauth_callback(code: str = Query(min_length=1, max_length=2000),
                   state: str = Query(min_length=1, max_length=200)) -> dict[str, Any]:
    """The redirect Google lands on. It only exchanges the code, nothing else."""

    try:
        return accounts.finish(code, state)
    except (accounts.AccountError, accounts.AccountUnavailable) as exc:
        raise _fail(exc) from exc


@router.post("/oauth/finish")
def oauth_finish(body: FinishRequest) -> dict[str, Any]:
    try:
        return accounts.finish(body.code, body.state)
    except (accounts.AccountError, accounts.AccountUnavailable) as exc:
        raise _fail(exc) from exc


@router.post("/send")
def send_mail(body: SendRequest) -> dict[str, Any]:
    try:
        return accounts.send(body.account_id, to=body.to, subject=body.subject,
                             body=body.body, confirm=body.confirm)
    except (accounts.AccountError, accounts.AccountUnavailable) as exc:
        raise _fail(exc) from exc


@router.post("/{account_id}/messages")
def list_messages(account_id: int, body: MessagesRequest) -> dict[str, Any]:
    try:
        return accounts.messages(account_id, query=body.query, limit=body.limit)
    except (accounts.AccountError, accounts.AccountUnavailable) as exc:
        raise _fail(exc) from exc


@router.post("/{account_id}/digest")
def digest(account_id: int, body: MessagesRequest) -> dict[str, Any]:
    try:
        return accounts.digest(account_id, query=body.query, limit=body.limit)
    except (accounts.AccountError, accounts.AccountUnavailable) as exc:
        raise _fail(exc) from exc


@router.delete("/{account_id}")
def disconnect(account_id: int) -> dict[str, Any]:
    try:
        return accounts.disconnect(account_id)
    except accounts.AccountError as exc:
        raise _fail(exc) from exc
