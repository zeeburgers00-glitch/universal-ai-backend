"""Natural requests become real skills — and unclear ones stay unclear."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import jarvis, skill_runners, skills, task_router
from videoengine.assembly import find_ffmpeg

ROUTED = [
    ("clip.mp4 ko 480p me chhota kar do", "media.video.resize.mp4-to-480p"),
    ("clip.mp4 ko webm banao", "media.video.convert.mp4-to-webm-vp9"),
    ("clip.mp4 se audio mp3 nikal do", "media.audio.convert.mp4-to-mp3-192k"),
    ("clip.mp4 ka gif banao", "media.video.gif.mp4"),
    ("photo.png ko jpg me convert karo", "media.image.convert.png-to-jpg-q85"),
    ("photo.png ko 720px karo", "media.image.resize.png-to-720"),
    ("rows.csv me duplicate hata do", "data.table.op.dedupe.csv"),
    ("app/skills.py me kitne functions hain", "code.python.symbols"),
    ("app/skills.py me koi secret hai kya", "code.python.secret-scan"),
    ("clip.mp4 ka probe karo", "media.probe.mp4"),
    ('text "ali ali sara" ke sabse zyada words batao', "text.word-frequency.inline"),
    ("health batao", "recipe.health-report"),
]

REFUSED = [
    "mujhe website bana do",
    "kal mausam kaisa hoga",
    "meri shaadi kab hogi",
]


@pytest.mark.parametrize("message,expected", ROUTED)
def test_sentences_map_to_real_skill_ids(message, expected):
    plan = task_router.plan(message)
    assert plan is not None, message
    assert plan["skill"] == expected
    assert plan["confidence"] >= 0.75
    skills.get(plan["skill"])  # the id exists in the catalogue, or this raises


def test_plans_carry_usable_arguments():
    plan = task_router.plan("rows.csv me duplicate hata do")
    assert plan["args"]["format"] == "csv"
    assert plan["args"]["path"] == "rows.csv"

    inline = task_router.plan('text "hello hello" ke word count batao')
    assert inline["args"]["text"] == "hello hello"


@pytest.mark.parametrize("message", REFUSED)
def test_unmatched_requests_are_not_guessed(message):
    assert task_router.plan(message) is None


def test_router_only_returns_catalogue_ids():
    for message, _ in ROUTED:
        plan = task_router.plan(message)
        assert skills.get(plan["skill"]).engine in skill_runners.RUNNERS


# --- through JARVIS, with real files -------------------------------------------

@pytest.fixture()
def workspace(isolated_data_root) -> Path:
    root = Path(isolated_data_root)
    binary = find_ffmpeg()
    if not binary:
        pytest.skip("ffmpeg is not available here")
    clip = root / "clip.mp4"
    subprocess.run(
        [binary, "-hide_banner", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=160x90:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-pix_fmt", "yuv420p", "-shortest", str(clip)],
        capture_output=True, check=True, timeout=120,
    )
    (root / "rows.csv").write_text("name,city\nAli,Zahir Pir\nAli,Zahir Pir\nSara,Multan\n")
    return root


def test_jarvis_completes_a_spoken_task(workspace):
    answer = jarvis.chat("clip.mp4 ko 480p me chhota kar do")
    assert answer["intent"] == "skill:media.video.resize.mp4-to-480p"
    assert answer["actions"] and answer["actions"][0]["ok"] is True
    output = Path(answer["actions"][0]["result"]["output"])
    assert output.exists() and output.stat().st_size > 1000


def test_jarvis_finds_a_file_in_the_data_root(workspace):
    answer = jarvis.chat("rows.csv me duplicate hata do")
    assert answer["intent"] == "skill:data.table.op.dedupe.csv"
    result = answer["actions"][0]["result"]
    assert result["rows_in"] == 3 and result["rows_out"] == 2


def test_jarvis_says_it_cannot_rather_than_faking():
    answer = jarvis.chat("mujhe website bana do")
    assert answer["intent"] == "unknown"
    assert "samajh nahi aaya" in answer["reply"]
    assert answer["actions"] == []


def test_a_routed_skill_that_cannot_run_reports_the_reason(workspace):
    answer = jarvis.chat("ghost.mp4 ko 480p me chhota kar do")
    assert "nahi chala" in answer["reply"]
    assert "file not found" in answer["reply"]
    assert answer["actions"][0]["ok"] is False


# --- the model's hands ---------------------------------------------------------

def test_claude_gets_search_and_run_tools():
    names = [tool["name"] for tool in jarvis._skill_tool_definitions()]
    assert names == ["skill_search", "skill_run"]


def test_skill_tools_work_without_any_model_key():
    found = jarvis._skill_tool_dispatch("skill_search", {"query": "convert to webm", "limit": 2})
    assert len(found["results"]) == 2
    assert found["results"][0]["available"] is True

    ran = jarvis._skill_tool_dispatch("skill_run",
                                      {"skill_id": "text.stats.inline", "args": {"text": "a b"}})
    assert ran["result"]["words"] == 2

    refused = jarvis._skill_tool_dispatch("skill_run", {"skill_id": "docs.convert.md->pdf"})
    assert "error" in refused


def test_skill_search_tool_is_honest_about_availability():
    found = jarvis._skill_tool_dispatch("skill_search", {"query": "slack", "limit": 5})
    for item in found["results"]:
        if not item["available"]:
            assert item["detail"].startswith("unavailable:")
