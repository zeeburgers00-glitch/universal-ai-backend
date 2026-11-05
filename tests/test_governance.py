"""API-key scopes, audit log and approval gates."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import governance
from app.main import app


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_API_KEY", "gov-key")
    monkeypatch.delenv("UAI_KEY_SCOPES", raising=False)
    monkeypatch.delenv("UAI_REQUIRE_APPROVAL", raising=False)
    monkeypatch.delenv("UAI_UNSCOPED_DENY", raising=False)
    governance.reset()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


HEADERS = {"X-API-Key": "gov-key"}


# --- scopes -------------------------------------------------------------------

def test_reads_are_never_blocked_by_scopes(monkeypatch, client):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"gov-key": ["video:write"]}))
    assert client.get("/v1/jobs/kinds", headers=HEADERS).status_code == 200
    assert client.get("/v1/code/tree", headers=HEADERS).status_code == 200


def test_write_outside_scope_is_forbidden(monkeypatch, client):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"gov-key": ["video:write"]}))
    blocked = client.post("/v1/jobs", headers=HEADERS, json={"kind": "video.probe", "payload": {}})
    assert blocked.status_code == 403
    assert "jobs:write" in blocked.json()["detail"]


def test_write_inside_scope_reaches_the_route(monkeypatch, client):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"gov-key": ["video:write"]}))
    # 400 is the route rejecting the payload — the point is that governance let it through.
    allowed = client.post("/v1/video/probe", headers=HEADERS, json={"path": "missing.mp4"})
    assert allowed.status_code == 400


def test_wildcard_and_area_wildcards(monkeypatch):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"a": ["*"], "b": ["code:*"]}))
    governance.authorise("a", "/v1/data/restore", "POST")
    governance.authorise("b", "/v1/code/write", "POST")
    with pytest.raises(governance.GovernanceError):
        governance.authorise("b", "/v1/data/restore", "POST")


def test_unscoped_keys_stay_unrestricted_by_default(monkeypatch):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"someone-else": ["code:write"]}))
    governance.authorise("unlisted-key", "/v1/data/restore", "POST")  # must not raise


def test_unscoped_deny_opt_in(monkeypatch):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"someone-else": ["code:write"]}))
    monkeypatch.setenv("UAI_UNSCOPED_DENY", "1")
    with pytest.raises(governance.GovernanceError):
        governance.authorise("unlisted-key", "/v1/data/restore", "POST")


def test_whoami_reports_scopes(monkeypatch, client):
    monkeypatch.setenv("UAI_KEY_SCOPES", json.dumps({"gov-key": ["code:write", "video:*"]}))
    body = client.get("/v1/governance/whoami", headers=HEADERS).json()
    assert body["scopes"] == ["code:write", "video:*"]
    assert body["unrestricted"] is False
    assert len(body["actor"]) == 12


# --- audit log ----------------------------------------------------------------

def test_audit_log_records_writes_without_storing_the_key(client):
    client.post("/v1/video/probe", headers=HEADERS, json={"path": "nope.mp4"})
    log = client.get("/v1/governance/audit", headers=HEADERS).json()
    entries = [entry for entry in log["entries"] if entry["action"] == "http.write"]
    assert entries, log
    entry = entries[0]
    assert entry["target"] == "/v1/video/probe"
    assert entry["actor"] == governance.fingerprint("gov-key")
    assert "gov-key" not in json.dumps(log), "the secret itself must never be logged"
    assert entry["outcome"].startswith("error:")  # the 400 was recorded honestly


def test_audit_log_is_append_only_and_filterable(client):
    governance.record("test.action", key="gov-key", target="a")
    governance.record("other.action", key="gov-key", target="b")
    filtered = client.get("/v1/governance/audit", params={"action": "test.action"}, headers=HEADERS).json()
    assert filtered["count"] == 1
    assert filtered["entries"][0]["target"] == "a"


def test_audit_log_survives_a_missing_file(client):
    body = client.get("/v1/governance/audit", headers=HEADERS).json()
    assert isinstance(body["entries"], list)


def test_audit_requires_the_key(client):
    assert client.get("/v1/governance/audit").status_code == 401


# --- approvals ----------------------------------------------------------------

def test_approvals_default_off(client):
    assert client.get("/v1/governance/approvals", headers=HEADERS).json()["required"] is False
    assert client.post("/v1/code/write", headers=HEADERS, json={
        "path": "tmp_none.py", "content": "x = 1\n", "dry_run": True,
    }).status_code == 200


def test_dangerous_write_needs_a_token(monkeypatch, client):
    monkeypatch.setenv("UAI_REQUIRE_APPROVAL", "1")
    body = {"path": "tmp_none.py", "content": "x = 1\n", "dry_run": True}
    assert client.post("/v1/code/write", headers=HEADERS, json=body).status_code == 428


def test_token_is_single_use(monkeypatch, client):
    monkeypatch.setenv("UAI_REQUIRE_APPROVAL", "1")
    token = client.post(
        "/v1/governance/approvals",
        headers=HEADERS,
        json={"path": "/v1/code/write", "reason": "demo"},
    ).json()["token"]

    headers = {**HEADERS, "X-Approval-Token": token}
    body = {"path": "tmp_none.py", "content": "x = 1\n", "dry_run": True}
    assert client.post("/v1/code/write", headers=headers, json=body).status_code == 200
    assert client.post("/v1/code/write", headers=headers, json=body).status_code == 403


def test_token_for_a_different_operation_is_refused(monkeypatch, client):
    monkeypatch.setenv("UAI_REQUIRE_APPROVAL", "1")
    token = client.post(
        "/v1/governance/approvals",
        headers=HEADERS,
        json={"path": "/v1/data/restore", "reason": "restore"},
    ).json()["token"]
    response = client.post(
        "/v1/code/write",
        headers={**HEADERS, "X-Approval-Token": token},
        json={"path": "tmp_none.py", "content": "x = 1\n", "dry_run": True},
    )
    assert response.status_code == 403


def test_expired_tokens_are_rejected(monkeypatch, client):
    monkeypatch.setenv("UAI_REQUIRE_APPROVAL", "1")
    token = governance.grant("/v1/code/write", "test")["token"]
    governance._approvals[token]["expires"] = time.time() - 1
    with pytest.raises(governance.GovernanceError):
        governance.consume(token, "/v1/code/write")


def test_only_dangerous_paths_can_be_pre_approved(client):
    bad = client.post("/v1/governance/approvals", headers=HEADERS, json={"path": "/health", "reason": "not dangerous"})
    assert bad.status_code == 400


def test_granting_an_approval_is_audited(client):
    client.post("/v1/governance/approvals", headers=HEADERS, json={"path": "/v1/code/apply", "reason": "patch"})
    log = client.get("/v1/governance/audit", params={"action": "approval.granted"}, headers=HEADERS).json()
    assert log["count"] == 1
    assert log["entries"][0]["detail"]["reason"] == "patch"
