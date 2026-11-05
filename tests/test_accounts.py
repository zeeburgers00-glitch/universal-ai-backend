"""Mail accounts: consent flow, token hygiene, and the things this code refuses to do."""

from __future__ import annotations

import json

import httpx
import pytest

from app import accounts, governance


@pytest.fixture(autouse=True)
def isolated_accounts(tmp_path, monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path))
    accounts.init_db()
    yield tmp_path


def _configure(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-1234567890.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shhh-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/v1/accounts/oauth/callback")


def _fake_google(monkeypatch, *, scopes=None, email="ali@example.com"):
    calls: dict = {"token": [], "get": []}

    def fake_post(url, data, timeout=30.0):
        calls["token"].append(data)
        if data.get("grant_type") == "authorization_code":
            return {"access_token": "access-abc", "refresh_token": "refresh-xyz",
                    "expires_in": 3600, "scope": scopes or accounts.READ_SCOPE}
        return {"access_token": "access-refreshed", "expires_in": 3600}

    def fake_get(url, token, params=None, timeout=30.0):
        calls["get"].append({"url": url, "params": params, "token": token})
        if url.endswith("/profile"):
            return {"emailAddress": email}
        if url.endswith("/messages"):
            return {"messages": [{"id": "m1"}, {"id": "m2"}]}
        return {"id": url.rsplit("/", 1)[-1], "labelIds": ["UNREAD"],
                "snippet": "hello there",
                "payload": {"headers": [
                    {"name": "From", "value": "boss@example.com"},
                    {"name": "Subject", "value": "Kal ki meeting"},
                    {"name": "Date", "value": "Wed, 5 Nov 2026 09:00:00 +0500"},
                ]}}

    monkeypatch.setattr(accounts, "_post_form", fake_post)
    monkeypatch.setattr(accounts, "_get_json", fake_get)
    return calls


def _connect(monkeypatch, *, allow_send=False):
    _configure(monkeypatch)
    calls = _fake_google(monkeypatch,
                        scopes=" ".join((accounts.READ_SCOPE, accounts.SEND_SCOPE))
                        if allow_send else accounts.READ_SCOPE)
    started = accounts.auth_url("personal",
                               scopes=(accounts.SEND_SCOPE,) if allow_send else accounts.DEFAULT_SCOPES)
    connected = accounts.finish("auth-code", started["state"])
    return connected, calls


# --- no credentials, no pretending --------------------------------------------

def test_without_google_credentials_everything_says_unavailable():
    state = accounts.status()
    assert state["oauth_configured"] is False
    assert state["accounts"] == 0

    with pytest.raises(accounts.AccountUnavailable) as caught:
        accounts.auth_url("personal")
    assert str(caught.value).startswith("unavailable: set GOOGLE_CLIENT_ID")


def test_status_lists_what_is_blocked_by_design():
    blocked = " ".join(accounts.status()["blocked_by_design"])
    assert "password" in blocked
    assert "consent" in blocked
    assert "sending mail without" in blocked


# --- consent flow --------------------------------------------------------------

def test_auth_url_is_a_real_google_consent_url(monkeypatch):
    _configure(monkeypatch)
    started = accounts.auth_url("work")
    assert started["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in started["url"]
    assert "prompt=consent" in started["url"]
    assert "gmail.readonly" in started["url"]
    assert started["state"]


def test_read_only_by_default_and_send_is_opt_in(monkeypatch):
    _configure(monkeypatch)
    default = accounts.auth_url("personal")
    assert accounts.SEND_SCOPE not in default["scopes"]

    sending = accounts.auth_url("work", scopes=(accounts.SEND_SCOPE,))
    assert accounts.SEND_SCOPE in sending["scopes"]


def test_finish_stores_a_masked_account(monkeypatch):
    connected, calls = _connect(monkeypatch)
    assert connected["email"] == "ali@example.com"
    assert connected["connected"] is True

    listing = accounts.list_accounts()
    assert listing["count"] == 1
    serialised = json.dumps(listing)
    assert "refresh-xyz" not in serialised
    assert "access-abc" not in serialised
    assert "access-abc" not in json.dumps(connected)


def test_state_is_single_use(monkeypatch):
    _configure(monkeypatch)
    _fake_google(monkeypatch)
    started = accounts.auth_url("personal")
    accounts.finish("code-1", started["state"])
    with pytest.raises(accounts.AccountError):
        accounts.finish("code-1", started["state"])

    with pytest.raises(accounts.AccountError):
        accounts.finish("code-1", "made-up-state")


def test_missing_refresh_token_is_an_explicit_error(monkeypatch):
    _configure(monkeypatch)
    started = accounts.auth_url("personal")
    monkeypatch.setattr(accounts, "_post_form",
                        lambda url, data, timeout=30.0: {"access_token": "a"})
    with pytest.raises(accounts.AccountError) as caught:
        accounts.finish("code", started["state"])
    assert "no refresh token" in str(caught.value)


# --- reading mail --------------------------------------------------------------

def test_messages_are_parsed_and_never_return_tokens(monkeypatch):
    connected, calls = _connect(monkeypatch)
    inbox = accounts.messages(connected["id"], query="is:unread", limit=2)

    assert inbox["count"] == 2
    assert inbox["messages"][0]["from"] == "boss@example.com"
    assert inbox["messages"][0]["subject"] == "Kal ki meeting"
    assert "refresh-xyz" not in json.dumps(inbox)
    assert calls["get"][0]["url"].endswith("/profile")


def test_digest_without_a_model_is_a_faithful_list(monkeypatch):
    connected, _ = _connect(monkeypatch)
    monkeypatch.setattr("app.jarvis.model_available", lambda: False)
    summary = accounts.digest(connected["id"])
    assert summary["used_model"] is False
    assert "boss@example.com" in summary["summary"]
    assert "Kal ki meeting" in summary["summary"]


def test_unknown_account_is_a_clear_error(monkeypatch):
    _configure(monkeypatch)
    with pytest.raises(accounts.AccountError):
        accounts.messages(99)


# --- sending -------------------------------------------------------------------

def test_send_refuses_an_account_without_the_send_scope(monkeypatch):
    connected, _ = _connect(monkeypatch)
    with pytest.raises(accounts.AccountError) as caught:
        accounts.send(connected["id"], to="x@example.com", subject="hi", body="test",
                      confirm=True)
    assert "read-only" in str(caught.value)


def test_send_requires_confirmation(monkeypatch):
    connected, _ = _connect(monkeypatch, allow_send=True)
    with pytest.raises(accounts.AccountError) as caught:
        accounts.send(connected["id"], to="x@example.com", subject="hi", body="test")
    assert "confirm=true" in str(caught.value)


def test_send_happens_only_with_every_key_turned(monkeypatch):
    connected, _ = _connect(monkeypatch, allow_send=True)
    sent: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "sent-1"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            sent.update({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    result = accounts.send(connected["id"], to="x@example.com", subject="Report",
                           body="kal ka plan", confirm=True)
    assert result["sent"] is True and result["id"] == "sent-1"
    assert sent["url"].endswith("/messages/send")

    # and the audit log has a line for it
    log = governance.read_log(limit=20)
    actions = [row["action"] for row in log.get("entries", log.get("events", []))]
    assert "account.send" in actions or any("account.send" in json.dumps(row) for row in
                                            log.get("entries", []))


# --- disconnecting -------------------------------------------------------------

def test_disconnect_deletes_tokens(monkeypatch):
    connected, _ = _connect(monkeypatch)
    db = accounts._db()

    import sqlite3

    with sqlite3.connect(db) as connection:
        before = connection.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    assert before == 1

    result = accounts.disconnect(connected["id"])
    assert result["status"] == "revoked"

    with sqlite3.connect(db) as connection:
        after = connection.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    assert after == 0
