"""The dependency audit must prove the manifest matches the code, not assume it."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import deps_audit
from app.main import app

REPO = Path(__file__).resolve().parent.parent


def test_parse_requirements_reads_real_specifiers():
    entries = deps_audit.parse_requirements(REPO / "requirements.txt")
    names = {entry["key"] for entry in entries}
    assert {"fastapi", "httpx", "pydantic"} <= names
    assert all(entry["bounded"] for entry in entries), "every dependency needs a ceiling"


def test_repository_manifest_matches_the_code():
    report = deps_audit.audit(REPO, REPO / "requirements.txt")
    assert report["declared"] >= 8
    assert report["declared_but_not_imported"] == [], report["declared_but_not_imported"]
    assert report["imported_but_not_declared"] == [], report["imported_but_not_declared"]
    assert report["python_files_scanned"] > 50
    assert any(entry["name"] == "fastapi" and entry["usage_count"] > 10 for entry in report["used"])


def test_runtime_only_packages_are_not_reported_as_dead():
    report = deps_audit.audit(REPO, REPO / "requirements.txt")
    assert "uvicorn" in report["runtime_only"]


def test_unused_dependency_is_detected(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text("import json\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(
        "fastapi>=0.115,<1.0\nnumpy>=2,<3\n", encoding="utf-8"
    )
    report = deps_audit.audit(tmp_path, tmp_path / "requirements.txt")
    assert [entry["name"] for entry in report["declared_but_not_imported"]] == ["fastapi", "numpy"]
    assert "fastapi" in deps_audit.verdict(report)[0]


def test_import_alias_is_understood(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text("import yaml\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pyyaml>=6.0,<7.0\n", encoding="utf-8")
    report = deps_audit.audit(tmp_path, tmp_path / "requirements.txt")
    assert report["declared_but_not_imported"] == []
    assert report["used"][0]["module"] == "yaml"


def test_optional_extras_in_deploy_are_not_flags(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "deploy").mkdir()
    (tmp_path / "app" / "mod.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "deploy" / "kit.py").write_text("import httpx\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi>=0.115,<1.0\n", encoding="utf-8")
    report = deps_audit.audit(tmp_path, tmp_path / "requirements.txt")
    assert [entry["module"] for entry in report["imported_but_not_declared"]] == []


def test_missing_requirements_file_raises(tmp_path):
    with pytest.raises(deps_audit.AuditError):
        deps_audit.parse_requirements(tmp_path / "nope.txt")


def test_audit_endpoint(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "audit-key")
    with TestClient(app) as client:
        assert client.get("/v1/audit/dependencies").status_code == 401
        response = client.get("/v1/audit/dependencies", headers={"X-API-Key": "audit-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["declared"] >= 8
    assert body["verdict"]
