"""Scoped API keys, an append-only audit log, and approval gates for risky writes.

This is the layer that makes "one shared secret" safe enough for a team:

* **scopes** — a key can be limited to read-only, or to specific areas
  (``UAI_KEY_SCOPES='{"kid1":"code:write,video:*"}'``); the main
  ``BACKEND_API_KEY`` stays unrestricted so bootstrapping never breaks.
* **audit log** — every write and every admin action lands in
  ``$UAI_DATA_ROOT/audit.jsonl`` as one JSON line, with the key fingerprint
  (never the key itself).
* **approval gates** — with ``UAI_REQUIRE_APPROVAL=1``, dangerous operations
  (applying a patch, restoring a backup, committing to git) need a short-lived
  token from ``POST /v1/governance/approvals``.

No database, no SaaS: a JSONL file and a dict of tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

APPROVAL_TTL = 900  # seconds
_lock = threading.Lock()
_approvals: dict[str, dict[str, Any]] = {}

# route prefix -> the scope it needs when scopes are configured
SCOPE_RULES = {
    "/v1/code/write": "code:write",
    "/v1/code/apply": "code:write",
    "/v1/data/restore": "data:write",
    "/v1/git/commit": "git:write",
    "/v1/jobs": "jobs:write",
    "/v1/video": "video:write",
}

# Operations that can be gated behind an approval token.
DANGEROUS = ("/v1/code/write", "/v1/code/apply", "/v1/data/restore", "/v1/git/commit",
             "/v1/accounts/send")


class GovernanceError(RuntimeError):
    """Rejected request, with an HTTP status attached."""

    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.status = status


# --- audit log ----------------------------------------------------------------

def audit_path() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT", "/data")).expanduser()
    return root / "audit.jsonl"


def fingerprint(key: str | None) -> str:
    """Stable short id for a key, so the log never stores the secret."""

    if not key:
        return "anonymous"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def record(
    action: str,
    *,
    key: str | None = None,
    target: str | None = None,
    outcome: str = "ok",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "action": action,
        "actor": fingerprint(key),
        "target": target,
        "outcome": outcome,
        "detail": detail or {},
    }
    path = audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # Logging must never break the request it is describing.
        pass
    return entry


def read_log(limit: int = 100, action: str | None = None) -> dict[str, Any]:
    path = audit_path()
    if not path.is_file():
        return {"count": 0, "entries": [], "path": str(path)}
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action and entry.get("action") != action:
                continue
            entries.append(entry)
    entries = entries[-limit:][::-1]
    return {"count": len(entries), "entries": entries, "path": str(path)}


# --- scopes -------------------------------------------------------------------

def key_scopes() -> dict[str, set[str]]:
    raw = os.getenv("UAI_KEY_SCOPES", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    scopes: dict[str, set[str]] = {}
    for key, value in parsed.items():
        items = value if isinstance(value, list) else str(value).split(",")
        scopes[key] = {str(item).strip() for item in items if str(item).strip()}
    return scopes


def scope_for_path(path: str) -> str | None:
    for prefix, scope in SCOPE_RULES.items():
        if path.startswith(prefix):
            return scope
    return None


def _scope_allows(granted: set[str], needed: str) -> bool:
    if "*" in granted or "admin" in granted:
        return True
    if needed in granted:
        return True
    area = needed.split(":")[0]
    return f"{area}:*" in granted


READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def authorise(api_key: str | None, path: str, method: str = "GET") -> None:
    """Raise GovernanceError when a scoped key may not touch this path.

    Scopes only gate *writes*. Reads stay open to any valid key, because a
    read-only integration is the common case and locking reads behind a scope
    would break the studio and the editor for scoped keys.
    """

    if method.upper() in READ_METHODS:
        return

    scopes = key_scopes()
    if not scopes:
        return  # scoping not configured: the shared secret's behaviour is unchanged
    granted = scopes.get(api_key or "")
    if granted is None:
        if api_key and os.getenv("UAI_UNSCOPED_DENY") == "1":
            raise GovernanceError("this key has no scopes configured", 403)
        return  # unscoped keys stay unrestricted unless the operator opts in
    needed = scope_for_path(path)
    if needed and not _scope_allows(granted, needed):
        raise GovernanceError(f"key lacks scope '{needed}'", 403)


def whoami(api_key: str | None) -> dict[str, Any]:
    scopes = key_scopes()
    granted = scopes.get(api_key or "")
    return {
        "actor": fingerprint(api_key),
        "scoped": bool(scopes),
        "scopes": sorted(granted) if granted else [],
        "unrestricted": granted is None,
        "approval_required": approval_required(),
    }


# --- approvals ----------------------------------------------------------------

def approval_required() -> bool:
    return (os.getenv("UAI_REQUIRE_APPROVAL") or "").strip().lower() in {"1", "true", "yes", "on"}


def needs_approval(path: str) -> bool:
    return approval_required() and any(path.startswith(prefix) for prefix in DANGEROUS)


def grant(path: str, reason: str, key: str | None = None) -> dict[str, Any]:
    token = secrets.token_urlsafe(18)
    expires = time.time() + APPROVAL_TTL
    _approvals[token] = {"path": path, "reason": reason, "actor": fingerprint(key), "expires": expires}
    record("approval.granted", key=key, target=path, detail={"reason": reason})
    return {"token": token, "path": path, "expires_in": APPROVAL_TTL, "reason": reason}


def _prune() -> None:
    now = time.time()
    for token in [token for token, meta in _approvals.items() if meta["expires"] < now]:
        _approvals.pop(token, None)


def consume(token: str | None, path: str, key: str | None = None) -> None:
    """Single-use: a token is removed as soon as it is accepted."""

    if not needs_approval(path):
        return
    _prune()
    if not token:
        raise GovernanceError("approval token required for this operation", 428)
    meta = _approvals.get(token)
    if meta is None:
        raise GovernanceError("invalid or expired approval token", 403)
    if not path.startswith(meta["path"].rstrip("*")):
        raise GovernanceError("approval token was issued for a different operation", 403)
    _approvals.pop(token, None)
    record("approval.used", key=key, target=path)


def approvals() -> dict[str, Any]:
    _prune()
    return {
        "pending": [
            {"path": meta["path"], "reason": meta["reason"], "actor": meta["actor"],
             "expires_in": max(0, int(meta["expires"] - time.time()))}
            for meta in _approvals.values()
        ],
        "required": approval_required(),
        "dangerous_paths": list(DANGEROUS),
    }


def reset() -> None:
    _approvals.clear()
