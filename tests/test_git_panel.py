"""The editor's git panel, exercised against a real throwaway repository."""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from app import git_tools, governance
from app.main import app


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial commit")
    monkeypatch.setenv("UAI_GIT_ROOT", str(root))
    monkeypatch.setenv("BACKEND_API_KEY", "git-key")
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("UAI_REQUIRE_APPROVAL", raising=False)
    governance.reset()
    return root


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


HEADERS = {"X-API-Key": "git-key"}


# --- core ---------------------------------------------------------------------

def test_status_reports_a_clean_repo(repo):
    body = git_tools.status()
    assert body["branch"] == "main"
    assert body["dirty"] is False
    assert body["root"] == str(repo.resolve())


def test_status_sees_a_modification(repo):
    (repo / "hello.py").write_text("print('bye')\n", encoding="utf-8")
    body = git_tools.status()
    assert body["dirty"] is True
    assert body["files"][0]["path"] == "hello.py"
    assert body["files"][0]["code"] == "M"


def test_diff_shows_the_change(repo):
    (repo / "hello.py").write_text("print('bye')\n", encoding="utf-8")
    body = git_tools.diff("hello.py")
    assert "-print('hi')" in body["diff"]
    assert "+print('bye')" in body["diff"]
    assert body["added"] == 1 and body["removed"] == 1


def test_diff_can_read_the_index(repo):
    (repo / "hello.py").write_text("print('staged')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert "print('staged')" in git_tools.diff(staged=True)["diff"]
    assert git_tools.diff()["diff"] == ""


def test_log_lists_commits(repo):
    body = git_tools.log(limit=5)
    assert body["count"] == 1
    assert body["commits"][0]["subject"] == "initial commit"
    assert len(body["commits"][0]["sha"]) == 7


def test_commit_makes_a_real_commit(repo):
    (repo / "new.txt").write_text("data\n", encoding="utf-8")
    result = git_tools.commit("add new file", add_all=True)
    assert result["committed"] is True
    assert result["pushed"] is False
    assert result["subject"] == "add new file"
    assert git_tools.status()["dirty"] is False
    assert git_tools.log(limit=1)["commits"][0]["subject"] == "add new file"


def test_commit_without_changes_fails(repo):
    with pytest.raises(git_tools.GitError):
        git_tools.commit("nothing here", add_all=True)


def test_commit_message_is_validated(repo):
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(git_tools.GitError):
        git_tools.commit("no", add_all=True)


def test_path_escape_is_refused(repo):
    with pytest.raises(git_tools.GitError):
        git_tools.diff("../../etc/passwd")


def test_missing_repository_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("UAI_GIT_ROOT", str(tmp_path / "not-a-repo"))
    with pytest.raises(git_tools.GitError):
        git_tools.status()


# --- HTTP ---------------------------------------------------------------------

def test_routes_require_key(client, repo):
    assert client.get("/v1/git/status").status_code == 401


def test_status_and_log_over_http(client, repo):
    status = client.get("/v1/git/status", headers=HEADERS)
    assert status.status_code == 200
    assert status.json()["branch"] == "main"
    assert client.get("/v1/git/log", headers=HEADERS).json()["count"] >= 1


def test_commit_over_http_is_logged_in_the_audit_trail(client, repo):
    (repo / "http.txt").write_text("hi\n", encoding="utf-8")
    result = client.post(
        "/v1/git/commit",
        headers=HEADERS,
        json={"message": "commit from the editor panel", "add_all": True},
    )
    assert result.status_code == 200
    assert result.json()["committed"] is True

    log = client.get("/v1/governance/audit", headers=HEADERS).json()
    assert any(entry["action"] == "git.commit" for entry in log["entries"])


def test_commit_is_approval_gated_when_enabled(client, repo, monkeypatch):
    monkeypatch.setenv("UAI_REQUIRE_APPROVAL", "1")
    (repo / "gated.txt").write_text("hi\n", encoding="utf-8")
    blocked = client.post("/v1/git/commit", headers=HEADERS, json={"message": "gated commit", "add_all": True})
    assert blocked.status_code == 428

    token = client.post(
        "/v1/governance/approvals",
        headers=HEADERS,
        json={"path": "/v1/git/commit", "reason": "release"},
    ).json()["token"]
    allowed = client.post(
        "/v1/git/commit",
        headers={**HEADERS, "X-Approval-Token": token},
        json={"message": "gated commit", "add_all": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["committed"] is True


def test_bad_diff_path_is_400(client, repo):
    assert client.get("/v1/git/diff", params={"path": "../../etc/passwd"}, headers=HEADERS).status_code == 400
