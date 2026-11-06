import asyncio
import pytest

from app import pexels
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_pexels_stock_search_requires_backend_auth(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-pexels-secret")
    response = client.post("/v1/media/stock/pexels/search", json={"query": "ocean waves"})
    assert response.status_code == 401


def test_pexels_stock_search_reports_missing_provider_key(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-pexels-secret")
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    response = client.post(
        "/v1/media/stock/pexels/search",
        headers={"X-API-Key": "test-pexels-secret"},
        json={"query": "ocean waves"},
    )
    assert response.status_code == 503


def test_pexels_video_search_uses_the_official_video_endpoint(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-test-key")
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"page": 1, "per_page": 1, "total_results": 0, "videos": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            seen["url"] = url
            seen["params"] = params
            seen["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(pexels.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(pexels.search_pexels_videos("ocean waves"))
    assert seen["url"] == "https://api.pexels.com/videos/search"
    assert seen["headers"]["Authorization"] == "pexels-test-key"
    assert result["provider"] == "pexels"
