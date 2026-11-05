"""Supabase connection: verify it, report what is missing, keep JARVIS memory durable.

Local SQLite stays the source of truth for speed (a chat turn must not wait on a network
round trip), and Supabase is the durable copy: facts, lessons and the journal survive a
wiped machine, a new PC, or a dead Kaggle session.

This module deliberately does **not** print or return secrets, and it never claims a table
exists because a migration said so — it asks PostgREST for one row and reports the status
code it actually got:

* 200 → present
* 404 → missing (run the migration)
* 401/403 → key wrong or RLS blocked (should not happen with the service-role key)

Config (env or `POST /v1/vault/secrets`):
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY=...        (never the anon key: RLS is on with no policies)
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from . import governance

TIMEOUT = 12.0

# table -> what it is for
EXPECTED_TABLES: dict[str, str] = {
    "uaib_custom_tools": "custom tool payloads (app/supabase_store.py)",
    "uaib_execution_logs": "execution history",
    "uaib_runtime_secrets": "runtime vault (app/vault.py)",
    "uaib_finance_entries": "finance ledger entries",
    "uaib_payout_requests": "payout requests (records only, never transfers)",
    "uaib_client_campaign_leads": "campaign CRM leads",
    "uaib_client_campaign_drafts": "campaign CRM drafts",
    "uaib_jarvis_facts": "JARVIS memory, durable copy",
    "uaib_jarvis_lessons": "JARVIS reflection lessons",
    "uaib_jarvis_journal": "JARVIS journal lines",
}

MIGRATION = "supabase/migrations/20261105140000_uaib_core_tables.sql"


class SupabaseError(RuntimeError):
    """Configured but the call failed."""


class SupabaseUnavailable(RuntimeError):
    """Not configured (or the network is blocked) — say which."""


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def url() -> str:
    return (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")


def service_key() -> str:
    return (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def configured() -> bool:
    return bool(url() and service_key())


def _mask(value: str) -> str:
    return "" if not value else (f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "set")


def project_ref() -> str:
    host = url().replace("https://", "").replace("http://", "")
    return host.split(".")[0] if host else ""


# --------------------------------------------------------------------------- #
# Transport (one seam, so tests never touch the network)
# --------------------------------------------------------------------------- #

def _request(method: str, path: str, *, params: dict[str, str] | None = None,
             body: Any = None, prefer: str | None = None,
             timeout: float = TIMEOUT) -> tuple[int, Any]:
    if not configured():
        raise SupabaseUnavailable(
            "unavailable: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "(Supabase dashboard → Project Settings → API)"
        )
    key = service_key()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, f"{url()}{path}", params=params, json=body,
                                      headers=headers)
    except Exception as exc:  # noqa: BLE001 - DNS, timeout, blocked sandbox
        raise SupabaseUnavailable(
            f"unavailable: Supabase unreachable ({type(exc).__name__})"
        ) from exc

    payload: Any = None
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:500]
    return response.status_code, payload


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

def ping() -> dict[str, Any]:
    started = time.perf_counter()
    status, _ = _request("GET", "/rest/v1/", params={"limit": "1"})
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return {
        "reachable": status < 400,
        "status": status,
        "latency_ms": elapsed,
        "project_ref": project_ref(),
        "note": "" if status < 400 else "401/403 means the key is wrong or not the service role",
    }


def schema_report() -> dict[str, Any]:
    """Ask PostgREST for one row of each table. The status code is the truth."""

    started = time.perf_counter()
    present: list[str] = []
    missing: list[str] = []
    blocked: list[str] = []
    for table, purpose in EXPECTED_TABLES.items():
        status, _ = _request("GET", f"/rest/v1/{table}",
                             params={"select": "*", "limit": "1"})
        if status < 300:
            present.append(table)
        elif status == 404:
            missing.append(table)
        else:
            blocked.append(table)
    return {
        "present": present,
        "missing": missing,
        "blocked": blocked,
        "purposes": {table: EXPECTED_TABLES[table] for table in missing},
        "migration": MIGRATION,
        "complete": not missing and not blocked,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "next": ("" if not (missing or blocked) else
                 f"Run {MIGRATION} in the Supabase SQL editor, then check again."),
    }


def status() -> dict[str, Any]:
    configured_here = configured()
    payload: dict[str, Any] = {
        "configured": configured_here,
        "project_ref": project_ref() or None,
        "url": url() or None,
        "service_key": _mask(service_key()),
        "expected_tables": list(EXPECTED_TABLES),
        "migration": MIGRATION,
        "honesty": (
            "Local SQLite is the source of truth for chat speed; Supabase is the durable "
            "copy. A table counts as present only when PostgREST answers for it."
        ),
    }
    if configured_here:
        try:
            payload["ping"] = ping()
        except SupabaseUnavailable as exc:
            payload["ping"] = {"reachable": False, "error": str(exc)}
    else:
        payload["next"] = (
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (service role, not anon). "
            "Keep them in .env or POST /v1/vault/secrets — never in chat or git."
        )
    return payload


# --------------------------------------------------------------------------- #
# JARVIS memory sync
# --------------------------------------------------------------------------- #

def push_jarvis(limit: int = 500) -> dict[str, Any]:
    """Copy local facts, lessons and journal lines up to Supabase. Idempotent upserts."""

    from . import jarvis, mind

    limit = max(1, min(int(limit), 2000))
    facts = jarvis.facts(limit)
    lessons = mind.lessons(limit)
    entries = mind.entries(limit)

    pushed = {"facts": 0, "lessons": 0, "journal": 0}
    errors: list[str] = []

    if facts:
        rows = [{"key": item["key"], "value": item["value"],
                 "source": item.get("source") or "user"} for item in facts]
        status, _ = _request("POST", "/rest/v1/uaib_jarvis_facts",
                            params={"on_conflict": "key"}, body=rows,
                            prefer="resolution=merge-duplicates,return=minimal")
        if status < 300:
            pushed["facts"] = len(rows)
        else:
            errors.append(f"facts: HTTP {status}")

    if lessons:
        rows = [{"text": item["text"], "source": item.get("source") or "reflection",
                 "evidence": item.get("evidence") or ""} for item in lessons]
        status, _ = _request("POST", "/rest/v1/uaib_jarvis_lessons",
                            params={"on_conflict": "text"}, body=rows,
                            prefer="resolution=merge-duplicates,return=minimal")
        if status < 300:
            pushed["lessons"] = len(rows)
        else:
            errors.append(f"lessons: HTTP {status}")

    if entries:
        rows = [{"at": item["at"], "entry": item["entry"],
                 "mood": item.get("mood") or "", "kind": item.get("kind") or "note"}
                for item in entries]
        status, _ = _request("POST", "/rest/v1/uaib_jarvis_journal", body=rows,
                            prefer="return=minimal")
        if status < 300:
            pushed["journal"] = len(rows)
        else:
            errors.append(f"journal: HTTP {status}")

    governance.record("supabase.sync", target="jarvis", outcome="ok" if not errors else "partial",
                      detail=pushed)
    return {
        "pushed": pushed,
        "errors": errors,
        "direction": "local → supabase",
        "note": "Upserts are idempotent; running this twice does not duplicate facts or lessons.",
    }


def pull_facts(limit: int = 500) -> dict[str, Any]:
    """Restore memory from Supabase into the local SQLite store (new machine / wiped disk)."""

    from . import jarvis

    status, rows = _request("GET", "/rest/v1/uaib_jarvis_facts",
                            params={"select": "key,value,source", "limit": str(limit)})
    if status >= 300 or not isinstance(rows, list):
        raise SupabaseError(f"could not read uaib_jarvis_facts: HTTP {status}")

    restored = 0
    skipped = 0
    for row in rows:
        try:
            jarvis.remember(str(row["key"]), str(row["value"]),
                            source=str(row.get("source") or "supabase"))
            restored += 1
        except (KeyError, ValueError):
            skipped += 1
    return {"restored": restored, "skipped": skipped, "direction": "supabase → local",
            "note": "Local values win on conflict: remember() overwrites only with valid input."}
