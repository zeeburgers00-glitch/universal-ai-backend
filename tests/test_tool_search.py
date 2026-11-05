"""BM25 search over the repo catalog and the live route table."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import tool_search
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "search-key")
    with TestClient(app) as test_client:
        yield test_client


HEADERS = {"X-API-Key": "search-key"}


# --- ranker -------------------------------------------------------------------

def test_tokenizer_drops_stopwords():
    assert tool_search.tokenize("how do I scrape the web?") == ["scrape", "web"]


def test_idf_favours_rare_terms():
    ranker = tool_search.BM25([["video", "edit"], ["video", "cut"], ["video", "encode"]])
    assert ranker.idf("encode") > ranker.idf("video")


def test_ranking_puts_the_rare_match_first():
    ranker = tool_search.BM25([
        ["video", "video", "video"],
        ["video", "silence", "cut"],
    ])
    results = ranker.search("cut silence")
    assert results[0]["index"] == 1
    assert results[0]["coverage"] == 1.0


def test_scores_are_sorted_and_limited():
    ranker = tool_search.BM25([["video", "audio"], ["video"], ["text"]])
    results = ranker.search("video audio", limit=2)
    assert len(results) == 2
    assert results[0]["score"] >= results[1]["score"]


def test_empty_query_returns_nothing():
    assert tool_search.BM25([["a"]]).search("   ") == []


# --- catalog search -----------------------------------------------------------

def test_catalog_search_finds_voice_tools():
    result = tool_search.search_tools("text to speech voiceover", limit=5)
    assert result["corpus"] >= 200
    names = [entry["full_name"] for entry in result["results"]]
    assert any("tts" in name.lower() or "voice" in name.lower() or "sherpa" in name.lower() for name in names), names


def test_catalog_search_finds_a_scraper():
    result = tool_search.search_tools("scrape websites crawler", limit=5)
    assert any("crawl" in entry["full_name"].lower() for entry in result["results"])


def test_results_carry_licence_and_integration_flags():
    result = tool_search.search_tools("agent framework", limit=3)
    for entry in result["results"]:
        assert "integration" in entry
        assert entry["integration"] == "reference-only"
        assert "license" in entry
        assert 0 <= entry["coverage"] <= 1


def test_limit_is_respected(client):
    body = client.get("/v1/tools/search", params={"q": "video", "limit": 2}, headers=HEADERS).json()
    assert len(body["results"]) <= 2


# --- route search -------------------------------------------------------------

def test_route_search_finds_the_silence_cutter():
    result = tool_search.search_routes("remove silence", app.openapi(), limit=5)
    assert result["results"][0]["path"].startswith("/v1/video/")


def test_route_search_covers_every_documented_route():
    result = tool_search.search_routes("backup", app.openapi(), limit=50)
    assert result["corpus"] >= 100


def test_route_search_http_surface(client):
    body = client.get("/v1/tools/routes", params={"q": "code review", "limit": 3}, headers=HEADERS).json()
    assert body["count"] >= 1
    assert "/v1/code/review" in json_paths(body)


def json_paths(body):
    return [entry["path"] for entry in body["results"]]


# --- capabilities -------------------------------------------------------------

def test_capabilities_map_matches_the_schema():
    caps = tool_search.capabilities()
    assert caps["total_routes"] >= 130
    assert caps["groups"]["video"]["routes"] >= 10
    assert caps["tools"]["corpus"] >= 200


def test_search_endpoints_require_the_key(client):
    assert client.get("/v1/tools/search", params={"q": "video"}).status_code == 401
    assert client.get("/v1/tools/capabilities").status_code == 401
