"""Tests for the free-tier CPU deployment (deploy/cpu-free)."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import yaml

DEPLOY_DIR = Path(__file__).resolve().parent.parent / "deploy" / "cpu-free"
COMPOSE = DEPLOY_DIR / "docker-compose.yml"
ENV_EXAMPLE = DEPLOY_DIR / ".env.cpu-free.example"
BOOTSTRAP = DEPLOY_DIR / "bootstrap.sh"
UNIT = DEPLOY_DIR / "universal-ai-backend.service"
README = DEPLOY_DIR / "README.md"

# Worker service name -> the port its Dockerfile binds.
WORKER_PORTS = {
    "youtube_worker": 8200,
    "channel_worker": 8300,
    "media_worker": 8400,
    "agent_worker": 8500,
    "automation_worker": 8600,
    "rea_worker": 8700,
}


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_all_deploy_files_exist():
    for path in (COMPOSE, ENV_EXAMPLE, BOOTSTRAP, UNIT, README):
        assert path.exists(), f"missing {path.name}"


def test_cpu_stack_runs_api_redis_and_six_workers_without_voice():
    services = _compose()["services"]
    assert "api" in services and "redis" in services
    for worker in WORKER_PORTS:
        assert worker in services, f"{worker} should be deployed"
    # voice_worker requires CUDA and must not be part of the CPU stack.
    assert "voice_worker" not in services


def test_every_service_uses_host_networking():
    # app/task_gateway.py only accepts plain HTTP worker URLs on 127.0.0.1.
    for name, service in _compose()["services"].items():
        assert service.get("network_mode") == "host", f"{name} must use host networking"


def test_api_builds_from_repository_root():
    api = _compose()["services"]["api"]
    assert api["build"]["context"] == "../.."
    assert api["build"]["dockerfile"] == "Dockerfile"
    assert api["healthcheck"]["test"][0] == "CMD"


def test_worker_build_contexts_point_at_real_directories():
    services = _compose()["services"]
    for worker in WORKER_PORTS:
        context = (DEPLOY_DIR / services[worker]["build"]["context"]).resolve()
        assert (context / "Dockerfile").exists(), f"{worker} context has no Dockerfile"
        assert context.name == worker


def test_worker_urls_match_deployed_ports():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for worker, port in WORKER_PORTS.items():
        var = worker.upper().replace("_WORKER", "") + "_WORKER_URL"
        match = re.search(rf"^{var}=(\S*)$", text, re.MULTILINE)
        assert match, f"{var} missing from the env template"
        assert match.group(1) == f"http://127.0.0.1:{port}", f"{var} has the wrong port"


def test_voice_is_optional_and_never_plain_http():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    match = re.search(r"^VOICE_WORKER_URL=(\S*)$", text, re.MULTILINE)
    assert match, "VOICE_WORKER_URL must be present (empty is fine)"
    url = match.group(1)
    # Empty (disabled) or HTTPS (remote free GPU host). Never insecure HTTP.
    assert url == "" or url.startswith("https://")


def test_bootstrap_is_executable_and_hardened():
    assert os.access(BOOTSTRAP, os.X_OK), "bootstrap.sh must be executable"
    assert BOOTSTRAP.stat().st_mode & stat.S_IXUSR
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "get.docker.com" in text
    assert "docker compose up -d" in text
    # Oracle needs both firewall layers; the script must mention the console one.
    assert "Security List" in text


def test_systemd_unit_starts_the_stack_on_boot():
    text = UNIT.read_text(encoding="utf-8")
    assert "docker compose up -d" in text
    assert "WantedBy=multi-user.target" in text
    assert "After=docker.service" in text


def test_readme_documents_the_gpu_boundary():
    text = README.read_text(encoding="utf-8").lower()
    assert "voice" in text
    assert "gpu" in text
    assert "503" in text  # the honest failure the API returns


def test_env_templates_are_not_gitignored():
    """A `.env.*` ignore rule once swallowed these templates entirely."""
    root = Path(__file__).resolve().parent.parent
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "!.env.*.example" in ignore, (
        "deploy env templates must be un-ignored or they vanish from the repository"
    )
    for template in (DEPLOY_DIR / ".env.cpu-free.example",
                     root / "deploy" / "runpod" / ".env.runpod.example"):
        assert template.is_file(), f"missing {template.name}"
