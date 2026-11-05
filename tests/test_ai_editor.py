"""The built-in AI editor: one HTML response, no CDN, and every call it makes exists."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.editor_assets import EDITOR_HTML
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "editor-test-key")
    with TestClient(app) as test_client:
        yield test_client


HEADERS = {"X-API-Key": "editor-test-key"}


# --- the page itself ----------------------------------------------------------

def test_editor_page_is_served(client):
    response = client.get("/editor")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "AI Editor" in response.text
    assert len(response.text) < 120_000, "keep it a single small response"


def test_editor_loads_nothing_from_the_internet():
    """No CDN, no fonts, no analytics: the page must work air-gapped."""

    assert "http://" not in EDITOR_HTML
    assert "https://" not in EDITOR_HTML
    assert "<link" not in EDITOR_HTML
    assert "src=" not in EDITOR_HTML


def test_editor_is_honest_about_model_requirements():
    assert "0 keys" in EDITOR_HTML
    assert "local model" in EDITOR_HTML.lower() or "ollama" in EDITOR_HTML.lower()


def test_every_endpoint_the_editor_calls_exists():
    """Drift guard: renaming a route must not silently break the editor UI."""

    called = set(re.findall(r"/v1/[a-z0-9\-/]+", EDITOR_HTML))
    known = set(app.openapi()["paths"])
    unknown = {path for path in called if path not in known}
    assert not unknown, f"editor calls endpoints that do not exist: {sorted(unknown)}"


def test_editor_handles_missing_or_wrong_key():
    assert "401" in EDITOR_HTML and "503" in EDITOR_HTML
    assert "localStorage" in EDITOR_HTML


# --- tree / read / write ------------------------------------------------------

def test_tree_requires_the_key(client):
    assert client.get("/v1/code/tree").status_code == 401
    assert client.get("/v1/code/read", params={"path": "app/config.py"}).status_code == 401


def test_tree_lists_files_and_respects_limits(client):
    body = client.get("/v1/code/tree", params={"max_entries": 5}, headers=HEADERS).json()
    assert body["total_files"] <= 5
    assert body["files"]
    assert all("path" in entry for entry in body["files"])


def test_read_returns_file_content(client):
    body = client.get("/v1/code/read", params={"path": "app/config.py"}, headers=HEADERS).json()
    assert body["path"] == "app/config.py"
    assert "def load_env_file" in body["content"]
    assert body["editable"] is True


def test_read_rejects_path_traversal(client):
    response = client.get("/v1/code/read", params={"path": "../../etc/passwd"}, headers=HEADERS)
    assert response.status_code == 400


def test_write_is_dry_by_default(client):
    before = client.get("/v1/code/read", params={"path": "app/config.py"}, headers=HEADERS).json()["content"]
    preview = client.post(
        "/v1/code/write",
        headers=HEADERS,
        json={"path": "app/config.py", "content": "# replaced\n", "dry_run": True},
    ).json()
    assert preview["applied"] is False
    assert preview["changed"] is True
    assert preview["removed_lines"] > 0

    after = client.get("/v1/code/read", params={"path": "app/config.py"}, headers=HEADERS).json()["content"]
    assert after == before, "dry run must not touch the file"


def test_write_saves_and_keeps_a_backup(client):
    from pathlib import Path

    probe = Path(__file__).resolve().parent.parent / "tmp_editor_probe.txt"
    probe.write_text("original\n", encoding="utf-8")
    try:
        result = client.post(
            "/v1/code/write",
            headers=HEADERS,
            json={"path": "tmp_editor_probe.txt", "content": "edited\n", "dry_run": False},
        ).json()
        assert result["applied"] is True
        assert result["backup"] == "tmp_editor_probe.txt.bak"
        assert probe.read_text(encoding="utf-8") == "edited\n"
        assert probe.with_suffix(".txt.bak").read_text(encoding="utf-8") == "original\n"
    finally:
        probe.unlink(missing_ok=True)
        probe.with_suffix(".txt.bak").unlink(missing_ok=True)


def test_write_can_create_a_new_file(client):
    from pathlib import Path

    target = Path(__file__).resolve().parent.parent / "tmp_editor_new.txt"
    target.unlink(missing_ok=True)
    try:
        result = client.post(
            "/v1/code/write",
            headers=HEADERS,
            json={"path": "tmp_editor_new.txt", "content": "hello\n", "dry_run": False},
        ).json()
        assert result["created"] is True
        assert target.read_text(encoding="utf-8") == "hello\n"
    finally:
        target.unlink(missing_ok=True)
