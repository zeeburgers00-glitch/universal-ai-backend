from __future__ import annotations

import os
from fastapi.testclient import TestClient

from app.main import app


os.environ.setdefault("BACKEND_API_KEY", "test-agent-runtime-key")
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
