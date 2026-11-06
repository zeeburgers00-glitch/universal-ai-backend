"""One-command video production: planner, timeline maths and a real render."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import command_center
from app.main import app
from videoengine import build_timeline, chunk_ranges, heuristic_plan, to_srt
from videoengine.assembly import FfmpegNotFound, find_ffmpeg

client = TestClient(app)
KEY = "command-test-secret"
HEADERS = {"X-API-Key": KEY}

MODEL_ENV = ["AI_API_KEY", "AI_DEFAULT_MODEL", "AI_BASE_URL",
             "GROQ_API_KEY", "GROQ_DEFAULT_MODEL", "GROQ_BASE_URL",
             "OPENAI_API_KEY", "OPENAI_DEFAULT_MODEL", "OPENAI_BASE_URL"]


@pytest.fixture()
def secured(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", KEY)
    for name in MODEL_ENV:
        monkeypatch.delenv(name, raising=False)
    return KEY


@pytest.fixture()
def isolated_store(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    output = tmp_path / "output"
    jobs.mkdir()
    output.mkdir()
    monkeypatch.setattr(command_center, "DATA_DIR", tmp_path)
    monkeypatch.setattr(command_center, "JOB_DIR", jobs)
    monkeypatch.setattr(command_center, "OUTPUT_DIR", output)
    command_center._JOBS.clear()
    return tmp_path


# --------------------------------------------------------------------- planner
@pytest.mark.parametrize(
    "command,seconds",
    [
        ("make a 10 minute video about tea", 600),
        ("12 second clip on diesel engines", 12),
        ("1 ghanta ki video banado football par", 3600),
        ("2.5 hours documentary", 9000),
        ("90 sec reel", 90),
    ],
)
def test_planner_reads_duration(command, seconds):
    assert heuristic_plan(command)["duration_seconds"] == seconds


def test_planner_reads_aspect_and_topic():
    plan = heuristic_plan("45 second vertical reel about motorcycle repair")
    assert plan["aspect_ratio"] == "9:16"
    assert "motorcycle repair" in plan["topic"]
    assert plan["beats"], "narration must never be empty"


def test_planner_falls_back_to_a_default_duration():
    plan = heuristic_plan("a video about solar panels")
    assert plan["duration_seconds"] > 0
    assert plan["source"] == "heuristic"


# -------------------------------------------------------------------- timeline
def test_long_timeline_is_contiguous_and_exact():
    timeline = build_timeline(title="Long", duration_seconds=3600, scene_seconds=8, beats=["a", "b"])
    assert timeline.duration == pytest.approx(3600, abs=0.01)
    assert len(timeline.scenes) == 450
    # No gaps and no overlaps anywhere in the timeline.
    for previous, current in zip(timeline.scenes, timeline.scenes[1:]):
        assert current.start == pytest.approx(previous.end, abs=0.001)
    assert timeline.scenes[-1].end == pytest.approx(3600, abs=0.01)


def test_timeline_scales_to_a_multi_hour_video():
    timeline = build_timeline(title="Marathon", duration_seconds=3 * 3600, scene_seconds=10)
    assert len(timeline.scenes) == 1080
    assert timeline.duration == pytest.approx(3 * 3600, abs=0.01)


def test_timeline_rejects_impossible_requests():
    with pytest.raises(ValueError):
        build_timeline(title="x", duration_seconds=0)
    with pytest.raises(ValueError):
        build_timeline(title="x", duration_seconds=10, fps=13)


def test_captions_and_chunks_cover_every_scene():
    timeline = build_timeline(title="c", duration_seconds=60, scene_seconds=10,
                              beats=["one two three four five six seven eight nine ten"])
    srt = to_srt(timeline)
    assert "-->" in srt and srt.strip().endswith("ten")
    ranges = chunk_ranges(timeline, chunk_seconds=25)
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(timeline.scenes)
    for (_, left_end), (right_start, _) in zip(ranges, ranges[1:]):
        assert left_end == right_start


# ------------------------------------------------------------------------- API
def test_command_endpoints_are_protected(secured):
    assert client.get("/v1/command/capabilities").status_code == 401
    assert client.post("/v1/command", json={"command": "make a video"}).status_code == 401


def test_capabilities_are_honest_about_what_is_missing(secured, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("VOICE_WORKER_URL", raising=False)
    data = client.get("/v1/command/capabilities", headers=HEADERS).json()
    assert data["works_without_keys"] is True
    joined = " ".join(data["upgrades"])
    assert "PEXELS_API_KEY" in joined and "VOICE_WORKER_URL" in joined


def test_plan_only_command_returns_a_usable_timeline(secured, isolated_store):
    response = client.post(
        "/v1/command",
        headers=HEADERS,
        json={"command": "make a 2 minute video about solar panels", "render": False},
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "planned"
    assert job["timeline"]["scene_count"] == 20
    assert job["timeline"]["duration"] == pytest.approx(120, abs=0.01)
    assert job["plan"]["source"] == "heuristic"
    # The plan must survive a restart.
    assert (isolated_store / "jobs" / f"{job['job_id']}.json").is_file()


def test_two_hour_command_plans_without_rendering(secured, isolated_store):
    response = client.post(
        "/v1/command",
        headers=HEADERS,
        json={"command": "make a 2 hour documentary about the indus river", "render": False},
    )
    assert response.status_code == 202
    timeline = response.json()["timeline"]
    assert timeline["duration"] == pytest.approx(7200, abs=0.01)
    assert timeline["scene_count"] == 900


def test_image_paths_outside_the_data_dir_are_rejected(secured, isolated_store):
    response = client.post(
        "/v1/command",
        headers=HEADERS,
        json={"command": "make a 10 second video", "render": False, "image_paths": ["/etc/passwd"]},
    )
    assert response.status_code == 400


def test_producer_view_is_served(secured):
    page = client.get("/app")
    assert page.status_code == 200
    assert "renderProducer" in page.text
    assert 'href="#/producer"' in page.text


# ---------------------------------------------------------------------- render
def _ffmpeg_or_skip() -> str:
    try:
        return find_ffmpeg()
    except FfmpegNotFound:
        pytest.skip("ffmpeg not available in this environment")


def test_render_job_uses_downloaded_pexels_clips(monkeypatch, secured, isolated_store):
    clip = isolated_store / "stock.mp4"
    clip.write_bytes(b"placeholder")
    monkeypatch.setattr(
        command_center,
        "download_pexels_videos",
        lambda **kwargs: [{
            "path": str(clip),
            "pexels_video_id": 123,
            "source_url": "https://www.pexels.com/video/123/",
            "creator_name": "Test Creator",
            "creator_url": "https://www.pexels.com/@testcreator/",
            "attribution": "Video by Test Creator via Pexels",
        }],
    )
    monkeypatch.setattr(command_center, "find_ffmpeg", lambda: "ffmpeg")
    seen = {}

    def fake_render(timeline, assets_for_scene, output, **kwargs):
        seen.update(assets_for_scene(timeline.scenes[0]))
        return {"duration": 4.0, "size_bytes": 2048}

    monkeypatch.setattr(command_center, "render_timeline", fake_render)
    job_id = "cmd-0123456789abcdef"
    command_center._save({"job_id": job_id, "created_at": command_center._now(), "status": "queued"})
    request = command_center.CommandRequest(command="make a 4 second video about mountains")
    plan = {
        "title": "Mountains", "duration_seconds": 4, "aspect_ratio": "16:9",
        "scene_seconds": 4, "beats": ["Explore the mountains."],
        "visual_prompts": ["mountain landscape"], "source": "heuristic", "language": "en",
        "topic": "mountains",
    }

    command_center._render_job(job_id, request, plan, [])
    job = command_center._load(job_id)
    assert seen["video"] == clip
    assert job["status"] == "completed"
    assert job["stock_footage"]["provider"] == "pexels"
    assert job["stock_footage"]["clip_count"] == 1
    assert job["stock_footage"]["attribution"] == ["Video by Test Creator via Pexels"]


def test_command_renders_a_real_video(secured, isolated_store):
    _ffmpeg_or_skip()
    response = client.post(
        "/v1/command",
        headers=HEADERS,
        json={"command": "make a 4 second video about mountains", "captions": True},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = {}
    for _ in range(120):
        job = client.get(f"/v1/command/{job_id}", headers=HEADERS).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.5)

    assert job["status"] == "completed", job.get("error")
    output = Path(job["output"]["path"])
    assert output.is_file() and output.stat().st_size > 10_000
    assert job["output"]["duration"] == pytest.approx(4, abs=0.4)
    assert job["output"]["resolution"] == "1920x1080"

    # The finished file is downloadable, and only with the key.
    stream = client.get(f"/v1/command/{job_id}/video", headers=HEADERS)
    assert stream.status_code == 200
    assert stream.headers["content-type"] == "video/mp4"
    assert client.get(f"/v1/command/{job_id}/video").status_code == 401
    assert client.get(f"/v1/command/{job_id}/video?key={KEY}").status_code == 200
