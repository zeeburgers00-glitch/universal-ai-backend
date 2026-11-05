"""The GitHub tool registry must stay real: 100+ verified repos, no hand-typed numbers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import github_registry
from app.main import app

CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "github_repos.json"
REQUIRED_FIELDS = {"full_name", "url", "stars", "license", "categories", "integration", "maps_to"}


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_snapshot_exists_and_is_large_enough(snapshot):
    assert snapshot["total"] >= 100, "owner asked for 100+ tools"
    assert len(snapshot["repos"]) == snapshot["total"]
    assert snapshot["fetched_at"]


def test_every_repo_has_required_fields(snapshot):
    for repo in snapshot["repos"]:
        missing = REQUIRED_FIELDS - set(repo)
        assert not missing, f"{repo.get('full_name')} missing {missing}"
        assert isinstance(repo["stars"], int) and repo["stars"] >= 0
        assert repo["categories"], repo["full_name"]
        assert repo["url"].startswith("https://github.com/")


def test_pinned_repos_requested_by_owner_are_present(snapshot):
    names = {repo["full_name"] for repo in snapshot["repos"]}
    assert "CopilotKit/OpenDots" in names
    assert "cedroid/groq-bot" in names


def test_nothing_claims_to_be_integrated(snapshot):
    """These repos are references. Calling them 'integrated' would be a lie."""

    assert all(repo["integration"] == "reference-only" for repo in snapshot["repos"])
    assert "NOT vendored" in snapshot["disclaimer"]


def test_missing_licences_are_not_hidden(snapshot):
    stats = github_registry.stats()
    assert stats["total"] == snapshot["total"]
    assert stats["without_license"] == sum(1 for r in snapshot["repos"] if not r.get("license"))


def test_every_category_is_populated(snapshot):
    empty = [name for name, members in snapshot["by_category"].items() if not members]
    assert empty == [], f"categories with no repos: {empty}"


def test_search_filters_are_exclusive():
    result = github_registry.search(category="mcp", limit=5)
    assert result["returned"] <= 5
    assert all("mcp" in {c.lower() for c in repo["categories"]} for repo in result["repos"])

    strict = github_registry.search(min_stars=10_000, limit=200)
    assert all(repo["stars"] >= 10_000 for repo in strict["repos"])


def test_registry_endpoints_respond():
    with TestClient(app) as client:
        stats = client.get("/v1/discover/github/registry/stats")
        assert stats.status_code == 200
        assert stats.json()["total"] >= 100

        page = client.get("/v1/discover/github/registry", params={"category": "agents", "limit": 3})
        assert page.status_code == 200
        assert page.json()["returned"] <= 3

        one = client.get("/v1/discover/github/registry/CopilotKit/OpenDots")
        assert one.status_code == 200
        assert one.json()["maps_to"]

        missing = client.get("/v1/discover/github/registry/nope/nothing-here")
        assert missing.status_code == 404
