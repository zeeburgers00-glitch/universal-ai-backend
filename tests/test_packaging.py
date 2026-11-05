"""Compose file, Makefile and docs must stay honest about the real app."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.main import app

PATHS = app.openapi()["paths"]

REPO = Path(__file__).resolve().parent.parent


def test_compose_is_valid_and_persistent():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["api"]
    assert "8000" in " ".join(service["ports"])
    assert any("uai-data" in volume for volume in service["volumes"]), "data must be on a volume"
    assert "BACKEND_API_KEY" in service["environment"]
    assert "uai-data" in compose["volumes"]


def test_compose_healthcheck_hits_the_deep_probe():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    command = " ".join(compose["services"]["api"]["healthcheck"]["test"])
    assert "/health/deep" in command
    assert "/health/deep" in app.openapi()["paths"]


def test_compose_data_root_matches_the_mount():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["api"]
    assert service["environment"]["UAI_DATA_ROOT"] == "/data"
    assert any(volume.endswith(":/data") for volume in service["volumes"])


def test_makefile_targets_exist():
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    for target in ("install:", "test:", "run:", "docker:", "backup:", "audit:", "sdk:"):
        assert target in text, target


def test_makefile_backup_hits_a_real_route():
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "/v1/data/backup" in text
    assert "/v1/data/backup" in app.openapi()["paths"]


def test_makefile_sdk_hits_a_real_route():
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "/v1/sdk" in text
    assert "/v1/sdk" in app.openapi()["paths"]


def test_dockerfile_runs_as_non_root():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "uvicorn app.main:app" in dockerfile
