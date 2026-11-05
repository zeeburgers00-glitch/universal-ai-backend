"""Metrics and rate limiting without any external service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import obs
from app.main import app


@pytest.fixture(autouse=True)
def clean_metrics(monkeypatch):
    monkeypatch.setenv("UAI_RATE_LIMIT", "0")
    obs.reset()
    yield
    obs.reset()


# --- path grouping ------------------------------------------------------------

@pytest.mark.parametrize(
    "path,expected",
    [
        ("/v1/jobs/abc123def4567890abcdef", "/v1/jobs/:id"),
        ("/v1/jobs/42", "/v1/jobs/:id"),
        ("/v1/code/search", "/v1/code/search"),
        ("/health", "/health"),
        ("/", "/"),
    ],
)
def test_path_grouping_keeps_cardinality_low(path, expected):
    assert obs.path_group(path) == expected


# --- prometheus ---------------------------------------------------------------

def test_metrics_endpoint_exposes_prometheus_text():
    with TestClient(app) as client:
        client.get("/health")
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "# TYPE uai_requests_total counter" in body
    assert 'route="/health"' in body
    assert "uai_uptime_seconds" in body
    assert "uai_inflight_requests" in body


def test_counts_increase_with_traffic():
    with TestClient(app) as client:
        client.get("/health")
        client.get("/health")
        body = client.get("/metrics").text
    assert 'uai_requests_total{method="GET",route="/health",status="2xx"}' in body


def test_summary_requires_the_key(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "obs-key")
    with TestClient(app) as client:
        assert client.get("/v1/observability/summary").status_code == 401
        summary = client.get("/v1/observability/summary", headers={"X-API-Key": "obs-key"})
    assert summary.status_code == 200
    assert summary.json()["rate_limit_per_minute"] == 0


# --- rate limiting ------------------------------------------------------------

def test_rate_limit_blocks_after_the_ceiling(monkeypatch):
    monkeypatch.setenv("UAI_RATE_LIMIT", "3")
    monkeypatch.setenv("BACKEND_API_KEY", "obs-key")
    with TestClient(app) as client:
        codes = [client.get("/v1/sdk", headers={"X-API-Key": "rate-a"}).status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401]  # auth still decides; limiter counts them
    assert codes[3] == 429


def test_rate_limit_sends_retry_after(monkeypatch):
    monkeypatch.setenv("UAI_RATE_LIMIT", "1")
    with TestClient(app) as client:
        client.get("/v1/sdk", headers={"X-API-Key": "rate-b"})
        blocked = client.get("/v1/sdk", headers={"X-API-Key": "rate-b"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["detail"] == "rate limit exceeded"


def test_health_and_metrics_are_never_rate_limited(monkeypatch):
    monkeypatch.setenv("UAI_RATE_LIMIT", "1")
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/health").status_code == 200
            assert client.get("/metrics").status_code == 200


def test_limiter_is_per_client(monkeypatch):
    monkeypatch.setenv("UAI_RATE_LIMIT", "2")
    monkeypatch.setenv("BACKEND_API_KEY", "obs-key")
    with TestClient(app) as client:
        for _ in range(2):
            client.get("/v1/sdk", headers={"X-API-Key": "tenant-one"})
        assert client.get("/v1/sdk", headers={"X-API-Key": "tenant-one"}).status_code == 429
        assert client.get("/v1/sdk", headers={"X-API-Key": "tenant-two"}).status_code == 401


def test_disabled_limiter_allows_everything(monkeypatch):
    monkeypatch.setenv("UAI_RATE_LIMIT", "0")
    monkeypatch.setenv("BACKEND_API_KEY", "obs-key")
    with TestClient(app) as client:
        assert all(client.get("/v1/sdk").status_code == 401 for _ in range(20))
