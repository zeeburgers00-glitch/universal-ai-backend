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
