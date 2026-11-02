import pytest
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
