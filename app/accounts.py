"""Connected mail accounts — with consent, not with passwords.

The request was "use all my gmail accounts automatically". Here is what that can honestly
mean, and what it cannot:

| Allowed here | Never here |
|---|---|
| Each of your accounts connected **once** through Google's own consent screen | Typing a password into this backend |
| Several accounts side by side, each with its own token | One credential shared across accounts |
| Read-only access by default (`gmail.readonly`) | Reading a mailbox you have not authorised |
| Sending only after `gmail.send` was granted **and** an approval token is presented | Bulk sending, auto-replies to strangers, "engagement" loops |
| Instant revoke, tokens deleted | Storing tokens in logs, git, or API responses |

Google does not allow password-based access for apps like this, and 2FA is not something to
work around — the OAuth flow is the supported path and the only one implemented.

Setup (once, ~5 minutes):

1. console.cloud.google.com → create a project → enable **Gmail API**.
2. OAuth consent screen → External → add yourself as a test user.
3. Credentials → OAuth client ID → **Web application** → authorised redirect URI
   `http://127.0.0.1:8000/v1/accounts/oauth/callback`.
4. Put the client id/secret in the environment (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`),
   or `POST /v1/vault/secrets`.

Until those exist, every function returns ``unavailable: ...`` with the missing step. No
fake inboxes, no sample data pretending to be your mail.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from . import governance
from .vault import get_secret

_LOCK = threading.RLock()  # re-entrant: helpers call init_db while holding it

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_SCOPES = (READ_SCOPE,)
MAX_ACCOUNTS = 10


class AccountError(ValueError):
    """Bad request: unknown account, missing scope, unconfirmed send."""


class AccountUnavailable(RuntimeError):
    """Nothing fake: credentials, network or a token is missing."""


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

def _db() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "accounts.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " label TEXT NOT NULL, email TEXT, provider TEXT DEFAULT 'google',"
            " scopes TEXT, status TEXT DEFAULT 'connected', created_at REAL, last_sync REAL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tokens (account_id INTEGER PRIMARY KEY,"
            " refresh_token TEXT, access_token TEXT, expires_at REAL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS oauth_states (state TEXT PRIMARY KEY, label TEXT,"
            " scopes TEXT, created_at REAL, used INTEGER DEFAULT 0)"
        )
    try:
        os.chmod(_db(), 0o600)
    except OSError:  # pragma: no cover - exotic filesystems
        pass


def _fernet():
    """Optional at-rest encryption. Absent `cryptography`, tokens are plain in a 0600 file."""

    try:
        from cryptography.fernet import Fernet
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    key_path = _db().with_suffix(".key")
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        os.chmod(key_path, 0o600)
    return Fernet(key_path.read_bytes())


def _seal(value: str) -> str:
    if not value:
        return ""
    cipher = _fernet()
    if cipher is None:
        return value
    return "enc:" + cipher.encrypt(value.encode()).decode()


def _unseal(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("enc:"):
        cipher = _fernet()
        if cipher is None:
            raise AccountUnavailable(
                "unavailable: token is encrypted but `cryptography` is not installed "
                "(pip install cryptography)"
            )
        return cipher.decrypt(value[4:].encode()).decode()
    return value


# --------------------------------------------------------------------------- #
# Network seams (stubbed in tests)
# --------------------------------------------------------------------------- #

def _client() -> tuple[str, str, str]:
    client_id = (os.getenv("GOOGLE_CLIENT_ID") or get_secret("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or get_secret("GOOGLE_CLIENT_SECRET") or "").strip()
    redirect = (os.getenv("GOOGLE_REDIRECT_URI") or
                "http://127.0.0.1:8000/v1/accounts/oauth/callback").strip()
    if not client_id or not client_secret:
        raise AccountUnavailable(
            "unavailable: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "(Google Cloud console → APIs & Services → Credentials → OAuth client)"
        )
    return client_id, client_secret, redirect


def _post_form(url: str, data: dict[str, str], timeout: float = 30.0) -> dict[str, Any]:
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, data=data,
                                   headers={"content-type": "application/x-www-form-urlencoded"})
    except Exception as exc:  # noqa: BLE001 - blocked network, DNS, timeout
        raise AccountUnavailable(f"unavailable: Google token endpoint unreachable ({type(exc).__name__})") from exc
    if response.status_code >= 400:
        raise AccountError(f"Google said HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def _get_json(url: str, access_token: str, params: dict[str, Any] | None = None,
              timeout: float = 30.0) -> dict[str, Any]:
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, params=params or {},
                                  headers={"Authorization": f"Bearer {access_token}"})
    except Exception as exc:  # noqa: BLE001
        raise AccountUnavailable(f"unavailable: Gmail API unreachable ({type(exc).__name__})") from exc
    if response.status_code == 401:
        raise AccountError("Gmail rejected the token (401) — reconnect this account")
    if response.status_code >= 400:
        raise AccountError(f"Gmail said HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #

def status() -> dict[str, Any]:
    try:
        client_id, _, redirect = _client()
        configured = True
        client = f"{client_id[:12]}…" if len(client_id) > 12 else client_id
    except AccountUnavailable as exc:
        configured = False
        client = ""
        redirect = (os.getenv("GOOGLE_REDIRECT_URI") or
                    "http://127.0.0.1:8000/v1/accounts/oauth/callback")
    init_db()
    with _connect() as connection:
        total = connection.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
    return {
        "oauth_configured": configured,
        "client_id": client,
        "redirect_uri": redirect,
        "accounts": total,
        "max_accounts": MAX_ACCOUNTS,
        "default_scopes": [READ_SCOPE],
        "send_scope": SEND_SCOPE,
        "tokens_encrypted": _fernet() is not None,
        "db": str(_db()),
        "honesty": (
            "One OAuth grant per account, granted by you in a browser. No password login, "
            "no shared credentials, no reading a mailbox that was never authorised."
        ),
        "blocked_by_design": [
            "password-based sign-in",
            "connecting an account without its owner's consent screen",
            "sending mail without gmail.send + an approval token",
            "importing credentials from a file or another app",
        ],
    }


def auth_url(label: str, *, scopes: tuple[str, ...] = DEFAULT_SCOPES) -> dict[str, Any]:
    client_id, _, redirect = _client()
    label = (label or "primary").strip()[:40]
    state = secrets.token_urlsafe(24)
    granted = tuple(dict.fromkeys([READ_SCOPE, *scopes]))
    init_db()
    with _LOCK, _connect() as connection:
        count = connection.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
        if count >= MAX_ACCOUNTS:
            raise AccountError(f"account limit reached ({MAX_ACCOUNTS}); disconnect one first")
        connection.execute(
            "INSERT INTO oauth_states (state, label, scopes, created_at) VALUES (?, ?, ?, ?)",
            (state, label, " ".join(granted), time.time()),
        )
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(granted),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return {
        "url": f"{AUTH_URL}?{query}",
        "state": state,
        "scopes": list(granted),
        "next": "Open the URL, pick the Gmail account, approve. Google redirects back with "
                "?code=...&state=... — paste both into POST /v1/accounts/oauth/finish.",
        "label": label,
    }


def finish(code: str, state: str) -> dict[str, Any]:
    if not code or not state:
        raise AccountError("both code and state are required")
    init_db()
    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
        if row is None:
            raise AccountError("unknown state — start the flow again")
        if row["used"]:
            raise AccountError("this state was already used")
        connection.execute("UPDATE oauth_states SET used = 1 WHERE state = ?", (state,))
        label, scopes = row["label"], row["scopes"].split()

    client_id, client_secret, redirect = _client()
    payload = _post_form(TOKEN_URL, {
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    })
    refresh = str(payload.get("refresh_token") or "")
    access = str(payload.get("access_token") or "")
    if not refresh:
        raise AccountError(
            "Google returned no refresh token. Remove the app from your Google account "
            "permissions and run the consent flow again (prompt=consent is required)."
        )
    expires = time.time() + float(payload.get("expires_in") or 3600)

    profile = _get_json(f"{GMAIL}/profile", access)
    email = str(profile.get("emailAddress") or "")

    with _LOCK, _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO accounts (label, email, provider, scopes, status, created_at)"
            " VALUES (?, ?, 'google', ?, 'connected', ?)",
            (label, email, " ".join(scopes), time.time()),
        )
        account_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO tokens (account_id, refresh_token, access_token, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (account_id, _seal(refresh), _seal(access), expires),
        )
    governance.record("account.connected", target=f"account:{account_id}",
                      detail={"email": email, "scopes": scopes})
    return {"id": account_id, "label": label, "email": email, "scopes": scopes,
            "connected": True}


def _account(account_id: int) -> sqlite3.Row:
    init_db()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM accounts WHERE id = ?", (int(account_id),)).fetchone()
    if row is None:
        raise AccountError(f"no account with id {account_id}")
    return row


def list_accounts() -> dict[str, Any]:
    init_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, label, email, provider, scopes, status, created_at, last_sync"
            " FROM accounts ORDER BY id"
        ).fetchall()
    accounts = [{
        "id": row["id"], "label": row["label"], "email": row["email"],
        "provider": row["provider"], "scopes": (row["scopes"] or "").split(),
        "status": row["status"],
        "connected_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["created_at"] or 0)),
        "last_sync": (time.strftime("%Y-%m-%d %H:%M", time.localtime(row["last_sync"]))
                      if row["last_sync"] else None),
        "can_send": SEND_SCOPE in (row["scopes"] or ""),
    } for row in rows]
    return {"count": len(accounts), "accounts": accounts,
            "note": "tokens are never returned by this API"}


def disconnect(account_id: int) -> dict[str, Any]:
    _account(account_id)
    with _LOCK, _connect() as connection:
        connection.execute("UPDATE accounts SET status = 'revoked' WHERE id = ?", (account_id,))
        connection.execute("DELETE FROM tokens WHERE account_id = ?", (account_id,))
    governance.record("account.disconnected", target=f"account:{account_id}")
    return {"id": int(account_id), "status": "revoked",
            "note": "tokens deleted locally. Revoke the app in your Google account as well "
                    "if you want the grant itself gone."}


def _access_token(account_id: int) -> tuple[str, sqlite3.Row]:
    account = _account(account_id)
    with _connect() as connection:
        row = connection.execute("SELECT * FROM tokens WHERE account_id = ?",
                                 (int(account_id),)).fetchone()
    if row is None:
        raise AccountError("this account has no token — reconnect it")
    if row["access_token"] and float(row["expires_at"] or 0) - 60 > time.time():
        return _unseal(row["access_token"]), account

    client_id, client_secret, _ = _client()
    payload = _post_form(TOKEN_URL, {
        "refresh_token": _unseal(row["refresh_token"]),
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    })
    access = str(payload.get("access_token") or "")
    if not access:
        raise AccountError("Google did not return an access token — reconnect this account")
    expires = time.time() + float(payload.get("expires_in") or 3600)
    with _LOCK, _connect() as connection:
        connection.execute("UPDATE tokens SET access_token = ?, expires_at = ? WHERE account_id = ?",
                           (_seal(access), expires, int(account_id)))
    return access, account


# --------------------------------------------------------------------------- #
# Gmail
# --------------------------------------------------------------------------- #

def _headers(message: dict[str, Any]) -> dict[str, str]:
    headers = (message.get("payload") or {}).get("headers") or []
    return {item.get("name", "").lower(): item.get("value", "") for item in headers}


def messages(account_id: int, *, query: str = "is:unread", limit: int = 10) -> dict[str, Any]:
    access, account = _access_token(account_id)
    limit = max(1, min(int(limit), 25))
    listing = _get_json(f"{GMAIL}/messages", access,
                        {"q": query or "is:unread", "maxResults": limit})
    items = []
    for entry in (listing.get("messages") or [])[:limit]:
        message = _get_json(
            f"{GMAIL}/messages/{entry['id']}", access,
            {"format": "metadata",
             "metadataHeaders": ["From", "Subject", "Date"]},
        )
        headers = _headers(message)
        items.append({
            "id": entry["id"],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": str(message.get("snippet") or "")[:240],
            "unread": "UNREAD" in (message.get("labelIds") or []),
        })
    with _LOCK, _connect() as connection:
        connection.execute("UPDATE accounts SET last_sync = ? WHERE id = ?",
                           (time.time(), int(account_id)))
    return {"account": {"id": account["id"], "label": account["label"], "email": account["email"]},
            "query": query, "count": len(items), "messages": items}


def digest(account_id: int, *, query: str = "is:unread", limit: int = 10) -> dict[str, Any]:
    """A short, faithful summary. Rules by default; the model only rewrites, never invents."""

    inbox = messages(account_id, query=query, limit=limit)
    if not inbox["messages"]:
        return {**inbox, "summary": "Inbox me is query par kuch nahi mila.", "used_model": False}

    bullets = [f"- {item['from']}: {item['subject']}" for item in inbox["messages"]]
    summary = "\n".join(bullets)
    used_model = False

    from . import jarvis

    if jarvis.model_available():
        answer = jarvis._ask_model(  # same persona plumbing, 2-sentence cap
            "Summarise these email subjects into at most 3 short lines. Do not invent names, "
            "numbers or deadlines that are not present. Reply in the user's language.",
            "Subjects:\n" + "\n".join(bullets),
        )
        if answer:
            summary = answer["text"]
            used_model = True
    return {**inbox, "summary": summary, "used_model": used_model}


def send(account_id: int, *, to: str, subject: str, body: str, confirm: bool = False,
         approval_token: str | None = None) -> dict[str, Any]:
    """Sending is the one destructive mail action, so it needs three separate keys."""

    account = _account(account_id)
    if SEND_SCOPE not in (account["scopes"] or ""):
        raise AccountError(
            "this account was connected read-only. Reconnect with the send scope if you want "
            "sending: POST /v1/accounts/oauth/start {\"label\": ..., \"allow_send\": true}"
        )
    if not confirm:
        raise AccountError("refusing to send: pass confirm=true after reading the draft")
    if not to.strip() or "@" not in to:
        raise AccountError("a real 'to' address is required")
    if not subject.strip():
        raise AccountError("subject is required")

    if governance.needs_approval("/v1/accounts/send"):
        governance.consume(approval_token, "/v1/accounts/send")

    raw = (f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"
           f"{body}").encode()
    access, _ = _access_token(account_id)
    import httpx

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{GMAIL}/messages/send", headers={"Authorization": f"Bearer {access}"},
                json={"raw": base64.urlsafe_b64encode(raw).decode()},
            )
    except Exception as exc:  # noqa: BLE001
        raise AccountUnavailable(f"unavailable: Gmail send unreachable ({type(exc).__name__})") from exc
    if response.status_code >= 400:
        raise AccountError(f"Gmail refused the send: HTTP {response.status_code} "
                           f"{response.text[:200]}")
    sent = response.json()
    governance.record("account.send", target=f"account:{account_id}",
                      detail={"to": to, "subject": subject[:80]})
    return {"sent": True, "id": sent.get("id"), "to": to, "subject": subject}
