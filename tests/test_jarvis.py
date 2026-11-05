"""JARVIS: memory, intent routing, tool execution, honesty, and the model upgrade path."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import agents, ai_router, jarvis
from app.main import app

HEADERS = {"X-API-Key": "jarvis-key"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_API_KEY", "jarvis-key")
    monkeypatch.setenv("UAI_JOBS_DISABLE", "1")
    jarvis.init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


# --- memory -------------------------------------------------------------------

def test_facts_persist_and_update():
    jarvis.remember("name", "Ali")
    assert jarvis.facts()[0]["value"] == "Ali"
    jarvis.remember("name", "Ali Khan")   # same key updates, no duplicate
    entries = [item for item in jarvis.facts() if item["key"] == "name"]
    assert len(entries) == 1 and entries[0]["value"] == "Ali Khan"


def test_facts_survive_a_new_connection():
    jarvis.remember("project", "universal-ai-backend")
    # A fresh connection is what a restarted process gets.
    assert any(item["key"] == "project" for item in jarvis.facts())


def test_forget_removes_only_that_fact():
    jarvis.remember("a", "1")
    jarvis.remember("b", "2")
    assert jarvis.forget("a")["removed"] == 1
    assert [item["key"] for item in jarvis.facts()] == ["b"]


def test_empty_facts_are_rejected():
    with pytest.raises(ValueError):
        jarvis.remember("", "value")
    with pytest.raises(ValueError):
        jarvis.remember("key", "   ")


def test_history_is_per_session():
    jarvis.add_episode("user", "hello", session="one")
    jarvis.add_episode("user", "hello", session="two")
    assert len(jarvis.history(session="one")) == 1


def test_recall_finds_the_relevant_memory():
    jarvis.remember("editor", "premiere pro")
    jarvis.remember("camera", "canon m50")
    hits = jarvis.recall("which camera do I use")
    assert hits and hits[0]["text"].lower().find("canon") >= 0


# --- learning from plain sentences --------------------------------------------

def test_extracts_name_and_preferences():
    facts = jarvis.extract_facts("mera naam Ali hai aur mujhe ffmpeg pasand hai")
    keys = {fact["key"] for fact in facts}
    assert "name" in keys
    assert any(fact["value"].lower() == "ali" for fact in facts if fact["key"] == "name")


def test_extracts_english_facts_and_notes():
    facts = jarvis.extract_facts("Remember: publish every Tuesday. My name is Sam.")
    values = {fact["key"]: fact["value"] for fact in facts}
    assert values.get("name", "").lower().startswith("sam")
    assert any("tuesday" in item["value"].lower() for item in facts)


def test_no_facts_invented_from_a_plain_request():
    assert jarvis.extract_facts("live_demo.mp4 ke chapters banao") == []


# --- intent routing -----------------------------------------------------------

def test_routes_a_video_request_with_its_file():
    steps = jarvis.detect_intents("live_demo.mp4 ke chapters banao")
    assert steps and steps[0]["agent"] == "chapter-writer"
    assert steps[0]["input"]["path"] == "live_demo.mp4"


def test_routes_ops_and_content_requests():
    assert jarvis.detect_intents("backup lo")[0]["agent"] == "backup-keeper"
    assert jarvis.detect_intents("health batao")[0]["agent"] == "health-warden"
    assert jarvis.detect_intents("seo tags banao: ffmpeg")[0]["agent"] == "seo-planner"


def test_file_request_without_a_file_falls_through():
    assert jarvis.detect_intents("silence cut karo") == []


def test_unknown_request_routes_nothing():
    assert jarvis.detect_intents("tell me a joke about cats") == []


def test_routing_caps_at_four_steps():
    steps = jarvis.detect_intents("health batao aur backup lo aur metrics dikhao aur disk check karo")
    assert len(steps) <= 4


# --- chat ---------------------------------------------------------------------

def test_chat_learns_and_says_so():
    reply = jarvis.chat("mera naam Ali hai")
    assert "Yaad rakh liya" in reply["reply"]
    assert reply["learned"]
    assert any(item["key"] == "name" for item in jarvis.facts())


def test_chat_answers_memory_questions():
    jarvis.remember("name", "Ali")
    reply = jarvis.chat("kya yaad hai?")
    assert reply["intent"] == "memory"
    assert "Ali" in reply["reply"]


def test_chat_runs_a_real_tool():
    reply = jarvis.chat("health batao")
    assert reply["intent"] == "health"
    assert reply["actions"] and reply["actions"][0]["agent"] == "health-warden"
    assert "Health Warden" in reply["reply"]


def test_dry_run_plans_without_running():
    reply = jarvis.chat("health batao", dry_run=True)
    assert reply["actions"] == []
    assert "Health Warden" in reply["reply"]


def test_chat_reports_failures_honestly():
    reply = jarvis.chat("missing_file.mp4 ka chapters banao")
    assert reply["actions"][0]["ok"] is False
    assert "nahi ho paya" in reply["reply"]


def test_unknown_request_lists_real_capabilities():
    reply = jarvis.chat("tell me a joke")
    assert reply["intent"] == "unknown"
    assert any(name in reply["reply"] for name in ("backup-keeper", "health-warden", "seo-planner"))
    assert reply["used_model"] is False


def test_chat_never_pretends_to_have_used_a_model():
    reply = jarvis.chat("health batao")
    assert reply["used_model"] is False
    assert reply["model"] is None


# --- the free model upgrade path ---------------------------------------------

def test_model_is_used_when_a_provider_exists(monkeypatch):
    monkeypatch.setattr(ai_router, "chain", lambda: [object()])
    monkeypatch.setattr(
        ai_router, "complete",
        lambda **kwargs: {"text": "Sab theek hai, boss.", "provider": "ollama", "model": "llama3.1:8b"},
    )
    reply = jarvis.chat("kya haal hai")
    assert reply["used_model"] is True
    assert reply["reply"] == "Sab theek hai, boss."
    assert reply["model"]["provider"] == "ollama"


def test_broken_model_configuration_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(ai_router, "chain", lambda: (_ for _ in ()).throw(RuntimeError("bad config")))
    reply = jarvis.chat("health batao")
    assert reply["used_model"] is False
    assert reply["actions"], "tools must still run without a model"


def test_model_that_returns_nothing_falls_back(monkeypatch):
    monkeypatch.setattr(ai_router, "chain", lambda: [object()])
    monkeypatch.setattr(ai_router, "complete", lambda **kwargs: {"text": "  "})
    reply = jarvis.chat("health batao")
    assert reply["used_model"] is False
    assert "Health Warden" in reply["reply"]


# --- HTTP ---------------------------------------------------------------------

def test_endpoints_require_a_key(client):
    assert client.post("/v1/jarvis/chat", json={"message": "hi"}).status_code == 401


def test_chat_over_http(client):
    body = client.post("/v1/jarvis/chat", headers=HEADERS, json={"message": "health batao"}).json()
    assert body["intent"] == "health"
    assert body["available_agents"] >= 38


def test_memory_over_http(client):
    client.post("/v1/jarvis/memory", headers=HEADERS, json={"key": "goal", "value": "1000 subs"})
    listing = client.get("/v1/jarvis/memory", headers=HEADERS).json()
    assert any(item["key"] == "goal" for item in listing["facts"])
    found = client.get("/v1/jarvis/memory", params={"q": "subs"}, headers=HEADERS).json()
    assert found["results"]


def test_forget_over_http(client):
    client.post("/v1/jarvis/memory", headers=HEADERS, json={"key": "temp", "value": "x"})
    assert client.delete("/v1/jarvis/memory/temp", headers=HEADERS).json()["removed"] == 1


def test_plan_over_http_does_not_execute(client):
    body = client.post("/v1/jarvis/plan", headers=HEADERS, json={"goal": "video.mp4 publish karo"}).json()
    assert body["steps"][0]["agent"] == "publish-packager"
    assert "nothing was executed" in body["note"]


def test_history_over_http(client):
    client.post("/v1/jarvis/chat", headers=HEADERS, json={"message": "health batao", "session": "web"})
    history = client.get("/v1/jarvis/history", params={"session": "web"}, headers=HEADERS).json()
    assert history["count"] >= 2
    assert history["turns"][0]["role"] == "user"


def test_status_over_http(client):
    body = client.get("/v1/jarvis/status", headers=HEADERS).json()
    assert body["agents"] >= 38
    assert "configured" in body["model"]


def test_chat_is_audited(client):
    client.post("/v1/jarvis/chat", headers=HEADERS, json={"message": "health batao"})
    log = client.get("/v1/governance/audit", params={"action": "jarvis.chat"}, headers=HEADERS).json()
    assert log["count"] >= 1
    assert "jarvis-key" not in json.dumps(log)


def test_jarvis_agents_are_listed_in_the_registry(client):
    listing = client.get("/v1/agents/runtime", headers=HEADERS).json()
    ids = {entry["id"] for entry in listing["agents"]}
    assert {"jarvis-chat", "memory-keeper", "goal-planner"} <= ids
    assert len(agents.AGENTS) >= 40
