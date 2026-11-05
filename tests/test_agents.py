"""The runnable agent runtime: registry, execution, crews, queueing, honesty."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agents, ai_router, jobs
from app.main import app

HEADERS = {"X-API-Key": "agent-key"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_API_KEY", "agent-key")
    monkeypatch.setenv("UAI_JOBS_DISABLE", "1")
    jobs.init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


# --- registry -----------------------------------------------------------------

def test_registry_has_a_full_team():
    assert len(agents.AGENTS) >= 35
    assert len(set(agents.AGENTS)) == len(agents.AGENTS)


def test_every_agent_is_self_describing():
    for entry in agents.AGENTS.values():
        assert entry.name and entry.description, entry.id
        assert entry.category in {"code", "video", "ops", "content", "discovery", "model"}
        assert entry.engine in {"rules", "ffmpeg", "index", "model"}
        assert entry.risk in {"low", "medium", "high"}
        assert isinstance(entry.inputs, dict)


def test_categories_add_up():
    counts = agents.categories()
    assert sum(counts.values()) == len(agents.AGENTS)
    assert counts["video"] >= 6 and counts["code"] >= 8


def test_describe_marks_model_agents():
    described = agents.describe("summarizer")
    assert described["needs_model"] is True
    assert described["engine"] == "model"
    assert agents.describe("seo-planner")["needs_model"] is False


def test_unknown_agent_is_404():
    with pytest.raises(agents.AgentError) as error:
        agents.describe("does-not-exist")
    assert error.value.status == 404


def test_registry_fingerprint_is_stable():
    assert agents.fingerprint() == agents.fingerprint()
    assert len(agents.fingerprint()) == 12


# --- execution ----------------------------------------------------------------

def test_seo_planner_composes_from_the_topic():
    result = agents.run("seo-planner", {"topic": "ffmpeg video editing"})["result"]
    assert len(result["titles"]) >= 4
    assert all("ffmpeg" in title.lower() for title in result["titles"])
    assert "ffmpeg" in result["tags"]
    assert "not keyword-volume data" in result["note"]


def test_tool_scout_finds_a_voice_tool():
    result = agents.run("tool-scout", {"query": "text to speech"})["result"]
    assert result["corpus"] >= 200, "the repo catalog must not shrink (see MINIMUM_REPOS guard)"
    assert result["count"] >= 1


def test_tool_scout_can_search_routes_instead():
    result = agents.run("tool-scout", {"query": "remove silence", "target": "routes"})["result"]
    assert any("/v1/video/" in entry["path"] for entry in result["results"])


def test_import_auditor_reports_the_real_manifest():
    result = agents.run("import-auditor")["result"]
    assert result["declared"] >= 8
    assert result["unused"] == []
    assert result["undeclared"] == []


def test_health_warden_explains_the_probe():
    result = agents.run("health-warden")["result"]
    assert result["status"] in {"ok", "degraded", "fail"}
    assert len(result["checks"]) >= 5


def test_changelog_writer_groups_real_commits():
    result = agents.run("changelog-writer", {"limit": 10})["result"]
    assert result["commits"] >= 1
    assert "markdown" in result and result["markdown"]


def test_route_guard_checks_the_editor_against_the_schema():
    result = agents.run("route-guard")["result"]
    assert result["ok"] is True, result["missing"]
    assert result["ui_calls"] > 0


def test_missing_required_input_is_rejected():
    with pytest.raises(agents.AgentError) as error:
        agents.run("media-prober", {})
    assert error.value.status == 400
    assert "path" in str(error.value)


def test_agent_errors_do_not_leak_as_crashes():
    with pytest.raises(agents.AgentError):
        agents.run("media-prober", {"path": "definitely-missing.mp4"})


def test_schedule_planner_validates_dates():
    result = agents.run("schedule-planner", {"cadence": 2, "start": "2026-12-01"})["result"]
    assert len(result["slots"]) == 4
    with pytest.raises(agents.AgentError):
        agents.run("schedule-planner", {"start": "01/12/2026"})


# --- honesty about models -----------------------------------------------------

def test_model_agent_says_so_when_no_provider(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("No model provider is configured.")

    monkeypatch.setattr(ai_router, "complete", boom)
    with pytest.raises(agents.AgentError) as error:
        agents.run("summarizer", {"text": "hello world"})
    assert error.value.status == 422
    assert "needs a model" in str(error.value)


def test_model_agent_uses_the_provider_when_present(monkeypatch):
    monkeypatch.setattr(
        ai_router, "complete",
        lambda **kwargs: {"text": "Short summary.", "provider": "ollama", "model": "llama3"},
    )
    result = agents.run("summarizer", {"text": "long text"})["result"]
    assert result["text"] == "Short summary."
    assert result["provider"] == "ollama"


# --- crews --------------------------------------------------------------------

def test_crew_chains_agents_in_order():
    result = agents.crew(["repo-scout", "metrics-reporter"])
    assert [step["agent"] for step in result["steps"]] == ["repo-scout", "metrics-reporter"]
    assert result["final"] == "metrics-reporter"
    assert "context" in result["context_keys"]


def test_crew_rejects_unknown_members():
    with pytest.raises(agents.AgentError) as error:
        agents.crew(["repo-scout", "ghost-agent"])
    assert error.value.status == 404


def test_crew_needs_members():
    with pytest.raises(agents.AgentError):
        agents.crew([])


# --- queue integration --------------------------------------------------------

def test_agent_can_run_through_the_job_queue():
    job = jobs.submit("agent.run", {"agent": "seo-planner", "input": {"topic": "sourdough"}})
    assert jobs.run_once() is True
    finished = jobs.get(job["id"])
    assert finished["status"] == "done"
    assert finished["result"]["agent"] == "seo-planner"
    assert finished["result"]["result"]["titles"]


def test_queued_agent_failure_is_recorded_not_raised():
    job = jobs.submit("agent.run", {"agent": "media-prober", "input": {"path": "nope.mp4"}}, max_attempts=1)
    jobs.run_once()
    assert jobs.get(job["id"])["status"] == "failed"


# --- real media ---------------------------------------------------------------

@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    folder = tmp_path_factory.mktemp("agentmedia")
    target = folder / "sample.mp4"
    from videoengine.assembly import find_ffmpeg

    subprocess.run(
        [
            find_ffmpeg(), "-y",
            "-f", "lavfi", "-i", "testsrc=size=240x180:rate=10:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
        ],
        capture_output=True, check=True, timeout=120,
    )
    return target


def test_video_agents_work_on_a_real_clip(clip, monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("UAI_MEDIA_ROOTS", str(clip.parent))

    probed = agents.run("media-prober", {"path": str(clip)})["result"]
    assert probed["has_video"] is True
    assert probed["width"] == 240

    packaged = agents.run("publish-packager", {"path": str(clip), "title": "Demo"})["result"]
    assert packaged["title"] == "Demo"
    assert packaged["manifest"]["chapter_markdown"]

    thumbs = agents.run("thumbnail-designer", {"path": str(clip), "count": 2})["result"]
    assert len(thumbs["thumbnails"]) == 2


def test_video_agent_refuses_audio_job_without_audio(clip, monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("UAI_MEDIA_ROOTS", str(clip.parent))
    with pytest.raises(agents.AgentError) as error:
        agents.run("video-editor", {"path": str(clip)})
    assert error.value.status == 422
    assert "audio" in str(error.value)


# --- HTTP surface -------------------------------------------------------------

def test_endpoints_require_a_key(client):
    assert client.get("/v1/agents/runtime").status_code == 401


def test_list_and_describe_over_http(client):
    listing = client.get("/v1/agents/runtime", headers=HEADERS).json()
    assert listing["count"] >= 35
    single = client.get("/v1/agents/runtime/seo-planner", headers=HEADERS).json()
    assert single["id"] == "seo-planner"
    assert client.get("/v1/agents/runtime/ghost", headers=HEADERS).status_code == 404


def test_filter_by_category_and_engine(client):
    video = client.get("/v1/agents/runtime", params={"category": "video"}, headers=HEADERS).json()
    assert video["count"] >= 6
    models = client.get("/v1/agents/runtime", params={"engine": "model"}, headers=HEADERS).json()
    assert all(entry["needs_model"] for entry in models["agents"])


def test_run_endpoint_returns_the_result(client):
    response = client.post(
        "/v1/agents/runtime/title-suggester/run",
        headers=HEADERS,
        json={"input": {"topic": "budget cameras", "count": 3}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "title-suggester"
    assert len(body["result"]["titles"]) == 3
    assert body["elapsed_ms"] >= 0


def test_crew_route_is_not_shadowed_by_the_dynamic_route(client):
    """`/crew/run` used to be parsed as agent_id='crew' and 404'd."""

    response = client.post(
        "/v1/agents/runtime/crew/run",
        headers=HEADERS,
        json={"agents": ["health-warden", "metrics-reporter"], "input": {}},
    )
    assert response.status_code == 200
    assert response.json()["final"] == "metrics-reporter"


def test_submit_endpoint_queues_an_agent_job(client):
    created = client.post(
        "/v1/agents/runtime/seo-planner/submit",
        headers=HEADERS,
        json={"input": {"topic": "hiking gear"}},
    ).json()
    assert created["kind"] == "agent.run"
    assert created["status"] == "queued"


def test_blueprints_are_labelled_honestly(client):
    body = client.get("/v1/agents/runtime/blueprints", headers=HEADERS).json()
    assert body["count"] >= 40
    assert body["runnable_here"] <= body["count"]
    assert "do not execute" in body["note"]


def test_runs_appear_in_the_audit_trail(client):
    client.post("/v1/agents/runtime/hashtag-smith/run", headers=HEADERS, json={"input": {"topic": "ai video"}})
    recent = client.get("/v1/agents/runtime/runs/recent", headers=HEADERS).json()
    assert recent["count"] >= 1
    assert any(entry["target"] == "hashtag-smith" for entry in recent["runs"])
