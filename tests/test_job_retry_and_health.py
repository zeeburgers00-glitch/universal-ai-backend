"""Job retries, live progress streaming, and the deep health probe."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import health_deep, jobs
from app.main import app


@pytest.fixture(autouse=True)
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("UAI_JOBS_DISABLE", "1")
    monkeypatch.setenv("UAI_JOBS_BACKOFF", "0.1")
    monkeypatch.setenv("BACKEND_API_KEY", "retry-key")
    jobs.HANDLERS.pop("t.flaky", None)
    jobs.HANDLERS.pop("t.always", None)
    jobs.init_db()

    state = {"calls": 0}

    @jobs.register("t.flaky")
    def _flaky(payload, progress):
        state["calls"] += 1
        if state["calls"] < 3:
            raise RuntimeError(f"transient failure {state['calls']}")
        return {"calls": state["calls"]}

    @jobs.register("t.always")
    def _always(payload, progress):
        raise RuntimeError("permanent failure")

    yield state
    jobs.HANDLERS.pop("t.flaky", None)
    jobs.HANDLERS.pop("t.always", None)


def _drain(rounds: int = 10, pause: float = 0.15) -> None:
    """Give retries time to clear their backoff, then let the run loop continue."""

    for _ in range(rounds):
        jobs.run_once()
        time.sleep(pause)


# --- retries ------------------------------------------------------------------

def test_transient_failure_is_retried_then_succeeds(queue):
    job = jobs.submit("t.flaky", {}, max_attempts=3)
    _drain()

    final = jobs.get(job["id"])
    assert final["status"] == "done"
    assert final["attempts"] == 3
    assert final["result"] == {"calls": 3}
    assert final["last_error"].startswith("RuntimeError: transient")


def test_permanent_failure_stops_at_max_attempts(queue):
    job = jobs.submit("t.always", {}, max_attempts=2)
    _drain()

    final = jobs.get(job["id"])
    assert final["status"] == "failed"
    assert final["attempts"] == 2, "must not exceed max_attempts"
    assert "permanent failure" in final["error"]
    assert final["result"]["traceback"]


def test_backoff_delays_the_next_attempt(queue):
    job = jobs.submit("t.always", {}, max_attempts=3)
    jobs.run_once()

    pending = jobs.get(job["id"])
    assert pending["status"] == "queued"
    assert pending["run_after"] > time.time() - 1

    # Nothing to claim until the backoff expires.
    assert jobs.run_once() is False
    time.sleep(0.15)
    assert jobs.run_once() is True


def test_backoff_grows_and_is_capped():
    assert jobs.backoff_seconds(1) < jobs.backoff_seconds(3)
    assert jobs.backoff_seconds(20) <= 60.0


def test_max_attempts_is_clamped():
    job = jobs.submit("t.flaky", {}, max_attempts=99)
    assert job["max_attempts"] == 10


def test_default_max_attempts_is_two(monkeypatch):
    monkeypatch.delenv("UAI_JOBS_MAX_ATTEMPTS", raising=False)
    assert jobs.max_attempts_default() == 2


def test_old_databases_are_migrated(tmp_path, monkeypatch):
    import sqlite3

    legacy = tmp_path / "legacy" / "jobs.db"
    legacy.parent.mkdir(parents=True)
    connection = sqlite3.connect(legacy)
    connection.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,"
        " status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT '',"
        " result TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,"
        " started_at REAL, finished_at REAL)"
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "legacy"))
    jobs.init_db()
    job = jobs.submit("t.flaky", {})
    assert job["max_attempts"] >= 1
    assert jobs.get(job["id"])["run_after"] >= 0


# --- server-sent events -------------------------------------------------------

def test_events_stream_reaches_a_terminal_state():
    with TestClient(app) as client:
        created = client.post(
            "/v1/jobs",
            headers={"X-API-Key": "retry-key"},
            json={"kind": "t.always", "payload": {}, "max_attempts": 1},
        ).json()

        # Workers are disabled in this suite; run the job so the stream has a
        # terminal state to report (the framing is what is under test here).
        jobs.run_once()

        frames: list[str] = []
        with client.stream(
            "GET", f"/v1/jobs/{created['id']}/events?timeout=20",
            headers={"X-API-Key": "retry-key"},
        ) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith(("data:", "event:")):
                    frames.append(line)
                if len(frames) > 40:
                    break

    assert any('"kind": "t.always"' in frame for frame in frames)
    assert any(frame == "event: done" for frame in frames), frames[-3:]


def test_events_for_unknown_job_are_handled():
    with TestClient(app) as client:
        with client.stream("GET", "/v1/jobs/nope/events?timeout=5",
                           headers={"X-API-Key": "retry-key"}) as response:
            body = "".join(response.iter_lines())
    assert "job not found" in body


# --- deep health --------------------------------------------------------------

def test_deep_health_reports_every_check():
    report = health_deep.probe()
    names = {check["name"] for check in report["checks"]}
    assert {"api_key", "data_root", "job_db", "disk", "ffmpeg", "queue"} <= names
    assert report["status"] in {"ok", "degraded", "fail"}
    assert report["elapsed_ms"] >= 0


def test_deep_health_flags_a_missing_key(monkeypatch):
    monkeypatch.delenv("BACKEND_API_KEY", raising=False)
    report = health_deep.probe()
    check = next(item for item in report["checks"] if item["name"] == "api_key")
    assert check["ok"] is False
    assert "api_key" in report["warnings"]


def test_deep_health_flags_a_read_only_data_root(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("UAI_DATA_ROOT", str(blocked / "data"))
    report = health_deep.probe()
    assert "data_root" in report["critical_failed"]
    assert report["status"] == "fail"


def test_deep_health_endpoint_status_codes(monkeypatch):
    with TestClient(app) as client:
        healthy = client.get("/health/deep")
        assert healthy.status_code == 200
        assert healthy.json()["status"] in {"ok", "degraded"}

        blocked = health_deep.probe()
        assert isinstance(blocked["checks"], list)


def test_shallow_health_stays_cheap():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "checks" not in body, "liveness must not do real work"
