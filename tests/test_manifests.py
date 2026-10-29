import json
from pathlib import Path

from app.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"


def _read_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_registry_search_filters_catalog():
    registry = Registry([
        {"id": "voice-1", "name": "Voice Agent", "category": "audio", "capabilities": ["speech-to-text"]},
        {"id": "browser-1", "name": "Browser Agent", "category": "browser", "capabilities": ["browser-control"]},
    ])
    assert len(registry.list(q="voice")) == 1
    assert registry.list(category="audio")[0]["id"] == "voice-1"
    assert registry.list(capability="browser-control")[0]["id"] == "browser-1"


def test_duplicate_registration_rejected():
    registry = Registry([{"id": "same", "name": "Existing"}])
    try:
        registry.add({"id": "same", "name": "Duplicate"})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate ID should fail")


def test_license_status_and_source_classification_filters():
    registry = Registry([
        {"id": "a", "license_status": "review_required", "source_classification": "candidate_open_source"},
        {"id": "b", "license_status": "verified", "source_classification": "source_available"},
    ])
    assert [x["id"] for x in registry.list(license_status="review_required")] == ["a"]
    assert [x["id"] for x in registry.list(source_classification="candidate")] == ["a"]


def test_default_registry_loads_expanded_catalogs():
    registry = Registry.from_file()
    assert len(registry.items) >= 3000
    assert any(item.get("source_name") for item in registry.items)
    assert any(item.get("commercial_model") for item in registry.items)
    assert any(item.get("category") == "voice-cloning" for item in registry.items)
    assert any(item.get("category") == "mcp-servers" for item in registry.items)
    assert registry.get("mcp-morluto-rea") is not None


def test_registry_repository_urls_are_unique_after_merge():
    registry = Registry.from_file()
    urls = [
        item["repository_url"].lower().rstrip("/").removesuffix(".git")
        for item in registry.items
        if item.get("repository_url")
    ]
    assert len(urls) == len(set(urls))


def test_all_manifests_are_valid_json_and_have_unique_ids():
    manifest_names = [
        "tools.json", "extended.json", "commercial.json", "llmops.json",
        "voice_media.json", "mcp_ecosystem.json", "global_ai_directory.json",
        "channels.json", "workflows.json", "agents.json",
        "provider_capabilities.json", "sources.json", "rea_mcp_tools.json",
    ]
    for name in manifest_names:
        data = _read_json(CATALOG / name)
        if name == "sources.json":
            assert isinstance(data.get("sources"), list)
            continue
        if name == "rea_mcp_tools.json":
            tools = data.get("tools", [])
            assert len(tools) >= 200
            tool_ids = [item.get("id") for item in tools]
            assert len(tool_ids) == len(set(tool_ids))
            continue
        assert isinstance(data, list), name
        ids = [item.get("id") for item in data]
        assert all(isinstance(value, str) and value for value in ids), name
        assert len(ids) == len(set(ids)), name



def test_creator_and_jarvis_workflows_are_approval_gated():
    workflows = _read_json(CATALOG / "workflows.json")
    by_id = {workflow["id"]: workflow for workflow in workflows}
    for workflow_id in [
        "youtube-shorts-factory", "youtube-longform", "voice-clone-narration",
        "faceless-channel-pipeline", "jarvis-windows-control", "social-repurpose",
    ]:
        assert workflow_id in by_id
        assert by_id[workflow_id]["requires_human_approval"] is True


def test_high_impact_agents_have_approval_rules():
    agents = _read_json(CATALOG / "agents.json")
    high_impact = [agent for agent in agents if agent.get("risk_level") == "critical"]
    assert high_impact
    assert all(agent.get("human_approval_rules") for agent in high_impact)
    assert all("least_privilege" in agent.get("security_baseline", []) for agent in agents)


def test_f5_tts_has_separate_model_license_warning():
    entries = _read_json(CATALOG / "voice_media.json")
    f5 = next(item for item in entries if item["id"] == "media-f5-tts")
    assert "CC-BY-NC" in f5["license"]
    assert f5["license_status"] == "review_required"
    assert f5["deployment_target"] == "gpu-worker"


def test_channel_manifest_does_not_claim_every_connector_is_live():
    channels = _read_json(CATALOG / "channels.json")
    assert len(channels) >= 25
    assert all(item.get("integration_status") == "manifest_only" for item in channels)


def test_control_plane_imports_and_exposes_worker_and_base44_routes():
    from app.main import app

    paths = {route.path for route in app.routes}
    required = {
        "/health",
        "/explorer",
        "/v1/runtime/capabilities",
        "/v1/models/providers",
        "/v1/voice/providers",
        "/v1/voice/tts",
        "/v1/voice/clone",
        "/v1/media/jobs",
        "/v1/workflows/{workflow_id}/run",
        "/v1/agents/{agent_id}/run",
        "/v1/channels/{channel_id}/actions",
        "/v1/youtube/publish",
        "/v1/desktop/actions",
        "/v1/rea/status",
        "/v1/rea/tools",
        "/v1/rea/inspect",
        "/v1/rea/jobs",
        "/v1/integrations/base44/status",
        "/v1/integrations/base44/sdk",
        "/v1/integrations/base44/apps",
        "/v1/integrations/base44/connect",
        "/v1/discover/github",
    }
    assert required.issubset(paths)


def test_worker_compose_is_valid_yaml():
    import yaml

    with (ROOT / "workers" / "docker-compose.yml").open("r", encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)
    assert {
        "redis", "voice-api", "voice-runner", "media-api", "media-runner",
        "youtube-api", "youtube-runner", "channel-api", "agent-api", "agent-runner",
        "automation-api", "automation-runner", "rea-api", "rea-runner",
    }.issubset(set(compose["services"]))
    assert compose["services"]["redis"]["environment"]["REDIS_PASSWORD"].startswith("${REDIS_PASSWORD:")


def test_rea_tool_agent_and_workflow_are_cataloged():
    registry = Registry.from_file()
    rea = registry.get("github-morluto-rea")
    assert rea is not None
    assert rea["repository_url"] == "https://github.com/morluto/rea"
    assert rea["integration_type"] == "optional-local-mcp-stdio"
    assert "reverse-engineering" in rea["capabilities"]

    agents = _read_json(CATALOG / "agents.json")
    rea_agent = next(item for item in agents if item["id"] == "reverse-engineering-agent")
    assert rea_agent["worker_service"] == "DESKTOP_AGENT_URL"
    assert rea_agent["risk_level"] == "high"

    workflows = _read_json(CATALOG / "workflows.json")
    rea_workflow = next(item for item in workflows if item["id"] == "authorized-app-reverse-engineering")
    assert rea_workflow["requires_human_approval"] is True
    assert "rea-mcp" in rea_workflow["required_services"]


def test_rea_path_scope_blocks_targets_outside_configured_root(monkeypatch, tmp_path):
    import pytest
    from workers.windows_agent.rea_mcp import ReaBridgeError, _validate_argument_scope

    allowed = tmp_path / "authorized"
    outside = tmp_path / "private"
    allowed.mkdir()
    outside.mkdir()
    approved_target = allowed / "owned-app.exe"
    approved_target.write_bytes(b"test")
    denied_target = outside / "other-app.exe"
    denied_target.write_bytes(b"test")
    monkeypatch.setenv("REA_ALLOWED_TARGET_ROOTS", str(allowed))
    _validate_argument_scope({"file_path": str(approved_target)})
    with pytest.raises(ReaBridgeError, match="outside"):
        _validate_argument_scope({"file_path": str(denied_target)})

