"""Local video toolkit — real FFmpeg runs on really generated media."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import video_tools
from app.main import app

FFMPEG = shutil.which("ffmpeg")


def _ffmpeg() -> str:
    from videoengine.assembly import find_ffmpeg

    return find_ffmpeg()


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    """Tiny clip: 2s tone, 2s silence, 2s tone — with video, so silence detect has audio."""

    folder = tmp_path_factory.mktemp("media")
    clip = folder / "talking.mp4"
    subprocess.run(
        [
            _ffmpeg(), "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=6",
            "-f", "lavfi", "-i",
            "aevalsrc='if(between(t,2,4),0,sin(2*PI*440*t))':s=44100:d=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip),
        ],
        capture_output=True, check=True, timeout=180,
    )
    return folder


@pytest.fixture(autouse=True)
def data_root(monkeypatch, tmp_path, media_dir):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path / "data"))
    # Generated media lives in pytest's temp dir, so declare it as a media root —
    # the same mechanism a deployment uses for a mounted volume.
    monkeypatch.setenv("UAI_MEDIA_ROOTS", str(media_dir))


# --- probe --------------------------------------------------------------------

def test_probe_reads_real_metadata(media_dir):
    info = video_tools.probe_media(media_dir / "talking.mp4")
    assert 5.5 < info["duration"] < 6.5
    assert info["width"] == 320 and info["height"] == 240
    assert info["has_video"] and info["has_audio"]
    assert info["size_bytes"] > 1000


def test_probe_rejects_non_media(tmp_path):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("not a video", encoding="utf-8")
    with pytest.raises(video_tools.VideoToolError):
        video_tools.probe_media(bogus)


# --- silence ------------------------------------------------------------------

def test_silence_detection_finds_the_gap(media_dir):
    silences = video_tools.detect_silences(media_dir / "talking.mp4", threshold_db=-30, min_silence=0.5)
    assert silences, "the 2s silent stretch should be detected"
    assert any(1.5 <= silence["start"] <= 2.5 for silence in silences)


def test_cut_silence_shortens_the_file(media_dir):
    result = video_tools.cut_silence(str(media_dir / "talking.mp4"), threshold_db=-30, min_silence=0.5)
    assert Path(result["output"]).is_file()
    assert result["new_duration"] < result["original_duration"] - 1.0
    assert result["segments_kept"] >= 2


def test_chapters_are_monotonic(media_dir):
    result = video_tools.chapters(str(media_dir / "talking.mp4"), min_chapter=5)
    starts = [chapter["start"] for chapter in result["chapters"]]
    assert starts == sorted(starts)
    assert result["chapters"][0]["start"] == 0.0
    assert ":" in result["youtube_description"]


# --- thumbnails / loudness / clips -------------------------------------------

def test_thumbnails_produce_distinct_frames(media_dir):
    result = video_tools.thumbnails(str(media_dir / "talking.mp4"), count=3, width=640)
    assert result["count"] == 3
    sizes = {item["size_bytes"] for item in result["thumbnails"]}
    assert all(size > 500 for size in sizes)
    positions = [item["at_seconds"] for item in result["thumbnails"]]
    assert positions == sorted(positions)


def test_loudnorm_writes_a_new_file(media_dir):
    result = video_tools.loudnorm(str(media_dir / "talking.mp4"), target_lufs=-14)
    assert Path(result["output"]).is_file()
    assert Path(result["output"]).stat().st_size > 1000


def test_vertical_clip_crops_to_phone_aspect(media_dir):
    result = video_tools.vertical_clip(str(media_dir / "talking.mp4"), 0, 2, aspect="9:16")
    info = video_tools.probe_media(Path(result["output"]))
    assert result["resolution"] == "1080x1920"
    assert info["width"] == 1080 and info["height"] == 1920


def test_clip_range_is_validated(media_dir):
    with pytest.raises(video_tools.VideoToolError):
        video_tools.vertical_clip(str(media_dir / "talking.mp4"), 30, 40)


# --- subtitles ----------------------------------------------------------------

def test_srt_to_vtt_and_back(media_dir):
    srt = media_dir / "captions.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\nhello there\n\n2\n00:00:04,000 --> 00:00:06,000\nbye\n",
        encoding="utf-8",
    )
    vtt = video_tools.convert_subtitles(str(srt), "vtt")
    assert vtt["format"] == "vtt" and vtt["cues"] == 2
    content = Path(vtt["output"]).read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:03.500" in content

    back = video_tools.convert_subtitles(vtt["output"], "srt")
    assert Path(back["output"]).read_text(encoding="utf-8").startswith("1\n")


# --- path safety --------------------------------------------------------------

def test_paths_outside_allowed_roots_are_rejected():
    with pytest.raises(video_tools.VideoToolError):
        video_tools.resolve_input("/etc/hostname")


def test_unsupported_extension_is_rejected(tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("x", encoding="utf-8")
    with pytest.raises(video_tools.VideoToolError):
        video_tools.resolve_input(str(doc))


# --- HTTP surface -------------------------------------------------------------

def test_video_routes_require_the_key(monkeypatch, media_dir):
    monkeypatch.setenv("BACKEND_API_KEY", "video-key")
    with TestClient(app) as client:
        assert client.post("/v1/video/probe", json={"path": str(media_dir / "talking.mp4")}).status_code == 401


def test_video_probe_route_works(monkeypatch, media_dir):
    monkeypatch.setenv("BACKEND_API_KEY", "video-key")
    with TestClient(app) as client:
        response = client.post(
            "/v1/video/probe",
            headers={"X-API-Key": "video-key"},
            json={"path": str(media_dir / "talking.mp4")},
        )
    assert response.status_code == 200
    assert response.json()["has_audio"] is True


def test_video_route_reports_bad_paths_as_400(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "video-key")
    with TestClient(app) as client:
        response = client.post(
            "/v1/video/probe",
            headers={"X-API-Key": "video-key"},
            json={"path": "/etc/hostname"},
        )
    assert response.status_code == 400
