"""Cursor-style code assistant: index, search, outline, diff, safe apply, review, plan.

None of these features calls a model provider — that is the point, so none of these
tests needs a key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import code_assistant
from app.main import app

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def indexed():
    return code_assistant.build_index()


# --- index + search -----------------------------------------------------------

def test_index_covers_the_repo(indexed):
    assert indexed["file_count"] > 50
    assert indexed["symbol_count"] > 100
    assert indexed["build_ms"] < 30_000
    assert "py" in indexed["languages"]


def test_search_finds_a_known_symbol():
    result = code_assistant.search("load_env_file", limit=5)
    assert result["total"] >= 1
    assert any(hit["path"] == "app/config.py" for hit in result["hits"])


def test_search_ranks_filename_hits_highly():
    hits = code_assistant.search("quota", limit=10)["hits"]
    assert hits
    assert hits[0]["score"] >= 3


def test_search_rejects_tiny_queries():
    with pytest.raises(code_assistant.CodeAssistantError):
        code_assistant.search("a")


# --- outline ------------------------------------------------------------------

def test_outline_lists_symbols_and_imports():
    outline = code_assistant.outline("app/quota.py")
    names = {symbol["name"] for symbol in outline["symbols"]}
    assert {"status", "record", "mark_exhausted"} <= names
    assert outline["language"] == "py"
    assert isinstance(outline["imports"], list)


# --- path safety --------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "app/../../secrets.txt"])
def test_paths_cannot_escape_the_repo(bad):
    with pytest.raises(code_assistant.CodeAssistantError):
        code_assistant.safe_path(bad)


def test_missing_file_is_rejected():
    with pytest.raises(code_assistant.CodeAssistantError):
        code_assistant.safe_path("app/definitely_not_here.py")


# --- diff / apply -------------------------------------------------------------

def test_diff_does_not_touch_the_file():
    target = REPO / "app" / "quota.py"
    before = target.read_text(encoding="utf-8")
    preview = code_assistant.propose_edit("app/quota.py", "DEFAULT_CAPS", "DEFAULT_CAPS_ALIAS")
    assert preview["added_lines"] >= 1
    assert preview["diff"].startswith("---")
    assert target.read_text(encoding="utf-8") == before, "diff must never write"


def test_apply_is_dry_by_default_and_writes_when_asked():
    probe = REPO / "tmp_apply_probe.txt"
    probe.write_text("alpha beta gamma\n", encoding="utf-8")
    try:
        dry = code_assistant.apply_edit("tmp_apply_probe.txt", "beta", "BETA")
        assert dry["applied"] is False
        assert probe.read_text(encoding="utf-8") == "alpha beta gamma\n"

        live = code_assistant.apply_edit("tmp_apply_probe.txt", "beta", "BETA", dry_run=False)
        assert live["applied"] is True
        assert probe.read_text(encoding="utf-8") == "alpha BETA gamma\n"
        assert (REPO / "tmp_apply_probe.txt.bak").is_file(), "a backup must be kept"
    finally:
        probe.unlink(missing_ok=True)
        (REPO / "tmp_apply_probe.txt.bak").unlink(missing_ok=True)


def test_apply_rejects_text_that_is_not_there():
    with pytest.raises(code_assistant.CodeAssistantError):
        code_assistant.propose_edit("app/quota.py", "this string does not exist 12345", "x")


# --- review -------------------------------------------------------------------

def test_secret_patterns_catch_obvious_leaks():
    sample = 'GROQ_API_KEY = "sk-abcdefghijklmnopqrstuvwx"\npassword = "hunter2hunter2hunter2"'
    assert any(pattern.search(sample) for pattern in code_assistant.SECRET_PATTERNS)


def test_review_reports_structured_findings():
    result = code_assistant.review(["app/code_assistant.py"])
    assert result["mode"] == "heuristic"
    assert result["files_reviewed"] == 1
    assert isinstance(result["by_severity"], dict)
    for finding in result["findings"][:10]:
        assert {"path", "line", "rule", "severity"} <= set(finding)


# --- scaffold / commit / plan -------------------------------------------------

def test_test_scaffold_produces_runnable_shaped_code():
    scaffold = code_assistant.test_scaffold("app/config.py")
    assert scaffold["target"] == "app/config.py"
    assert scaffold["suggested_test_file"].startswith("tests/test_")
    assert "import app.config as target" in scaffold["content"]
    assert "def test_" in scaffold["content"]
    compile(scaffold["content"], "<scaffold>", "exec")  # must at least be valid Python


def test_commit_message_reports_changed_files():
    result = code_assistant.commit_message()
    assert "changed_files" in result
    if result["changed_files"]:
        assert result["suggestion"].split(":")[0] in {"feat", "fix", "test", "docs", "chore"}


def test_plan_lists_related_files():
    plan = code_assistant.plan("make the free quota rotation smarter")
    assert len(plan["steps"]) == 6
    assert plan["related_files"], "the plan should point at real files"
    assert plan["model_available"] in {True, False}


# --- HTTP surface -------------------------------------------------------------

def test_endpoints_require_the_api_key(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "code-secret")
    with TestClient(app) as client:
        assert client.post("/v1/code/index").status_code == 401
        assert client.get("/v1/code/search?q=quota").status_code == 401
        assert client.post("/v1/code/plan", json={"goal": "add caching"}).status_code == 401


def test_endpoints_answer_with_the_key(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "code-secret")
    headers = {"X-API-Key": "code-secret"}
    with TestClient(app) as client:
        indexed = client.post("/v1/code/index", headers=headers)
        assert indexed.status_code == 200
        assert indexed.json()["file_count"] > 50

        found = client.get("/v1/code/search", params={"q": "require_api_key"}, headers=headers)
        assert found.status_code == 200 and found.json()["total"] >= 1

        outline = client.post("/v1/code/outline", headers=headers, json={"path": "app/quota.py"})
        assert outline.status_code == 200

        blocked = client.post("/v1/code/outline", headers=headers, json={"path": "../../etc/passwd"})
        assert blocked.status_code == 400
