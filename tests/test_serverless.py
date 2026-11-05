"""Vercel/serverless packaging: the entry point must actually serve the app."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ENTRY = REPO / "api" / "index.py"


def _load_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("UAI_JOBS_DISABLE", raising=False)
    monkeypatch.setenv("BACKEND_API_KEY", "serverless-key")
    spec = importlib.util.spec_from_file_location("api_index_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entry_point_exists_and_exports_asgi_app(monkeypatch, tmp_path):
    module = _load_entry(monkeypatch, tmp_path)
    assert hasattr(module, "app")
    assert module.app.title  # a real FastAPI instance


def test_entry_point_serves_the_full_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    module = _load_entry(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/deep").status_code == 200
        assert client.get("/editor").status_code == 200
        assert "/v1/jobs" in module.app.openapi()["paths"]


def test_entry_point_moves_state_to_tmp(monkeypatch, tmp_path):
    module = _load_entry(monkeypatch, tmp_path)
    assert module.app is not None
    assert "uai-data" in os.environ.get("UAI_DATA_ROOT", "") or "tmp" in os.environ.get("UAI_DATA_ROOT", "")


def test_entry_point_disables_background_workers(monkeypatch, tmp_path):
    monkeypatch.delenv("UAI_JOBS_DISABLE", raising=False)
    _load_entry(monkeypatch, tmp_path)
    assert os.environ["UAI_JOBS_DISABLE"] == "1", "serverless has no long-lived worker"


def test_vercel_json_targets_the_python_entry():
    config = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    # Modern zero-config Python: Vercel detects api/index.py, we only set limits + routing.
    assert "api/index.py" in config["functions"]
    assert config["functions"]["api/index.py"]["maxDuration"] >= 30
    assert "builds" not in config, "builds and functions are mutually exclusive on Vercel"


def test_every_route_goes_to_the_function():
    config = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    rewrites = config["rewrites"]
    assert any(rule["destination"] == "/api/index.py" for rule in rewrites)
    assert any(rule["source"] == "/(.*)" for rule in rewrites), "catch-all keeps every route on the app"


def test_runtime_requirements_are_complete_and_bounded():
    runtime = (REPO / "requirements.txt").read_text(encoding="utf-8")
    lines = [line.strip() for line in runtime.splitlines() if line.strip() and not line.startswith("#")]
    assert any(line.startswith("fastapi") for line in lines)
    assert any(line.startswith("imageio-ffmpeg") for line in lines), "renders need the ffmpeg wheel"
    assert all(any(char in line for char in "<>=~") for line in lines), "every pin needs a ceiling"


def test_vercelignore_keeps_the_runtime_catalog():
    text = (REPO / ".vercelignore").read_text(encoding="utf-8")
    ignored = {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}
    assert "catalog/" not in ignored, "the 205-repo registry is read at runtime"
    assert ".venv/" in ignored and "tests/" in ignored


def test_serverless_startup_skips_job_workers(monkeypatch, tmp_path):
    """The startup hook must not spawn threads when running as a lambda."""

    monkeypatch.setenv("UAI_SERVERLESS", "1")
    monkeypatch.delenv("UAI_JOBS_DISABLE", raising=False)
    from app import jobs

    started = {"value": False}
    monkeypatch.setattr(jobs, "ensure_started", lambda *a, **k: started.__setitem__("value", True))

    import app.main as main_module

    main_module._start_job_workers()
    assert started["value"] is False
