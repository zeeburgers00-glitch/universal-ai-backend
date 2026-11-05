from __future__ import annotations

import os
from fastapi.testclient import TestClient

from app.main import app
from workers.agent_runtime.worker import _secure_service_url, execute_one


client = TestClient(app)
HEADERS = {"X-API-Key": "test-agent-runtime-key"}


def _configure(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_RUNTIME_DB_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setenv("BACKEND_API_KEY", "test-agent-runtime-key")
    monkeypatch.setenv("AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED", "true")


def test_runtime_status_and_auth(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    assert client.get("/v1/agent-runtime/status").status_code == 401
    response = client.get("/v1/agent-runtime/status", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["no_card_only"] is True
    assert response.json()["paid_provider_fallback"] is False


def test_enqueue_idempotency_and_secret_rejection(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    payload = {"objective": "Research this topic", "idempotency_key": "same-task-key-001"}
    first = client.post("/v1/agent-runtime/tasks", headers=HEADERS, json=payload)
    second = client.post("/v1/agent-runtime/tasks", headers=HEADERS, json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]
    rejected = client.post(
        "/v1/agent-runtime/tasks", headers=HEADERS,
        json={"objective": "Run agent safely", "inputs": {"api_key": "never-store-this"}},
    )
    assert rejected.status_code == 422


def test_worker_claim_requires_no_card_attestation(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_RUNTIME_WORKER_NO_CARD_CONFIRMED", "false")
    client.post("/v1/agent-runtime/tasks", headers=HEADERS, json={"objective": "Queued task"})
    response = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"})
    assert response.status_code == 503


def test_claim_heartbeat_complete_lifecycle(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    created = client.post("/v1/agent-runtime/tasks", headers=HEADERS, json={"objective": "Write a project plan"})
    task_id = created.json()["task_id"]
    claimed = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"})
    assert claimed.status_code == 200
    assert claimed.json()["task"]["task_id"] == task_id
    heartbeat = client.post(
        f"/v1/agent-runtime/workers/worker-1/tasks/{task_id}/heartbeat",
        headers=HEADERS, json={"extend_seconds": 120},
    )
    assert heartbeat.status_code == 200
    completed = client.post(
        f"/v1/agent-runtime/workers/worker-1/tasks/{task_id}/complete",
        headers=HEADERS, json={"result": {"answer": "done"}},
    )
    assert completed.status_code == 200
    assert client.get(f"/v1/agent-runtime/tasks/{task_id}", headers=HEADERS).json()["status"] == "succeeded"
    assert len(client.get(f"/v1/agent-runtime/tasks/{task_id}/events", headers=HEADERS).json()["items"]) >= 4


def test_high_risk_task_waits_for_human_approval(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    task = client.post(
        "/v1/agent-runtime/tasks", headers=HEADERS,
        json={"objective": "Publish this video publicly", "risk_level": "critical"},
    ).json()
    assert task["status"] == "pending_approval"
    claim = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"})
    assert claim.json()["task"] is None
    decision = client.post(
        f"/v1/agent-runtime/approvals/{task['approval_id']}/decision",
        headers=HEADERS, json={"decision": "approved", "note": "Reviewed by operator"},
    )
    assert decision.status_code == 200
    claimed = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"})
    assert claimed.json()["task"]["task_id"] == task["task_id"]


def test_workflow_dag_respects_dependencies(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/v1/agent-runtime/workflows", headers=HEADERS,
        json={"name": "research then write", "steps": [
            {"id": "research", "objective": "Research the topic"},
            {"id": "write", "objective": "Write the script", "depends_on": ["research"]},
        ]},
    )
    assert response.status_code == 202, response.text
    workflow = response.json()
    first = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"}).json()["task"]
    assert first["step_key"] == "research"
    second_claim = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-2"}).json()
    assert second_claim["task"] is None
    client.post(
        f"/v1/agent-runtime/workers/worker-1/tasks/{first['task_id']}/complete",
        headers=HEADERS, json={"result": {"summary": "research ready"}},
    )
    next_claim = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-2"}).json()["task"]
    assert next_claim["step_key"] == "write"
    client.post(
        f"/v1/agent-runtime/workers/worker-2/tasks/{next_claim['task_id']}/complete",
        headers=HEADERS, json={"result": {"script": "draft"}},
    )
    assert client.get(f"/v1/agent-runtime/workflows/{workflow['workflow_id']}", headers=HEADERS).json()["status"] == "completed"


def test_workflow_cycle_is_rejected(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/v1/agent-runtime/workflows", headers=HEADERS,
        json={"name": "cyclic", "steps": [
            {"id": "a", "objective": "Do A", "depends_on": ["b"]},
            {"id": "b", "objective": "Do B", "depends_on": ["a"]},
        ]},
    )
    assert response.status_code == 422


def test_retry_exhaustion_and_memory_scope(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    task = client.post(
        "/v1/agent-runtime/tasks", headers=HEADERS,
        json={"objective": "Try it twice", "max_attempts": 2},
    ).json()
    first = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"}).json()["task"]
    assert first["task_id"] == task["task_id"]
    failed = client.post(
        f"/v1/agent-runtime/workers/worker-1/tasks/{task['task_id']}/fail",
        headers=HEADERS, json={"error": "temporary provider error", "retryable": True},
    ).json()
    assert failed["status"] == "queued"
    second = client.post("/v1/agent-runtime/workers/claim", headers=HEADERS, json={"worker_id": "worker-1"}).json()["task"]
    assert second["attempts"] == 2
    final = client.post(
        f"/v1/agent-runtime/workers/worker-1/tasks/{task['task_id']}/fail",
        headers=HEADERS, json={"error": "still failing", "retryable": True},
    ).json()
    assert final["status"] == "failed"
    saved = client.post("/v1/agent-runtime/memory", headers=HEADERS, json={
        "scope": "project-a", "key": "brand-voice", "content": "Clear and friendly",
    })
    assert saved.status_code == 201
    assert client.get("/v1/agent-runtime/memory?scope=project-a", headers=HEADERS).json()["items"][0]["content"] == "Clear and friendly"
    assert client.get("/v1/agent-runtime/memory?scope=project-b", headers=HEADERS).json()["items"] == []


def test_agent_blueprint_risk_cannot_be_downgraded_and_approval_is_recorded(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/v1/agent-runtime/tasks", headers=HEADERS,
        json={"objective": "Prepare a public YouTube upload", "agent_id": "youtube-publisher", "risk_level": "low"},
    )
    assert response.status_code == 202, response.text
    task = response.json()
    assert task["risk_level"] == "critical"
    assert task["status"] == "pending_approval"
    decision = client.post(
        f"/v1/agent-runtime/approvals/{task['approval_id']}/decision",
        headers=HEADERS, json={"decision": "approved", "note": "Reviewed"},
    )
    assert decision.status_code == 200
    refreshed = client.get(f"/v1/agent-runtime/tasks/{task['task_id']}", headers=HEADERS).json()
    assert refreshed["payload"]["user_approved"] is True
    assert refreshed["payload"]["agent"]["id"] == "youtube-publisher"


def test_unknown_agent_blueprint_is_rejected(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/v1/agent-runtime/tasks", headers=HEADERS,
        json={"objective": "Use an unknown agent", "agent_id": "agent-does-not-exist"},
    )
    assert response.status_code == 404


def test_unified_agent_catalog_merges_all_282_blueprints(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = client.get("/v1/agent-runtime/catalog?limit=200", headers=HEADERS)
    assert response.status_code == 200
    first = response.json()
    second = client.get(
        "/v1/agent-runtime/catalog?limit=200&offset=200", headers=HEADERS
    ).json()
    assert first["total"] == 282
    all_items = first["items"] + second["items"]
    assert len({item["id"] for item in all_items}) == 282
    assert {item["source"] for item in all_items} == {"general", "openavatar", "youtube"}


def test_unified_catalog_filter_and_detail(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    response = client.get(
        "/v1/agent-runtime/catalog?source=youtube&risk_level=critical&limit=200",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["total"] > 0
    assert all(item["risk_level"] == "critical" for item in response.json()["items"])
    detail = client.get("/v1/agent-runtime/catalog/youtube-publisher", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["risk_level"] == "critical"


def test_private_http_worker_url_requires_explicit_host_allowlist(monkeypatch):
    monkeypatch.setenv("AGENT_WORKER_URL", "http://agent-api:8500")
    monkeypatch.setenv("AGENT_RUNTIME_ALLOW_PRIVATE_NETWORK_HTTP", "false")
    monkeypatch.setenv("AGENT_RUNTIME_PRIVATE_HTTP_HOSTS", "agent-api")
    try:
        _secure_service_url("AGENT_WORKER_URL")
        assert False, "private HTTP must be disabled by default"
    except RuntimeError:
        pass
    monkeypatch.setenv("AGENT_RUNTIME_ALLOW_PRIVATE_NETWORK_HTTP", "true")
    assert _secure_service_url("AGENT_WORKER_URL") == "http://agent-api:8500"
    monkeypatch.setenv("AGENT_WORKER_URL", "http://attacker.example")
    try:
        _secure_service_url("AGENT_WORKER_URL")
        assert False, "unlisted private host must be rejected"
    except RuntimeError:
        pass


def test_reference_worker_polls_accepted_plan_before_completing(monkeypatch):
    from datetime import datetime, timedelta, timezone

    task_id = "runtime-task-123456"
    executor_id = "celery-task-123456"
    seen = {"dispatch": None, "completed": None, "polls": 0}

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("unexpected HTTP error")

    class FakeApi:
        def post(self, url, **kwargs):
            if url.endswith("/workers/claim"):
                return FakeResponse(200, {"task": {
                    "task_id": task_id, "agent_id": "youtube-publisher",
                    "objective": "Prepare upload plan", "risk_level": "critical",
                    "lease_until": (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat(),
                    "payload": {"agent": {"id": "youtube-publisher", "risk_level": "critical"},
                                "user_approved": True, "dry_run": True, "inputs": {}, "tool_allowlist": []},
                }})
            if url == "https://agent.example/v1/agents/run":
                seen["dispatch"] = kwargs["json"]
                return FakeResponse(202, {"task_id": executor_id, "status": "queued"})
            if url.endswith("/complete"):
                seen["completed"] = kwargs["json"]["result"]["output"]
                return FakeResponse(200, {"status": "succeeded"})
            if url.endswith("/fail"):
                raise AssertionError("unexpected task failure")
            raise AssertionError(f"unexpected POST {url}")

        def get(self, url, **kwargs):
            assert url == f"https://agent.example/v1/tasks/{executor_id}"
            seen["polls"] += 1
            return FakeResponse(200, {
                "status": "plan_created",
                "result": {"summary": "A reviewed plan", "steps": []},
            })

    monkeypatch.setenv("AGENT_RUNTIME_EXECUTOR_POLL_SECONDS", "1")
    assert execute_one(
        FakeApi(), "https://backend.example", "api-key", "worker-1",
        "https://agent.example", "agent-key", "/v1/agents/run", 90,
    ) is True
    assert seen["dispatch"]["task_id"] == task_id
    assert seen["dispatch"]["agent_id"] == "youtube-publisher"
    assert seen["polls"] == 1
    assert seen["completed"]["summary"] == "A reviewed plan"


def test_worker_registry_blocks_parallel_claims_for_same_worker_and_cannot_hard_cancel(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    first = client.post("/v1/agent-runtime/tasks", headers=HEADERS, json={"objective": "First task"}).json()
    client.post("/v1/agent-runtime/tasks", headers=HEADERS, json={"objective": "Second task"})
    registered = client.post(
        "/v1/agent-runtime/workers/register", headers=HEADERS,
        json={"worker_id": "worker-registry-1", "capabilities": {"executor": "plan-only"}},
    )
    assert registered.status_code == 200
    claim = client.post(
        "/v1/agent-runtime/workers/claim", headers=HEADERS,
        json={"worker_id": "worker-registry-1"},
    ).json()
    assert claim["task"]["task_id"] == first["task_id"]
    busy = client.post(
        "/v1/agent-runtime/workers/claim", headers=HEADERS,
        json={"worker_id": "worker-registry-1"},
    ).json()
    assert busy["worker_busy"] is True
    assert busy["task"] is None
    worker = client.get("/v1/agent-runtime/workers", headers=HEADERS).json()["items"][0]
    assert worker["status"] == "busy"
    assert worker["current_task_id"] == first["task_id"]
    cannot_cancel = client.post(
        f"/v1/agent-runtime/tasks/{first['task_id']}/cancel", headers=HEADERS,
    )
    assert cannot_cancel.status_code == 409
