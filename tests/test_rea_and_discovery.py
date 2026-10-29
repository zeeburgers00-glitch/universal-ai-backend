import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.providers import PROVIDERS


client = TestClient(app)


def test_root_explorer_and_catalog_stats_expose_full_expansion():
    root = client.get("/").json()
    assert root["explorer"] == "/explorer"
    assert root["rea_status"] == "/v1/rea/status"
    assert root["rea_tools"] == "/v1/rea/tools"
    assert root["rea_inspect"] == "/v1/rea/inspect"
    assert root["discovery_categories"] == "/v1/discover/categories"

    explorer_resp = client.get("/explorer")
    assert explorer_resp.status_code == 200
    assert "Universal AI Backend" in explorer_resp.text
    assert "/v1/catalog/stats" in explorer_resp.text

    stats = client.get("/v1/catalog/stats").json()
    assert stats["total_tools"] >= 6000
    assert stats["separate_manifests"]["rea_mcp_tools"] >= 200
    assert stats["separate_manifests"]["mcp_ecosystem_records"] >= 1700


def test_providers_manifest_matches_runtime_adapter_registry():
    resp = client.get("/v1/models/providers").json()
    assert resp["total"] == len(PROVIDERS)
    assert resp["total"] >= 45
    manifest_ids = {item["id"] for item in resp["items"]}
    assert manifest_ids == set(PROVIDERS.keys())
    for required in ("openai", "anthropic", "gemini", "xai", "groq", "deepseek", "moonshot", "zhipu", "nvidia-nim", "ollama", "vllm"):
        assert required in manifest_ids


def test_rea_status_and_rea_tools_search():
    status = client.get("/v1/rea/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["package_name"] == "rea-agents"
    assert payload["repository_url"] == "https://github.com/morluto/rea"
    assert payload["counts"]["mcp_tools"] >= 200
    assert len(payload["ai_workflow_highlights"]) >= 5
    assert len(payload["discovery_evidence_runs"]) >= 3

    ai_only = client.get("/v1/rea/tools", params={"ai_only": True}).json()
    assert ai_only["total"] >= 5
    names = {item["name"] for item in ai_only["items"]}
    assert "inspect_model_artifact" in names
    assert "discover_webmcp_tools" in names
    assert "export_environment_bundle" in names

    webmcp = client.get("/v1/rea/tools", params={"q": "webmcp"}).json()
    assert webmcp["total"] >= 1


def test_rea_inspect_endpoint_enforces_auth_authorization_and_approval(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-secret-key-12345")
    headers = {"X-API-Key": "test-secret-key-12345"}

    # Missing authorized_target_confirmed -> 400
    r1 = client.post("/v1/rea/inspect", json={"operation": "capabilities"}, headers=headers)
    assert r1.status_code == 400

    # Missing user_approved -> 409
    r2 = client.post(
        "/v1/rea/inspect",
        json={"operation": "capabilities", "authorized_target_confirmed": True, "user_approved": False},
        headers=headers,
    )
    assert r2.status_code == 409

    # Target operation without target_path -> 400
    r3 = client.post(
        "/v1/rea/inspect",
        json={"operation": "inspect-model-artifact", "authorized_target_confirmed": True, "user_approved": True},
        headers=headers,
    )
    assert r3.status_code == 400

    # Valid request when REA worker is unconfigured -> 503
    r4 = client.post(
        "/v1/rea/inspect",
        json={"operation": "capabilities", "authorized_target_confirmed": True, "user_approved": True},
        headers=headers,
    )
    assert r4.status_code == 503


def test_rea_worker_path_confinement(tmp_path, monkeypatch):
    workers_dir = str(Path(__file__).resolve().parents[1] / "workers")
    if workers_dir not in sys.path:
        sys.path.insert(0, workers_dir)
    monkeypatch.setenv("REA_ALLOWED_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("REA_WORKER_API_KEY", "worker-secret-999")
    (tmp_path / "model.gguf").write_bytes(b"GGUF")

    from rea_worker.app import app as rea_worker_app, resolve_safe_target

    resolved = resolve_safe_target("model.gguf")
    assert resolved == str((tmp_path / "model.gguf").resolve())

    wclient = TestClient(rea_worker_app)
    bad = wclient.post(
        "/v1/rea/inspect",
        headers={"Authorization": "Bearer worker-secret-999"},
        json={
            "task_id": "task_12345678",
            "operation": "inspect-model-artifact",
            "target_path": "../outside.gguf",
            "authorized_target_confirmed": True,
            "user_approved": True,
            "dry_run": True,
        },
    )
    assert bad.status_code == 400

    ok = wclient.post(
        "/v1/rea/inspect",
        headers={"Authorization": "Bearer worker-secret-999"},
        json={
            "task_id": "task_12345678",
            "operation": "inspect-model-artifact",
            "target_path": "model.gguf",
            "authorized_target_confirmed": True,
            "user_approved": True,
            "dry_run": True,
        },
    )
    assert ok.status_code == 202
    assert ok.json()["status"] == "dry_run_validated"


def test_tools_filtering_by_mcp_stars_and_language():
    mcp_res = client.get("/v1/tools", params={"category": "mcp-servers", "limit": 20}).json()
    assert mcp_res["total"] >= 1700
    assert any("rea" in item["id"] for item in mcp_res["items"])

    starred = client.get("/v1/tools", params={"min_stars": 50000, "limit": 50}).json()
    assert starred["total"] >= 10
    assert all((item.get("stars_snapshot") or 0) >= 50000 for item in starred["items"])

    py_tools = client.get("/v1/tools", params={"language": "Python", "limit": 20}).json()
    assert py_tools["total"] >= 100
    assert all(item.get("primary_language") == "Python" for item in py_tools["items"])


def test_discover_categories_endpoint():
    resp = client.get("/v1/discover/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_presets"] >= 30
    preset_ids = {item["id"] for item in data["presets"]}
    assert "mcp-servers" in preset_ids
    assert "ai-agents" in preset_ids
    assert "reverse-engineering-ai" in preset_ids
    assert "local-edge-ai" in preset_ids
    assert "education-learning-ai" in preset_ids


def test_base44_integration_routes_and_generated_sdk(monkeypatch):
    status = client.get("/v1/integrations/base44/status")
    assert status.status_code == 200
    assert status.json()["integration"] == "base44"
    assert "tools" in status.json()["supported_actions"]
    assert "rea_tools" in status.json()["supported_actions"]

    sdk = client.get("/v1/integrations/base44/sdk")
    assert sdk.status_code == 200
    sdk_json = sdk.json()
    assert sdk_json["backend_function_name"] == "universalAiBackend"
    assert "createClientFromRequest" in sdk_json["backend_function_entry"]
    assert "UNIVERSAL_AI_BACKEND_URL" in sdk_json["backend_function_entry"]
    assert "universalAiBackend" in sdk_json["frontend_sdk_code"]
    assert "UniversalAiHub" in sdk_json["hub_page_code"]

    # Auth required for listing/connecting Base44 apps
    monkeypatch.setenv("BACKEND_API_KEY", "test-secret-key-for-base44-routes")
    unauth = client.get("/v1/integrations/base44/apps")
    assert unauth.status_code == 401

