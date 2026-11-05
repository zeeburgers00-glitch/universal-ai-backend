from __future__ import annotations

import asyncio
import json
import os

from fastapi.testclient import TestClient

from app.main import app
import app.openavatar as openavatar_module


os.environ.setdefault("BACKEND_API_KEY", "test-openavatar-agents-key")
client = TestClient(app)
API_HEADERS = {"X-API-Key": "test-openavatar-agents-key"}


def test_openavatar_fleet_contains_120_task_scoped_agents():
    response = client.get("/v1/openavatar/fleet")
    assert response.status_code == 200
    fleet = response.json()
    assert fleet["agent_slots"] == 120
    assert fleet["department_count"] == 12
    assert fleet["workflow_count"] == 12
    assert fleet["worker"]["service"] == "agents"
    assert "not 120 always-running" in fleet["note"]
    assert fleet["no_card_policy"]["paid_provider_fallback"] is False


def test_openavatar_agents_are_filterable_and_have_security_metadata():
    response = client.get("/v1/openavatar/agents?department=voice&limit=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 10
    assert all(item["department_id"] == "voice" for item in payload["items"])
    clone_auditor = next(item for item in payload["items"] if item["id"] == "oa-voice-clone-consent-auditor")
    assert clone_auditor["risk_level"] == "critical"
    assert clone_auditor["requires_human_approval"] is True
    assert "no_secret_in_prompt" in clone_auditor["security_baseline"]


def test_openavatar_workflows_reference_real_agent_ids():
    workflows = client.get("/v1/openavatar/workflows").json()["items"]
    agents = {item["id"] for item in client.get("/v1/openavatar/agents?limit=200").json()["items"]}
    assert len(workflows) == 12
    assert all(set(workflow["agent_ids"]).issubset(agents) for workflow in workflows)


def test_agent_dispatch_is_disabled_until_no_card_worker_is_attested(monkeypatch):
    called = False

    async def fake_post_worker(service, path, payload, timeout_seconds=90):
        nonlocal called
        called = True
        return 202, "application/json", b'{}'

    monkeypatch.setattr(openavatar_module, "post_worker", fake_post_worker)
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    monkeypatch.delenv("OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED", raising=False)
    response = client.post(
        "/v1/openavatar/agents/oa-avatar-scriptwriter/run",
        headers=API_HEADERS,
        json={"objective": "Draft narration", "dry_run": True},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "blocked_no_card_gate"
    assert called is False


def test_agent_planning_requires_api_key_and_is_planning_only(monkeypatch):
    calls = []

    async def fake_post_worker(service, path, payload, timeout_seconds=90):
        calls.append((service, path, payload))
        return 202, "application/json", b'{"task_id":"plan-1","status":"accepted"}'

    monkeypatch.setattr(openavatar_module, "post_worker", fake_post_worker)
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    monkeypatch.setenv("OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED", "true")
    denied = client.post("/v1/openavatar/plan", json={"objective": "Plan a talking avatar video"})
    assert denied.status_code == 401
    response = client.post(
        "/v1/openavatar/plan",
        headers=API_HEADERS,
        json={"objective": "Plan a talking avatar video"},
    )
    assert response.status_code == 200
    assert calls[0][0:2] == ("agents", "/v1/agents/run")
    inputs = calls[0][2]["inputs"]
    assert inputs["planning_only"] is True
    assert inputs["do_not_dispatch_subagents"] is True
    assert inputs["studio_policy"]["no_paid_provider_fallback"] is True
    assert calls[0][2]["dry_run"] is True


def test_individual_agent_dispatch_routes_to_shared_agent_worker(monkeypatch):
    calls = []

    async def fake_post_worker(service, path, payload, timeout_seconds=90):
        calls.append(payload)
        return 202, "application/json", b'{"worker_task_id":"agent-task-1"}'

    monkeypatch.setattr(openavatar_module, "post_worker", fake_post_worker)
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    monkeypatch.setenv("OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED", "true")
    response = client.post(
        "/v1/openavatar/agents/oa-avatar-scriptwriter/run",
        headers=API_HEADERS,
        json={"objective": "Draft a 60-second avatar narration script", "dry_run": True},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert calls[0]["agent"]["id"] == "oa-avatar-scriptwriter"
    assert calls[0]["inputs"]["studio"] == "openavatar"


def test_high_risk_agent_requires_approval_for_live_execution(monkeypatch):
    called = False

    async def fake_post_worker(service, path, payload, timeout_seconds=90):
        nonlocal called
        called = True
        return 202, "application/json", b'{}'

    monkeypatch.setattr(openavatar_module, "post_worker", fake_post_worker)
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    monkeypatch.setenv("OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED", "true")
    response = client.post(
        "/v1/openavatar/agents/oa-voice-clone-consent-auditor/run",
        headers=API_HEADERS,
        json={"objective": "Prepare a voice clone", "dry_run": False, "user_approved": False},
    )
    assert response.status_code == 409
    assert called is False


def test_team_dispatch_accepts_100_agents_with_bounded_parallelism(monkeypatch):
    active = 0
    peak = 0
    calls = 0

    async def fake_post_worker(service, path, payload, timeout_seconds=90):
        nonlocal active, peak, calls
        assert service == "agents"
        assert path == "/v1/agents/run"
        active += 1
        calls += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return 202, "application/json", json.dumps({"accepted": payload["agent_id"]}).encode()

    monkeypatch.setattr(openavatar_module, "post_worker", fake_post_worker)
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    monkeypatch.setenv("OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED", "true")
    monkeypatch.setenv("OPENAVATAR_MAX_PARALLEL_AGENTS", "3")
    fleet = client.get("/v1/openavatar/agents?limit=200").json()["items"]
    ids = [agent["id"] for agent in fleet[:100]]
    response = client.post(
        "/v1/openavatar/teams/run",
        headers=API_HEADERS,
        json={
            "objective": "Review the avatar video production plan",
            "agent_ids": ids,
            "max_parallel": 10,
            "dry_run": True,
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["selected_agents"] == 100
    assert payload["accepted"] == 100
    assert payload["max_parallel"] == 3
    assert calls == 100
    assert peak <= 3


def test_team_dispatch_rejects_duplicate_or_unknown_agent_ids(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    duplicate = client.post(
        "/v1/openavatar/teams/run",
        headers=API_HEADERS,
        json={"objective": "Review video", "agent_ids": ["oa-openavatar-chief-orchestrator"] * 2},
    )
    assert duplicate.status_code == 422
    unknown = client.post(
        "/v1/openavatar/teams/run",
        headers=API_HEADERS,
        json={"objective": "Review video", "agent_ids": ["not-a-real-agent"]},
    )
    assert unknown.status_code == 404


def test_team_dispatch_blocks_unapproved_live_high_risk_work(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-openavatar-agents-key")
    response = client.post(
        "/v1/openavatar/teams/run",
        headers=API_HEADERS,
        json={
            "objective": "Approve a public avatar release",
            "agent_ids": ["oa-approved-release-coordinator", "oa-openavatar-chief-orchestrator"],
            "dry_run": False,
            "user_approved": False,
        },
    )
    assert response.status_code == 409
    assert "approval_required_agents" in response.json()["detail"]
