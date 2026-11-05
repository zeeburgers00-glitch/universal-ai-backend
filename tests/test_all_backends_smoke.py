"""Boot every backend in this repository and prove it answers.

There are nine worker services next to the FastAPI control plane. Eight expose
HTTP; autopilot_worker is a Celery consumer with no port. A worker that fails to
import is dead on deploy, and the only way to catch that before shipping is to
import it and call /health.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
WORKERS_DIR = ROOT / "workers"

if str(WORKERS_DIR) not in sys.path:
    sys.path.insert(0, str(WORKERS_DIR))

# Data roots must be writable in CI; the containers use /data.
DATA_ENVS = {
    "VOICE_DATA_ROOT": "/tmp/uai-test/voice",
    "MEDIA_DATA_ROOT": "/tmp/uai-test/media",
    "YOUTUBE_MEDIA_ASSET_ROOT": "/tmp/uai-test/youtube",
    "REA_ALLOWED_WORKSPACE_ROOT": "/tmp/uai-test/rea",
    "WINDOWS_AGENT_WORKSPACE": "/tmp/uai-test/windows",
    "CELERY_BROKER_URL": "memory://",
    "WORKER_ALLOW_INSECURE_HTTP": "true",
}

KEY_ENVS = (
    "VOICE_WORKER_API_KEY", "MEDIA_WORKER_API_KEY", "YOUTUBE_WORKER_API_KEY",
    "CHANNEL_WORKER_API_KEY", "AGENT_WORKER_API_KEY", "AUTOMATION_WORKER_API_KEY",
    "REA_WORKER_API_KEY", "DESKTOP_AGENT_API_KEY",
)
TEST_KEY = "smoke-test-worker-key"

# module, minimum route count, one route that must demand the bearer key
HTTP_BACKENDS = [
    ("voice_worker", 7, "GET", "/v1/voice/providers"),
    ("media_worker", 6, "POST", "/v1/media/jobs"),
    ("youtube_worker", 3, "POST", "/v1/youtube/publish"),
    ("channel_worker", 2, "POST", "/v1/channels/action"),
    ("agent_worker", 3, "POST", "/v1/agents/run"),
    ("automation_worker", 3, "POST", "/v1/workflows/run"),
    ("rea_worker", 3, "POST", "/v1/rea/inspect"),
    ("windows_agent", 5, "POST", "/v1/desktop/actions"),
]


@pytest.fixture(scope="module", autouse=True)
def worker_environment():
    saved = {name: os.environ.get(name) for name in {**DATA_ENVS, **dict.fromkeys(KEY_ENVS)}}
    os.environ.update(DATA_ENVS)
    for name in KEY_ENVS:
        os.environ[name] = TEST_KEY
    for directory in {p for p in DATA_ENVS.values() if p.startswith("/tmp")}:
        Path(directory).mkdir(parents=True, exist_ok=True)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _load(module_name: str):
    module = importlib.import_module(f"{module_name}.app")
    return module


@pytest.mark.parametrize("module_name,min_routes,method,path", HTTP_BACKENDS,
                         ids=[case[0] for case in HTTP_BACKENDS])
def test_backend_boots_and_answers_health(module_name, min_routes, method, path):
    module = _load(module_name)
    app = getattr(module, "app", None)
    assert app is not None, f"{module_name} must expose a FastAPI app"

    routes = {route.path for route in app.routes if getattr(route, "methods", None)}
    assert "/health" in routes, f"{module_name} has no /health route"
    assert path in routes, f"{module_name} is missing {path}"

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200, f"{module_name} /health -> {health.status_code}"

    # Protected routes must reject an unauthenticated caller.
    response = client.request(method, path, json={})
    assert response.status_code in (401, 403), (
        f"{module_name} {path} answered {response.status_code} without a key"
    )


def test_autopilot_worker_is_a_celery_consumer_not_an_http_service():
    """It is deployed as `celery -A autopilot_worker.app.celery_app worker`."""
    module = _load("autopilot_worker")
    assert not hasattr(module, "app"), "autopilot is queue-driven; it should not serve HTTP"
    celery_app = getattr(module, "celery_app", None)
    assert celery_app is not None
    assert "autopilot_worker.tasks" in celery_app.conf.include


def test_autopilot_worker_refuses_to_start_without_a_broker(monkeypatch):
    pytest.importorskip("celery")
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    sys.modules.pop("autopilot_worker.app", None)
    with pytest.raises(RuntimeError, match="CELERY_BROKER_URL"):
        importlib.import_module("autopilot_worker.app")


def test_every_worker_has_a_container_definition():
    """Each worker either has a Dockerfile or is documented as host-only."""
    expected = {
        "voice_worker", "media_worker", "youtube_worker", "channel_worker",
        "agent_worker", "automation_worker", "rea_worker", "autopilot_worker",
    }
    for name in expected:
        assert (WORKERS_DIR / name / "Dockerfile").is_file(), f"{name} has no Dockerfile"
    # windows_agent runs on a Windows host, not in a Linux container.
    assert (WORKERS_DIR / "windows_agent" / "README.md").is_file()


def test_deploy_stacks_include_the_queue_consumer():
    import yaml

    for compose_path in (ROOT / "deploy" / "cpu-free" / "docker-compose.yml",
                         ROOT / "deploy" / "runpod" / "docker-compose.yml"):
        services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]
        assert "autopilot_worker" in services, (
            f"{compose_path.parent.name} would queue /v1/chat/tasks with no consumer"
        )
        assert "api" in services and "redis" in services


# --- resilience: a dead broker must be a 503, not a 500 -----------------------

SEND_TASK_WORKERS = (
    "agent_worker", "automation_worker", "media_worker",
    "rea_worker", "voice_worker", "youtube_worker",
)


def test_enqueue_without_broker_returns_503_not_500():
    """A worker whose Redis broker is down must say so, not blow up with a 500."""

    media = importlib.import_module("media_worker.app")
    from fastapi.testclient import TestClient

    def boom(*args, **kwargs):
        raise RuntimeError("Retry limit exceeded while trying to reconnect to the Celery result store")

    original = media.celery_app.send_task
    media.celery_app.send_task = boom
    try:
        with TestClient(media.app) as client:
            response = client.post(
                "/v1/media/jobs",
                headers={"Authorization": f"Bearer {TEST_KEY}"},
                json={"task_type": "image", "inputs": {"prompt": "a cat"}, "user_approved": True},
            )
    finally:
        media.celery_app.send_task = original

    assert response.status_code == 503
    assert "broker" in response.json()["detail"].lower()


def test_every_enqueue_site_is_guarded():
    """Source guard: each worker that enqueues must wrap send_task in try/except."""

    unguarded = []
    for worker in SEND_TASK_WORKERS:
        source = (WORKERS_DIR / worker / "app.py").read_text(encoding="utf-8")
        assert "celery_app.send_task(" in source, worker
        window_start = max(0, source.index("celery_app.send_task(") - 200)
        window = source[window_start: source.index("celery_app.send_task(")]
        if "try:" not in window:
            unguarded.append(worker)
    assert unguarded == []


def test_ffmpeg_resolves_without_system_binary(monkeypatch):
    """Local (.venv) runs have no system ffmpeg; the pip-bundled binary must work."""

    media = importlib.import_module("media_worker.app")
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    resolved = media.resolve_ffmpeg()
    assert resolved and Path(resolved).exists()


def test_command_request_rejects_unknown_fields(monkeypatch):
    """`duration_seconds` is not a knob (it is `scene_seconds`) and must not be ignored."""

    from fastapi.testclient import TestClient

    from app.main import app as control_plane

    # Auth is checked before the body, so pin the key for this test only.
    monkeypatch.setenv("BACKEND_API_KEY", TEST_KEY)
    with TestClient(control_plane) as client:
        response = client.post(
            "/v1/command",
            headers={"X-API-Key": TEST_KEY},
            json={"command": "three tips for a small shop", "duration_seconds": 12},
        )
    assert response.status_code == 422
