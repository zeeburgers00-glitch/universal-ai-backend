from app.registry import Registry


def test_search_filters_catalog():
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


def test_default_registry_loads_multiple_catalogs():
    registry = Registry.from_file()
    assert len(registry.items) >= 200
    assert any(item.get("source_name") for item in registry.items)
    assert any(item.get("commercial_model") for item in registry.items)
