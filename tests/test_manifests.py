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
