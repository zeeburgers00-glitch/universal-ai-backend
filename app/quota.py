"""Daily free-tier accounting, so the router stops hammering a provider that is out.

Free tiers are capped per day (Gemini Flash is famously ~20 requests/day). Without
accounting, every call after the cap burns a round trip, gets a 429, and the user
sees "everything failed". This module keeps a tiny per-day counter on disk and
tells the router which providers still have room.

Two honest constraints:

* These caps are **defaults**, not provider promises. Override with
  ``AI_QUOTA_<PROVIDER>`` (e.g. ``AI_QUOTA_GEMINI=20``).
* Creating extra accounts to multiply quotas violates most providers' terms.
  Rotating keys **you legitimately own** is fine; that is what the keyring does.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Documented/community-observed daily request caps for free tiers (Nov 2026).
DEFAULT_CAPS: dict[str, int] = {
    "gemini": 20,          # Gemini 3.x Flash free tier, per project
    "groq": 14_400,        # llama-3.3-70b free tier daily requests
    "openrouter": 50,      # :free models, daily (account needs $0 balance)
    "mistral": 1_000,      # free "experiment" tier
    "cerebras": 1_000,
    "huggingface": 300,
    "zai": 200,
    "ollama": 0,           # 0 = unlimited (local, no quota)
    "lmstudio": 0,
    "llamacpp": 0,
    "custom": 0,
}


def data_dir() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    return root / "quota"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _state_path() -> Path:
    return data_dir() / "usage.json"


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(state: dict[str, Any]) -> None:
    """Persist counters. A read-only filesystem (serverless hosts) must not crash a request."""

    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def cap_for(provider: str) -> int:
    """Daily allowance. ``0`` means unlimited (local models)."""

    env = (os.getenv(f"AI_QUOTA_{provider.upper()}") or "").strip()
    if env.isdigit():
        return int(env)
    return DEFAULT_CAPS.get(provider, 0)


def _bucket(state: dict[str, Any], provider: str) -> dict[str, Any]:
    day = state.get(_today())
    if not isinstance(day, dict):
        day = {}
        state[_today()] = day
    bucket = day.get(provider)
    if not isinstance(bucket, dict):
        bucket = {"used": 0, "exhausted": False, "last_status": None}
        day[provider] = bucket
    return bucket


def used(provider: str) -> int:
    return int(_bucket(_load(), provider).get("used", 0))


def remaining(provider: str) -> int | None:
    """``None`` when unlimited, else requests left today."""

    cap = cap_for(provider)
    if cap <= 0:
        return None
    return max(0, cap - used(provider))


def available(provider: str) -> bool:
    state = _load()
    bucket = _bucket(state, provider)
    if bucket.get("exhausted"):
        return False
    left = remaining(provider)
    return left is None or left > 0


def mark_exhausted(provider: str, reason: str = "429") -> None:
    state = _load()
    bucket = _bucket(state, provider)
    bucket["exhausted"] = True
    bucket["last_status"] = reason
    _save(state)


def record(provider: str, status: str = "ok", count: int = 1) -> None:
    """Count one attempt; a 429 immediately marks the provider as exhausted."""

    state = _load()
    bucket = _bucket(state, provider)
    bucket["used"] = int(bucket.get("used", 0)) + count
    bucket["last_status"] = status
    if status == "429":
        bucket["exhausted"] = True
    _save(state)


def status() -> dict[str, Any]:
    state = _load()
    day = state.get(_today(), {})
    providers: dict[str, Any] = {}
    for provider, cap in DEFAULT_CAPS.items():
        bucket = day.get(provider) if isinstance(day, dict) else None
        used_today = int((bucket or {}).get("used", 0))
        providers[provider] = {
            "daily_cap": cap,
            "used_today": used_today,
            "remaining": None if cap <= 0 else max(0, cap - used_today),
            "exhausted": bool((bucket or {}).get("exhausted", False)),
            "unlimited": cap <= 0,
            "last_status": (bucket or {}).get("last_status"),
        }
    return {
        "date_utc": _today(),
        "resets_at": f"{_today()}T00:00:00Z (+1 day)",
        "note": (
            "Caps are local estimates of provider free tiers, not provider guarantees. "
            "Override with AI_QUOTA_<PROVIDER>. Rotating keys you own is fine; creating "
            "extra accounts to dodge limits breaks most providers' terms."
        ),
        "providers": providers,
    }


def reset(provider: str | None = None) -> None:
    """Clear today's counters (admin/testing)."""

    state = _load()
    day = state.get(_today())
    if not isinstance(day, dict):
        return
    if provider:
        day.pop(provider, None)
    else:
        day.clear()
    _save(state)
