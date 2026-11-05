"""Which models each provider actually offers right now.

The provider registry answers "do I have a key?"; this catalog answers "what can
that key call?". It is a dated snapshot (`catalog/models.json`) so answers are
deterministic and reviewable in a diff, and every entry carries:

  * ``status``     – stable / preview / deprecated / shutdown
  * ``confidence`` – how the model ID was established (high = read in provider docs)
  * ``free_tier``  – whether the provider serves it without billing

Anything marked ``shutdown`` must never be picked as a default: Google turned
``gemini-2.0-flash`` off in June 2026 while it was still the hard-coded default
here, which made a fully configured deployment look broken.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog" / "models.json"
USABLE_STATUSES = ("stable", "preview")

# Preference when several live models can do the job (earlier = better).
TIER_ORDER = (
    "flagship", "flagship-fast", "balanced", "pro", "fast", "workhorse",
    "reasoning", "coding", "image-default", "moE", "moE-fast", "realtime",
    "omni", "stt", "stt-fast", "tts", "video", "agentic", "open-weights",
    "budget", "cheap", "cheapest", "preview",
)


class CatalogUnavailable(RuntimeError):
    """Raised when catalog/models.json is missing."""


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise CatalogUnavailable("catalog/models.json is missing")
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _iter_models(provider: str | None = None):
    for provider_id, block in load()["providers"].items():
        if provider and provider_id != provider:
            continue
        for model in block.get("models", []):
            yield provider_id, block, model


def stats() -> dict[str, Any]:
    data = load()
    per_provider: dict[str, Any] = {}
    total = 0
    for provider_id, block in data["providers"].items():
        models = block.get("models", [])
        total += len(models)
        per_provider[provider_id] = {
            "label": block.get("label"),
            "default_model": block.get("default_model"),
            "key_env": block.get("key_env"),
            "total": len(models),
            "usable": sum(1 for m in models if m.get("status") in USABLE_STATUSES),
            "free_tier": sum(1 for m in models if m.get("free_tier")),
            "kinds": sorted({m.get("kind") for m in models}),
        }
    return {
        "verified_on": data.get("verified_on"),
        "total_models": total,
        "providers": per_provider,
        "note": data.get("note"),
        "sources": data.get("sources", []),
    }


def list_models(
    provider: str | None = None,
    capability: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    free_only: bool = False,
    include_shutdown: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for provider_id, block, model in _iter_models(provider):
        if not include_shutdown and model.get("status") == "shutdown" and status != "shutdown":
            continue
        if capability and capability not in model.get("capabilities", []):
            continue
        if kind and model.get("kind") != kind:
            continue
        if status and model.get("status") != status:
            continue
        if free_only and not model.get("free_tier"):
            continue
        rows.append({"provider": provider_id, "provider_label": block.get("label"), **model})

    rows.sort(key=lambda row: (row["provider"], str(row.get("tier")), row["id"]))
    return {"total": len(rows), "models": rows}


def resolve(capability: str, prefer_free: bool = True, provider: str | None = None) -> dict[str, Any] | None:
    """Pick the most sensible live model for a capability. Never returns a dead one."""

    candidates = [
        row
        for row in list_models(provider=provider, capability=capability)["models"]
        if row.get("status") in USABLE_STATUSES
    ]
    if not candidates:
        return None

    def rank(row: dict[str, Any]) -> tuple[int, int, int, str]:
        free_rank = 0 if (prefer_free and row.get("free_tier")) else 1
        status_rank = 0 if row.get("status") == "stable" else 1
        tier = str(row.get("tier"))
        tier_rank = TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)
        return (free_rank, status_rank, tier_rank, row["id"])

    return sorted(candidates, key=rank)[0]


def is_shutdown(model_id: str, provider: str | None = None) -> bool:
    for _provider_id, _block, model in _iter_models(provider):
        if model.get("id") == model_id:
            return model.get("status") == "shutdown"
    return False
