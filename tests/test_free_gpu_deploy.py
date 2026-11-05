"""Tests for the free-GPU (Kaggle) and image-publishing (GitHub Actions) paths."""

from __future__ import annotations

import py_compile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KAGGLE_DIR = ROOT / "deploy" / "kaggle"
KAGGLE_SCRIPT = KAGGLE_DIR / "run_voice_worker.py"
KAGGLE_README = KAGGLE_DIR / "README.md"
# Kept outside .github/workflows because the automation token that pushes this
# branch has no "workflows" scope. See deploy/ghcr/README.md to install it.
WORKFLOW = ROOT / "deploy" / "ghcr" / "voice-worker-image.yml"
RUNPOD_COMPOSE = ROOT / "deploy" / "runpod" / "docker-compose.yml"


def test_kaggle_kit_exists_and_compiles():
    assert KAGGLE_SCRIPT.exists()
    assert KAGGLE_README.exists()
    py_compile.compile(str(KAGGLE_SCRIPT), doraise=True)  # syntax is valid


def test_kaggle_script_matches_the_worker_contract():
    source = KAGGLE_SCRIPT.read_text(encoding="utf-8")
    # The worker app is started by module path, from the workers/ package root.
    assert "voice_worker.app:app" in source
    assert "PYTHONPATH" in source
    # Voice jobs are Celery tasks, so a broker must be started.
    assert "redis-server" in source
    assert "voice_worker.synthesize" in source or "celery_app" in source
    # The worker key must be generated per run, never hard-coded.
    assert "secrets.token_urlsafe" in source
    assert "VOICE_WORKER_API_KEY" in source


def test_kaggle_tunnel_produces_an_https_url():
    # The API rejects plain http for anything other than 127.0.0.1, so the
    # tunnel is what makes a remote worker acceptable.
    source = KAGGLE_SCRIPT.read_text(encoding="utf-8")
    assert "trycloudflare" in source
    assert "https://[a-z0-9-]+\\.trycloudflare\\.com" in source
    assert "VOICE_WORKER_URL=" in source  # prints a copy-paste snippet


def test_kaggle_readme_is_honest_about_limits():
    text = KAGGLE_README.read_text(encoding="utf-8").lower()
    assert "12-hour" in text or "12 h" in text
    assert "https" in text
    assert "not a production worker" in text or "testing bench" in text


def test_github_workflow_builds_the_voice_image_without_claiming_a_gpu():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # Triggers
    assert "workflow_dispatch" in data[True] or "workflow_dispatch" in data.get("on", {})
    # Needs to publish to GHCR
    assert data["permissions"]["packages"] == "write"
    job = data["jobs"]["build"]
    # GitHub-hosted runners have no GPU; the workflow must not pretend otherwise.
    assert job["runs-on"] == "ubuntu-latest"
    steps = [s for s in job["steps"] if "build-push-action" in s.get("uses", "")]
    assert steps, "workflow must build and push the image"
    assert steps[0]["with"]["context"] == "workers/voice_worker"


def test_github_workflow_states_the_gpu_limitation():
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    assert "no gpu" in text or "cpu-only" in text


def test_runpod_compose_can_pull_the_prebuilt_image():
    services = yaml.safe_load(RUNPOD_COMPOSE.read_text(encoding="utf-8"))["services"]
    image = services["voice_worker"].get("image", "")
    assert "VOICE_WORKER_IMAGE" in image, "voice_worker must accept a prebuilt image"
    # The build context must stay so a local build still works.
    assert services["voice_worker"]["build"]["context"] == "../../workers/voice_worker"
