from __future__ import annotations

import os
from fastapi.testclient import TestClient

from app.main import app


os.environ.setdefault("BACKEND_API_KEY", "test-backend-api-key")

client = TestClient(app)
API_HEADERS = {"X-API-Key": "test-backend-api-key"}


def _upload(kind: str, body: bytes, content_type: str, filename: str) -> str:
    response = client.post(
        f"/v1/openavatar/assets?kind={kind}",
        headers={**API_HEADERS, "X-Filename": filename, "Content-Type": content_type},
        content=body,
    )
    assert response.status_code == 201, response.text
    return response.json()["asset_id"]


def _make_talking_head_assets():
    image_id = _upload("portrait", b"\x89PNG\r\n\x1a\nsmall-test-image", "image/png", "portrait.png")
    audio_id = _upload("audio", b"RIFF0000WAVEfmt ", "audio/wav", "voice.wav")
    return image_id, audio_id


def test_openavatar_status_is_no_card_and_has_no_paid_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    response = client.get("/v1/openavatar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["no_card_only"] is True
    assert payload["paid_provider_fallback"] is False
    assert {item["id"] for item in payload["providers"]} == {
        "local_cpu", "huggingface_zerogpu", "kaggle", "lightning"
    }
    assert all(item["no_card_required"] is True for item in payload["providers"])


def test_job_creation_requires_backend_key_and_consent(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    image_id, audio_id = _make_talking_head_assets()
    payload = {
        "job_type": "talking_head",
        "image_asset_id": image_id,
        "audio_asset_id": audio_id,
    }
    monkeypatch.delenv("BACKEND_API_KEY", raising=False)
    unauthenticated = client.post("/v1/openavatar/jobs", json=payload)
    assert unauthenticated.status_code == 503
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    response = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload)
    assert response.status_code == 400
    payload["consent_confirmed"] = True
    response = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["provider"] == "huggingface_zerogpu"


def test_upload_rejects_mismatched_media_type(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    response = client.post(
        "/v1/openavatar/assets?kind=portrait",
        headers={**API_HEADERS, "Content-Type": "text/plain", "X-Filename": "portrait.txt"},
        content=b"not an image",
    )
    assert response.status_code == 415


def test_kaggle_is_disabled_by_default_and_blocks_commercial_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    monkeypatch.delenv("OPENAVATAR_KAGGLE_ENABLED", raising=False)
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    image_id, audio_id = _make_talking_head_assets()
    payload = {
        "job_type": "talking_head",
        "provider": "kaggle",
        "image_asset_id": image_id,
        "audio_asset_id": audio_id,
        "consent_confirmed": True,
        "commercial_use": True,
    }
    assert client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload).status_code == 503
    monkeypatch.setenv("OPENAVATAR_KAGGLE_ENABLED", "true")
    assert client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload).status_code == 403


def test_worker_claim_reserves_huggingface_quota_and_completes(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    monkeypatch.setenv("OPENAVATAR_WORKER_TOKEN", "w" * 40)
    monkeypatch.setenv("OPENAVATAR_HF_DAILY_BUDGET_SECONDS", "60")
    image_id, audio_id = _make_talking_head_assets()
    payload = {
        "job_type": "talking_head",
        "image_asset_id": image_id,
        "audio_asset_id": audio_id,
        "consent_confirmed": True,
        "max_gpu_seconds": 60,
    }
    job = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload).json()
    worker_headers = {"X-OpenAvatar-Worker-Token": "w" * 40}
    heartbeat = client.post(
        "/internal/openavatar/heartbeat",
        headers=worker_headers,
        json={"provider": "huggingface_zerogpu", "worker_id": "test-hf", "capabilities": ["sadtalker"]},
    )
    assert heartbeat.status_code == 200
    claim = client.post(
        "/internal/openavatar/jobs/claim",
        headers=worker_headers,
        json={"provider": "huggingface_zerogpu", "worker_id": "test-hf", "capabilities": ["sadtalker"]},
    )
    assert claim.status_code == 200
    assert claim.json()["job"]["job_id"] == job["job_id"]
    quota = client.get("/v1/openavatar/quota", headers=API_HEADERS).json()["huggingface_zerogpu"]
    assert quota["reserved_seconds"] == 60
    second = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload).json()
    no_quota = client.post(
        "/internal/openavatar/jobs/claim",
        headers=worker_headers,
        json={"provider": "huggingface_zerogpu", "worker_id": "test-hf", "capabilities": ["sadtalker"]},
    )
    assert no_quota.json()["job"] is None
    assert no_quota.json()["reason"] == "daily_quota_exhausted"
    assert second["status"] == "queued"


def test_worker_cannot_complete_another_workers_job(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    monkeypatch.setenv("OPENAVATAR_WORKER_TOKEN", "w" * 40)
    monkeypatch.setenv("OPENAVATAR_HF_DAILY_BUDGET_SECONDS", "60")
    image_id, audio_id = _make_talking_head_assets()
    job = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json={
        "job_type": "talking_head",
        "image_asset_id": image_id,
        "audio_asset_id": audio_id,
        "consent_confirmed": True,
    }).json()
    token_header = {"X-OpenAvatar-Worker-Token": "w" * 40}
    client.post("/internal/openavatar/jobs/claim", headers=token_header, json={
        "provider": "huggingface_zerogpu", "worker_id": "worker-a", "capabilities": ["sadtalker"]
    })
    fail = client.post(
        f"/internal/openavatar/jobs/{job['job_id']}/fail",
        headers={**token_header, "X-OpenAvatar-Worker-Id": "worker-b"},
        json={"error": "not my job", "consumed_gpu_seconds": 0},
    )
    assert fail.status_code == 409


def test_voice_job_requires_consent_and_routes_to_local_cpu(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-api-key")
    monkeypatch.setenv("OPENAVATAR_DATA_DIR", str(tmp_path))
    audio_id = _upload("audio", b"RIFF0000WAVEfmt ", "audio/wav", "reference.wav")
    payload = {
        "job_type": "voice",
        "audio_asset_id": audio_id,
        "text": "Hello from OpenAvatar.",
    }
    denied = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload)
    assert denied.status_code == 400
    payload["consent_confirmed"] = True
    accepted = client.post("/v1/openavatar/jobs", headers=API_HEADERS, json=payload)
    assert accepted.status_code == 202
    assert accepted.json()["provider"] == "local_cpu"
    assert accepted.json()["engine"] == "openvoice_v2"


def test_model_registry_marks_weights_and_commercial_use_for_review():
    response = client.get("/v1/openavatar/models")
    assert response.status_code == 200
    models = {model["id"]: model for model in response.json()["models"]}
    assert models["sadtalker"]["commercial_status"] == "review_required"
    assert models["f5_tts"]["commercial_status"] == "not_approved"
