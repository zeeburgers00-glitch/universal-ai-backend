"""Tests for the single-page Universal AI Studio app."""

from fastapi.testclient import TestClient

from app.main import app
from app.studio_ui import STUDIO_HTML

client = TestClient(app)


def test_studio_routes_serve_html():
    for path in ("/app", "/studio"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Universal AI Studio" in response.text


def test_studio_root_advertises_the_app():
    payload = client.get("/").json()
    assert payload["studio"] == "/app"


def test_studio_is_self_contained():
    # A preview environment may have no outbound network: no CDN dependencies.
    assert "cdn." not in STUDIO_HTML
    assert "unpkg.com" not in STUDIO_HTML
    assert "https://fonts." not in STUDIO_HTML
    assert "<script src=" not in STUDIO_HTML


def test_studio_uses_relative_api_paths():
    # Same-origin requests only; the browser must never call localhost directly.
    assert "http://127.0.0.1" not in STUDIO_HTML
    assert "localhost:" not in STUDIO_HTML
    assert "/v1/catalog/stats" in STUDIO_HTML
    assert "/v1/tools" in STUDIO_HTML
    assert "/v1/chat/completions" in STUDIO_HTML


def test_studio_does_not_embed_secrets():
    assert "SUPABASE_SERVICE_ROLE_KEY=" not in STUDIO_HTML
    assert "BACKEND_API_KEY=" not in STUDIO_HTML
