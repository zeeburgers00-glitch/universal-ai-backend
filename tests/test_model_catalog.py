"""The model catalog must be current, and must never route to a dead model.

Regression behind this file: `gemini-2.0-flash` was hard-coded as the router
default long after Google shut it down (June 2026), so a fully configured Gemini
key produced failures that looked like our bug.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import ai_router, model_catalog
from app.main import app


def test_catalog_is_substantial_and_dated():
    data = model_catalog.load()
    assert data["verified_on"]
    assert len(data["sources"]) >= 3

    stats = model_catalog.stats()
    assert stats["total_models"] >= 50
    assert {"openai", "gemini", "groq"} <= set(stats["providers"])
    for provider in ("openai", "gemini", "groq"):
        assert stats["providers"][provider]["total"] > 0


@pytest.mark.parametrize("provider", ["openai", "gemini", "groq"])
def test_every_model_has_status_and_confidence(provider):
    block = model_catalog.load()["providers"][provider]
    for model in block["models"]:
        assert model["status"] in {"stable", "preview", "deprecated", "shutdown"}
        assert model["confidence"] in {"high", "medium"}
        assert model["kind"]
        assert model["capabilities"]


def test_shutdown_models_are_hidden_by_default():
    visible = model_catalog.list_models()["models"]
    assert all(model["status"] != "shutdown" for model in visible)

    everything = model_catalog.list_models(include_shutdown=True)["models"]
    assert len(everything) > len(visible)


def test_router_default_is_not_a_shutdown_model():
    """Every provider default must still exist at the provider."""

    for provider_id, provider in ai_router.PROVIDERS.items():
        if not provider.default_model:
            continue
        if not model_catalog.is_shutdown(provider.default_model):
            continue
        pytest.fail(f"{provider_id} defaults to shut-down model {provider.default_model}")


def test_gemini_default_is_current():
    assert ai_router.PROVIDERS["gemini"].default_model == "gemini-3.8-flash"


@pytest.mark.parametrize(
    "capability",
    ["vision", "image-out", "text-to-speech", "transcribe", "video-out", "reasoning", "tools"],
)
def test_resolve_never_returns_a_dead_model(capability):
    picked = model_catalog.resolve(capability)
    assert picked is not None, capability
    assert picked["status"] in model_catalog.USABLE_STATUSES
    assert capability in picked["capabilities"]


def test_free_preference_is_honoured():
    free = model_catalog.resolve("vision", prefer_free=True)
    paid = model_catalog.resolve("vision", prefer_free=False)
    assert free is not None and paid is not None
    assert free.get("free_tier") is True


def test_model_endpoints():
    with TestClient(app) as client:
        stats = client.get("/v1/ai/models/stats")
        assert stats.status_code == 200
        assert stats.json()["total_models"] >= 50

        groq = client.get("/v1/ai/models", params={"provider": "groq"})
        assert groq.status_code == 200
        assert all(row["provider"] == "groq" for row in groq.json()["models"])

        images = client.get("/v1/ai/models", params={"capability": "image-out"})
        assert images.status_code == 200
        assert images.json()["total"] > 0

        resolved = client.get("/v1/ai/models/resolve", params={"capability": "vision"})
        assert resolved.status_code == 200
        assert resolved.json()["status"] != "shutdown"

        impossible = client.get("/v1/ai/models/resolve", params={"capability": "teleportation"})
        assert impossible.status_code == 404
