"""Supabase: report what is really there, sync memory, never leak the key."""

from __future__ import annotations

import json

import pytest

from app import jarvis, mind, supabase_db


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path))
    yield


def _configure(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://yqutpgefnykkqjifbgec.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key-with-length")


# --- unconfigured --------------------------------------------------------------

def test_unconfigured_reports_the_two_variables_it_needs():
    state = supabase_db.status()
    assert state["configured"] is False
    assert "SUPABASE_URL" in state["next"]
    assert "service role" in state["next"]

    with pytest.raises(supabase_db.SupabaseUnavailable) as caught:
        supabase_db.ping()
    assert str(caught.value).startswith("unavailable: set SUPABASE_URL")


def test_anon_key_would_not_be_enough():
    """The docs say service role for a reason: RLS is on with no policies."""

    text = supabase_db.status()["honesty"]
    assert "durable" in text
    assert "PostgREST" in text


# --- configured ----------------------------------------------------------------

def test_status_never_returns_the_key(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(supabase_db, "_request", lambda *a, **k: (200, []))
    state = supabase_db.status()
    serialised = json.dumps(state)
    assert "service-role-key-with-length" not in serialised
    assert state["configured"] is True
    assert state["project_ref"] == "yqutpgefnykkqjifbgec"
    assert state["ping"]["reachable"] is True


def test_ping_measures_a_real_call(monkeypatch):
    _configure(monkeypatch)
    seen: list[tuple] = []

    def fake_request(method, path, *, params=None, body=None, prefer=None, timeout=12.0):
        seen.append((method, path, params))
        return 200, []

    monkeypatch.setattr(supabase_db, "_request", fake_request)
    result = supabase_db.ping()
    assert result["reachable"] is True
    assert seen == [("GET", "/rest/v1/", {"limit": "1"})]


def test_schema_report_splits_present_missing_and_blocked(monkeypatch):
    _configure(monkeypatch)

    def fake_request(method, path, *, params=None, body=None, prefer=None, timeout=12.0):
        table = path.rsplit("/", 1)[-1]
        if table in {"uaib_custom_tools", "uaib_runtime_secrets"}:
            return 200, [{"id": "x"}]
        if table == "uaib_finance_entries":
            return 404, {"message": "relation does not exist"}
        return 401, {"message": "no api key"}

    monkeypatch.setattr(supabase_db, "_request", fake_request)
    report = supabase_db.schema_report()
    assert "uaib_custom_tools" in report["present"]
    assert report["missing"] == ["uaib_finance_entries"]
    assert "uaib_jarvis_facts" in report["blocked"]
    assert report["complete"] is False
    assert "20261105140000_uaib_core_tables.sql" in report["next"]


def test_complete_schema_has_nothing_to_do(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(supabase_db, "_request", lambda *a, **k: (200, []))
    report = supabase_db.schema_report()
    assert report["complete"] is True
    assert report["next"] == ""


def test_unreachable_database_is_unavailable_not_silent(monkeypatch):
    _configure(monkeypatch)

    def boom(*args, **kwargs):
        raise supabase_db.SupabaseUnavailable("unavailable: Supabase unreachable (ConnectError)")

    monkeypatch.setattr(supabase_db, "_request", boom)
    with pytest.raises(supabase_db.SupabaseUnavailable):
        supabase_db.ping()


# --- JARVIS durability ---------------------------------------------------------

def test_push_jarvis_upserts_facts_lessons_and_journal(monkeypatch):
    _configure(monkeypatch)
    jarvis.init_db()
    jarvis.remember("name", "Ali")
    mind.init_db()
    mind.add_lesson("Pillow missing blocked thumbnails", source="reflection")
    mind.journal("test entry", mood="khush")

    calls: list[dict] = []

    def fake_request(method, path, *, params=None, body=None, prefer=None, timeout=12.0):
        calls.append({"path": path, "params": params, "body": body, "prefer": prefer})
        return 201, []

    monkeypatch.setattr(supabase_db, "_request", fake_request)
    result = supabase_db.push_jarvis()

    assert result["pushed"] == {"facts": 1, "lessons": 1, "journal": 1}
    assert result["errors"] == []
    facts_call = next(call for call in calls if call["path"].endswith("uaib_jarvis_facts"))
    assert facts_call["params"] == {"on_conflict": "key"}
    assert "merge-duplicates" in facts_call["prefer"]
    assert facts_call["body"][0]["key"] == "name"


def test_push_jarvis_reports_a_failed_table_instead_of_claiming_success(monkeypatch):
    _configure(monkeypatch)
    jarvis.init_db()
    jarvis.remember("name", "Ali")

    def fake_request(method, path, *, params=None, body=None, prefer=None, timeout=12.0):
        return (500, {"message": "boom"}) if path.endswith("uaib_jarvis_facts") else (201, [])

    monkeypatch.setattr(supabase_db, "_request", fake_request)
    result = supabase_db.push_jarvis()
    assert result["pushed"]["facts"] == 0
    assert result["errors"] == ["facts: HTTP 500"]


def test_pull_facts_restores_local_memory(monkeypatch):
    _configure(monkeypatch)
    jarvis.init_db()

    def fake_request(method, path, *, params=None, body=None, prefer=None, timeout=12.0):
        assert method == "GET" and path.endswith("uaib_jarvis_facts")
        return 200, [{"key": "name", "value": "Ali", "source": "supabase"},
                     {"key": "city", "value": "Zahir Pir", "source": "supabase"}]

    monkeypatch.setattr(supabase_db, "_request", fake_request)
    result = supabase_db.pull_facts()
    assert result["restored"] == 2
    assert {item["key"] for item in jarvis.facts(10)} >= {"name", "city"}


def test_pull_facts_raises_on_a_bad_response(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(supabase_db, "_request", lambda *a, **k: (403, {"message": "denied"}))
    with pytest.raises(supabase_db.SupabaseError):
        supabase_db.pull_facts()
