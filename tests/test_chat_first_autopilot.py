from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_youtube_agent_fleet_has_120_role_slots():
    response = client.get("/v1/agent-fleet")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_slots"] == 120
    assert data["role_count"] == 17
    assert len(data["roles"]) == 17


def test_chat_task_endpoint_is_protected(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-autopilot-secret")
    response = client.post("/v1/chat/tasks", json={"message": "Create a YouTube video"})
    assert response.status_code == 401


def test_metricool_status_never_returns_credentials(monkeypatch):
    monkeypatch.delenv("METRICOOL_API_TOKEN", raising=False)
    monkeypatch.delenv("METRICOOL_USER_ID", raising=False)
    monkeypatch.delenv("METRICOOL_BLOG_ID", raising=False)
    response = client.get("/v1/integrations/metricool/status")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is False
    assert "METRICOOL_API_TOKEN" in data["required_backend_secrets"]
    assert "secret_value" not in data


def test_metricool_youtube_schedule_requires_explicit_approval(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-autopilot-secret")
    response = client.post(
        "/v1/integrations/metricool/schedule-youtube",
        headers={"X-API-Key": "test-autopilot-secret"},
        json={
            "title": "Test video",
            "description": "Test description",
            "publication_datetime": "2026-11-10T12:00:00",
            "timezone": "Asia/Karachi",
            "media_ids": ["metricool-media-id"],
            "user_approved": False,
        },
    )
    assert response.status_code == 409
