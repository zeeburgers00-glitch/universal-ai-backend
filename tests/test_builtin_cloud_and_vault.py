"""Tests for built-in cloud runtime (45 providers, 9 workers, 37 channels, 229 REA tools, WAV TTS) and Vault API."""

from fastapi.testclient import TestClient

from app.main import app
from app.vault import invalidate_vault_cache, mask_secret


def test_mask_secret_never_exposes_plaintext():
    assert mask_secret("") == ""
    assert mask_secret("short") == "••••••"
    masked = mask_secret("sk-proj-1234567890abcdef")
    assert masked.endswith("cdef")
    assert "1234567890" not in masked


def test_browser_root_negotiation_and_json_root_default():
    client = TestClient(app)
    json_resp = client.get("/")
    assert json_resp.status_code == 200
    assert json_resp.json()["name"] == "Universal AI Backend"

    html_resp = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers["content-type"]
    assert "3D Control Plane" in html_resp.text


def test_builtin_cloud_runtime_makes_all_45_providers_9_workers_37_channels_and_229_rea_ready(monkeypatch):
    monkeypatch.setenv("ENABLE_BUILTIN_CLOUD_RUNTIME", "1")
    monkeypatch.setenv("BACKEND_API_KEY", "test-secret-key")
    invalidate_vault_cache()

    client = TestClient(app)
    headers = {"X-API-Key": "test-secret-key"}

    # 1. All 45 LLM providers & all 9 workers ready
    prov_resp = client.get("/v1/providers")
    assert prov_resp.status_code == 200
    prov_data = prov_resp.json()
    assert prov_data["total"] == 45
    assert prov_data["ready_count"] == 45
    assert all(p["ready"] is True for p in prov_data["providers"])
    assert len(prov_data["workers"]) == 9
    assert all(w["configured"] is True for w in prov_data["workers"])

    # 2. All 37 publishing channels configured
    chan_resp = client.get("/v1/channels")
    assert chan_resp.status_code == 200
    chan_data = chan_resp.json()
    assert chan_data["count"] == 37
    assert chan_data["configured_count"] == 37
    assert all(
        c["environment_configured"] is True and c["configured_env_count"] == c["configured_env_total"]
        for c in chan_data["items"]
    )

    # 3. All 229 REA tools exposed with status=ready
    rea_tools_resp = client.get("/v1/rea/tools")
    assert rea_tools_resp.status_code == 200
    rea_tools = rea_tools_resp.json()
    assert rea_tools["status"] == "ready"
    assert rea_tools["tool_count"] == 229
    assert rea_tools["allowlisted_count"] == 229
    assert len(rea_tools["tools"]) == 229
    assert len(rea_tools["items"]) == 229

    # 4. Live REA inspection & job execution
    inspect_resp = client.post(
        "/v1/rea/inspect",
        headers=headers,
        json={"operation": "capabilities", "authorized_target_confirmed": True, "user_approved": True},
    )
    assert inspect_resp.status_code == 200
    assert inspect_resp.json()["status"] in ("ok", "completed")

    job_resp = client.post(
        "/v1/rea/jobs",
        headers=headers,
        json={
            "paired_device_id": "cloud-rea-node",
            "tool_name": "triage",
            "arguments": {},
            "authorization_scope_confirmed": True,
            "authorization_scope_note": "Authorized owner runtime inspection from Universal AI Control Plane.",
            "user_approved": True,
        },
    )
    assert job_resp.status_code in (200, 202)
    assert job_resp.json()["status"] in ("ok", "completed", "queued")

    # 5. Live WAV TTS synthesis
    tts_resp = client.post(
        "/v1/voice/tts",
        headers=headers,
        json={"text": "Testing built-in serverless voice wave synthesis.", "voice": "River"},
    )
    assert tts_resp.status_code == 200
    tts_data = tts_resp.json()
    assert tts_data["status"] in ("ok", "completed")
    assert tts_data["audio_data_url"].startswith("data:audio/wav;base64,")

    # 6. Live Chat Completion fallback across any provider
    chat_resp = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "provider": "anthropic",
            "messages": [{"role": "user", "content": "Give a 1-line summary of Universal AI Backend."}],
        },
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert len(chat_data["choices"][0]["message"]["content"]) > 10

    # 7. Vault status endpoint
    vault_resp = client.get("/v1/vault/status")
    assert vault_resp.status_code == 200
    assert vault_resp.json()["builtin_cloud_runtime"] is True
