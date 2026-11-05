"""SQLite job queue: durable, restart-safe, and usable without Redis."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.main import app


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    """Fresh database per test; workers stay off so runs are deterministic."""

    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("UAI_JOBS_DISABLE", "1")
    jobs.HANDLERS.pop("test.echo", None)
    jobs.HANDLERS.pop("test.boom", None)
    jobs.init_db()

    @jobs.register("test.echo")
    def _echo(payload, progress):
        progress(50, "half")
        return {"echo": payload, "ok": True}

    @jobs.register("test.boom")
    def _boom(payload, progress):
        raise RuntimeError("handler exploded")

    yield
    jobs.HANDLERS.pop("test.echo", None)
    jobs.HANDLERS.pop("test.boom", None)


# --- core queue ---------------------------------------------------------------

def test_submit_runs_and_completes():
    queued = jobs.submit("test.echo", {"value": 42})
    assert queued["status"] == "queued"
    assert jobs.run_once() is True

    done = jobs.get(queued["id"])
    assert done["status"] == "done"
    assert done["result"] == {"echo": {"value": 42}, "ok": True}
    assert done["progress"] == 100.0
    assert done["attempts"] == 1


def test_failures_are_recorded_not_raised():
    queued = jobs.submit("test.boom", {}, max_attempts=1)  # one shot: no retry
    jobs.run_once()
    failed = jobs.get(queued["id"])
    assert failed["status"] == "failed"
    assert "handler exploded" in failed["error"]
    assert failed["result"]["traceback"]


def test_unknown_kind_is_rejected():
    with pytest.raises(jobs.JobError):
        jobs.submit("does.not.exist", {})


def test_run_once_returns_false_when_empty():
    assert jobs.run_once() is False


def test_jobs_survive_a_restart(tmp_path):
    queued = jobs.submit("test.echo", {"persisted": True})
    # A fresh connection is what a restarted process gets.
    fresh = jobs.get(queued["id"])
    assert fresh["payload"] == {"persisted": True}
    jobs.run_once()
    assert jobs.get(queued["id"])["status"] == "done"


def test_cancel_only_works_while_queued():
    queued = jobs.submit("test.echo", {})
    cancelled = jobs.cancel(queued["id"])
    assert cancelled["status"] == "cancelled"
    assert jobs.run_once() is False

    finished = jobs.submit("test.echo", {})
    jobs.run_once()
    with pytest.raises(jobs.JobError):
        jobs.cancel(finished["id"])


def test_list_filters_by_status():
    first = jobs.submit("test.echo", {})
    jobs.submit("test.echo", {})
    jobs.run_once()
    queued = jobs.list_jobs(status="queued")
    done = jobs.list_jobs(status="done")
    assert len(queued["jobs"]) == 1
    assert len(done["jobs"]) == 1
    assert done["jobs"][0]["id"] == first["id"]


def test_stats_report_kinds_and_counts():
    jobs.submit("test.echo", {})
    stats = jobs.stats()
    assert "test.echo" in stats["kinds"]
    assert stats["counts"]["queued"] >= 1


# --- a real handler (video) ---------------------------------------------------

@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    from videoengine.assembly import find_ffmpeg

    folder = tmp_path_factory.mktemp("jobmedia")
    target = folder / "clip.mp4"
    subprocess.run(
        [
            find_ffmpeg(), "-y",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
        ],
        capture_output=True, check=True, timeout=120,
    )
    return target


def test_real_video_job_completes(isolated_queue, clip, monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_MEDIA_ROOTS", str(clip.parent))
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))

    queued = jobs.submit("video.probe", {"path": str(clip)})
    jobs.run_once()

    result = jobs.get(queued["id"])
    assert result["status"] == "done"
    assert result["result"]["has_video"] is True
    assert result["result"]["duration"] > 2


# --- HTTP surface -------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "jobs-key")
    with TestClient(app) as test_client:
        yield test_client


HEADERS = {"X-API-Key": "jobs-key"}


def test_endpoints_require_key(client):
    assert client.post("/v1/jobs", json={"kind": "test.echo", "payload": {}}).status_code == 401


def test_submit_and_poll_over_http(client):
    created = client.post("/v1/jobs", headers=HEADERS, json={"kind": "test.echo", "payload": {"a": 1}})
    assert created.status_code == 200
    job_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    drained = client.post("/v1/jobs/run-once", headers=HEADERS)
    assert drained.status_code == 200 and drained.json()["worked"] is True

    polled = client.get(f"/v1/jobs/{job_id}", headers=HEADERS)
    assert polled.status_code == 200
    assert polled.json()["status"] == "done"
    assert polled.json()["result"]["echo"] == {"a": 1}


def test_unknown_kind_is_400_over_http(client):
    response = client.post("/v1/jobs", headers=HEADERS, json={"kind": "nope", "payload": {}})
    assert response.status_code == 400


def test_missing_job_is_404(client):
    assert client.get("/v1/jobs/deadbeef", headers=HEADERS).status_code == 404


def test_kinds_endpoint_lists_video_handlers(client):
    body = client.get("/v1/jobs/kinds", headers=HEADERS).json()
    assert "video.cut_silence" in body["kinds"]
    assert body["queue"]["db"].endswith("jobs.db")
