"""Free-tier pool: quota accounting, keyring rotation, and local (unlimited) models."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import ai_router, quota
from app.main import app

KEY_ENVS = (
    "GROQ_API_KEY", "GROQ_API_KEYS", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
    "OLLAMA_API_KEY", "LMSTUDIO_API_KEY", "LLAMACPP_API_KEY",
    "OLLAMA_DEFAULT_MODEL", "AI_ALLOW_LOCAL_BASE", "AI_PROVIDER_ORDER",
    "AI_QUOTA_GEMINI", "AI_QUOTA_OLLAMA",
)


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    for name in KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    yield
    quota.reset()


# --- quota accounting ---------------------------------------------------------

def test_counter_tracks_usage_and_resets():
    quota.reset("gemini")
    assert quota.used("gemini") == 0
    quota.record("gemini")
    quota.record("gemini")
    assert quota.used("gemini") == 2
    assert quota.remaining("gemini") == quota.cap_for("gemini") - 2

    quota.reset("gemini")
    assert quota.used("gemini") == 0


def test_429_marks_provider_exhausted():
    quota.reset("gemini")
    assert quota.available("gemini")
    quota.record("gemini", "429")
    assert not quota.available("gemini")
    assert quota.status()["providers"]["gemini"]["exhausted"] is True


def test_cap_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("AI_QUOTA_GEMINI", "3")
    quota.reset("gemini")
    for _ in range(3):
        quota.record("gemini")
    assert quota.cap_for("gemini") == 3
    assert quota.remaining("gemini") == 0
    assert not quota.available("gemini")


def test_local_providers_are_unlimited_by_default(monkeypatch):
    monkeypatch.delenv("AI_QUOTA_OLLAMA", raising=False)
    assert quota.cap_for("ollama") == 0
    assert quota.remaining("ollama") is None


# --- keyring + local transport ------------------------------------------------

def test_keyring_expands_into_multiple_routes(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", "key-one, key-two ,key-three")
    routes = ai_router.resolve_all("groq")
    assert [route.key for route in routes] == ["key-one", "key-two", "key-three"]
    assert len(ai_router.chain()) >= 3


def test_single_key_still_works(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "solo-key")
    routes = ai_router.resolve_all("groq")
    assert len(routes) == 1 and routes[0].key == "solo-key"


def test_local_server_works_without_any_key():
    routes = ai_router.resolve_all("ollama")
    assert len(routes) == 1
    assert routes[0].base.startswith("http://127.0.0.1")
    assert routes[0].key == "local"


def test_remote_plain_http_is_rejected(monkeypatch):
    """A remote provider over plain http would leak the key — never allow it."""

    monkeypatch.setenv("AI_BASE_URL", "http://evil.example.com/v1")
    monkeypatch.setenv("AI_API_KEY", "secret")
    assert ai_router.resolve_all("custom") == []


def test_exhausted_provider_is_pushed_out_of_the_chain(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setenv("AI_PROVIDER_ORDER", "groq,gemini")
    quota.reset()
    assert [route.id for route in ai_router.chain()][:2] == ["groq", "gemini"]

    quota.mark_exhausted("groq")
    assert [route.id for route in ai_router.chain()][:1] == ["gemini"]


def test_chain_falls_back_when_everything_looks_exhausted(monkeypatch):
    """Local counters are estimates; a wrong estimate must not brick the app."""

    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("AI_PROVIDER_ORDER", "groq")
    quota.reset()
    quota.mark_exhausted("groq")
    assert [route.id for route in ai_router.chain()] == ["groq"]


# --- endpoint -----------------------------------------------------------------

def test_free_status_endpoint(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    with TestClient(app) as client:
        response = client.get("/v1/ai/free/status")
    assert response.status_code == 200
    body = response.json()

    assert "ollama" in body["unlimited_options"]
    groq = next(row for row in body["providers"] if row["provider"] == "groq")
    assert groq["configured"] is True
    assert groq["daily_cap"] > 0
    assert "terms" in body["quota"]["note"]


def test_free_reset_requires_the_api_key(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "secret-key")
    with TestClient(app) as client:
        assert client.post("/v1/ai/free/reset").status_code == 401
        ok = client.post("/v1/ai/free/reset", headers={"X-API-Key": "secret-key"})
    assert ok.status_code == 200


# --- real local model server --------------------------------------------------

def test_router_uses_a_local_server_for_free(monkeypatch):
    """A local OpenAI-compatible server must be reachable with no key and no quota."""

    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    calls: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            calls.append(json.loads(self.rfile.read(length) or b"{}"))
            body = json.dumps({
                "choices": [{"message": {"content": "local answer"}}],
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence stderr noise
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("OLLAMA_BASE_URL", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setenv("OLLAMA_DEFAULT_MODEL", "llama3.1")
        monkeypatch.setenv("AI_PROVIDER_ORDER", "ollama")

        result = ai_router.complete("be brief", "hello")
        assert result["provider"] == "ollama"
        assert result["text"] == "local answer"
        assert calls and calls[0]["model"] == "llama3.1"
    finally:
        server.shutdown()
        server.server_close()
