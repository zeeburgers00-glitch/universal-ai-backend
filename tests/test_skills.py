"""The skill catalogue: thousands of entries, but only real ones may claim to run."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app import skill_runners, skills
from videoengine.assembly import find_ffmpeg

REPO = Path(__file__).resolve().parent.parent


def _ffmpeg():
    try:
        return find_ffmpeg()
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture(scope="module")
def sample_video(isolated_data_root) -> Path:
    binary = _ffmpeg()
    if not binary:
        pytest.skip("ffmpeg is not available here")
    directory = Path(isolated_data_root) / "skills-media"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "skill-sample.mp4"
    subprocess.run(
        [binary, "-hide_banner", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=160x90:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-pix_fmt", "yuv420p", "-shortest", str(target)],
        capture_output=True, check=True, timeout=120,
    )
    return target


# --- the catalogue -------------------------------------------------------------

def test_catalogue_is_thousands_and_split_honestly():
    stats = skills.stats()
    assert stats["total"] >= 2000, "the request was thousands, not dozens"
    assert stats["native"] >= 800
    assert stats["external"] >= 1000
    assert stats["total"] == stats["native"] + stats["external"]
    assert "available=false" in stats["honesty"]


def test_ids_are_unique_and_stable():
    first = skills.list_skills(limit=200, include_external=True)["total"]
    snapshot = list(skills._load_native())
    assert len(snapshot) == len(set(snapshot))
    skills.refresh()
    assert len(skills._load_native()) == len(snapshot)
    assert skills.list_skills(limit=1, include_external=True)["total"] == first


def test_every_native_skill_declares_what_it_takes_and_gives():
    for skill in skills._load_native().values():
        assert skill.name and skill.description, skill.id
        assert skill.category in {"media", "data", "text", "code", "docs", "tools",
                                  "ai", "system", "recipe"}, skill.id
        if skill.engine not in skill_runners.RUNNERS:
            assert skill.needs, f"{skill.id} has no runner and names no dependency"


def test_availability_refusals_always_explain_themselves():
    for skill in skills._load_native().values():
        ok, detail = skills.availability(skill.id)
        if not ok:
            assert detail.startswith("unavailable:"), (skill.id, detail)


def test_external_skills_are_importable_never_runnable():
    external = skills.list_skills(source="external", limit=5)["skills"]
    assert external
    for item in external:
        assert item["available"] is False
        assert "mcp_ecosystem" in item["detail"]
        assert item["source"] == "external"


def test_stats_breakdown_is_not_empty():
    stats = skills.stats()
    assert stats["by_category"]["media"] > 100
    assert stats["available_now"] > 0
    assert stats["by_subcategory"]


def test_listing_filters_work():
    media = skills.list_skills(category="media", limit=5)
    assert media["total"] > 100
    assert all(item["category"] == "media" for item in media["skills"])

    ready = skills.list_skills(available=True, source="native", limit=5)
    assert ready["total"] > 0
    assert all(item["available"] for item in ready["skills"])


# --- discovery -----------------------------------------------------------------

def test_search_finds_a_video_conversion():
    results = skills.search("convert video to webm", limit=5)["results"]
    assert any("mp4-to-webm" in item["id"] for item in results)


def test_search_finds_text_and_data_skills():
    assert any(item["id"].startswith("text.") for item in skills.search("word frequency")["results"])
    assert any(item["id"].startswith("data.") for item in skills.search("dedupe csv")["results"])


def test_unknown_skill_suggests_something():
    with pytest.raises(KeyError) as caught:
        skills.get("text.stats.inlinee")
    assert "Did you mean" in str(caught.value)


# --- real execution ------------------------------------------------------------

def test_text_stats_returns_real_numbers():
    result = skills.run("text.stats.inline", {"text": "hello world. This is a test!"})
    assert result["ok"] is True
    assert result["result"]["words"] == 6
    assert result["result"]["sentences"] == 2


def test_text_case_op_and_slugify():
    assert skills.run("text.case-upper.inline", {"text": "abc"})["result"]["text"] == "ABC"
    assert skills.run("text.slugify.inline",
                      {"text": "Hello World Again"})["result"]["slug"] == "hello-world-again"


def test_table_dedupe_writes_a_real_file(isolated_data_root):
    data = "name,city\nAli,Zahir Pir\nAli,Zahir Pir\nSara,Multan\n"
    result = skills.run("data.table.op.dedupe.csv", {"data": data, "format": "csv"})
    output = Path(result["result"]["output"])
    assert output.exists()
    assert result["result"]["rows_in"] == 3
    assert result["result"]["rows_out"] == 2
    assert output.read_text().count("Ali") == 1


def test_table_convert_to_json_then_query():
    data = "name,amount\nAli,10\nSara,20\n"
    converted = skills.run("data.table.convert.csv-to-json", {"data": data, "format": "csv"})
    payload = json.loads(Path(converted["result"]["output"]).read_text())
    assert payload == [{"name": "Ali", "amount": "10"}, {"name": "Sara", "amount": "20"}]

    queried = skills.run("data.table.sql.count.csv", {"data": data, "format": "csv"})
    assert queried["result"]["rows_out"] == 1


def test_code_symbols_on_a_real_file():
    result = skills.run("code.python.symbols", {"path": "app/skills.py"})
    names = {item["name"] for item in result["result"]["symbols"]}
    assert {"Skill", "run", "search"} <= names


def test_code_todos_and_secret_scan_on_a_temp_file(isolated_data_root):
    target = Path(isolated_data_root) / "dirty.py"
    target.write_text(
        'API_KEY = "abcdefghijklmnop"\n'
        "def f():\n"
        "    pass  # TODO: finish this\n"
    )
    todos = skills.run("code.python.todos", {"path": str(target)})
    assert todos["result"]["count"] == 1

    secrets = skills.run("code.python.secret-scan", {"path": str(target)})
    assert secrets["result"]["count"] == 1


def test_media_probe_on_a_generated_clip(sample_video):
    result = skills.run("media.probe.mp4", {"path": str(sample_video)})
    probe = result["result"]["probe"]
    assert probe["width"] == 160 and probe["height"] == 90


def test_video_conversion_actually_produces_a_file(sample_video):
    result = skills.run("media.video.convert.mp4-to-mkv-h264",
                        {"path": str(sample_video)})
    output = Path(result["result"]["output"])
    assert output.exists() and output.suffix == ".mkv"
    assert output.stat().st_size > 1000


def test_video_resize_preset_reports_what_it_did(sample_video):
    result = skills.run("media.video.resize.mp4-to-480p", {"path": str(sample_video)})
    assert result["result"]["preset"] == "480p"
    assert Path(result["result"]["output"]).exists()


def test_webm_conversion_uses_an_audio_codec_webm_accepts(sample_video):
    result = skills.run("media.video.convert.mp4-to-webm-vp9", {"path": str(sample_video)})
    output = Path(result["result"]["output"])
    assert output.suffix == ".webm" and output.stat().st_size > 1000


def test_gif_needs_no_manual_timestamps(sample_video):
    result = skills.run("media.video.gif.mp4", {"path": str(sample_video)})
    output = Path(result["result"]["output"])
    assert output.suffix == ".gif" and output.stat().st_size > 500


def test_audio_can_be_extracted_from_a_video_container(sample_video):
    result = skills.run("media.audio.convert.mp4-to-mp3-192k", {"path": str(sample_video)})
    assert Path(result["result"]["output"]).suffix == ".mp3"


def test_csv_to_sqlite_is_really_sqlite(isolated_data_root):
    result = skills.run("data.table.convert.csv-to-sqlite", {"data": "n,c\nA,x\nB,y\n"})
    output = Path(result["result"]["output"])
    assert output.suffix == ".sqlite"
    assert output.read_bytes()[:15] == b"SQLite format 3"

    import sqlite3

    with sqlite3.connect(output) as connection:
        assert connection.execute("select count(*) from data").fetchone()[0] == 2


def test_recipe_runs_its_default_agent_without_a_model_key():
    result = skills.run("recipe.health-report", {})
    assert result["result"]["steps"] == 1
    assert result["result"]["results"][0]["agent"] == "health-warden"


def test_image_skill_works_when_imagemagick_is_present(isolated_data_root):
    import shutil

    if not (shutil.which("convert") or shutil.which("magick")):
        pytest.skip("imagemagick is not installed here")
    binary = _ffmpeg()
    if not binary:
        pytest.skip("ffmpeg is not available here")
    photo = Path(isolated_data_root) / "skills-media" / "photo.png"
    photo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([binary, "-hide_banner", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=64x64:d=1", "-frames:v", "1", str(photo)],
                   capture_output=True, check=True, timeout=120)
    result = skills.run("media.image.convert.png-to-jpg-q85", {"path": str(photo)})
    output = Path(result["result"]["output"])
    assert output.suffix == ".jpg" and output.stat().st_size > 100


# --- refusals ------------------------------------------------------------------

def test_external_skill_run_is_refused_with_the_reason():
    external_id = next(iter(skills._load_external()))
    with pytest.raises(skill_runners.SkillUnavailable) as caught:
        skills.run(external_id, {})
    assert str(caught.value).startswith("unavailable:")
    assert "MCP" in str(caught.value) or "install" in str(caught.value)


def test_docs_skill_names_the_missing_binary():
    import shutil

    if shutil.which("pandoc"):
        pytest.skip("pandoc is installed here")
    with pytest.raises(skill_runners.SkillUnavailable) as caught:
        skills.run("docs.convert.md-to-pdf", {"path": "README.md"})
    assert "pandoc" in str(caught.value)


def test_provider_skill_without_a_key_says_which_env_var(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    with pytest.raises(skill_runners.SkillUnavailable) as caught:
        skills.run("ai.groq.chat", {"prompt": "hi"})
    assert "GROQ_API_KEY" in str(caught.value)


def test_bad_arguments_are_422_not_500():
    with pytest.raises(skill_runners.SkillInputError):
        skills.run("text.stats.inline", {})  # no text, no path


# --- HTTP surface --------------------------------------------------------------

def test_http_catalogue_stats_list_and_search():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    headers = {"X-API-Key": "skills-test-secret"}

    import os

    previous = os.environ.get("BACKEND_API_KEY")
    os.environ["BACKEND_API_KEY"] = "skills-test-secret"
    try:
        stats = client.get("/v1/skills/stats", headers=headers)
        assert stats.status_code == 200 and stats.json()["total"] >= 2000

        listing = client.get("/v1/skills?category=media&limit=3", headers=headers)
        assert listing.status_code == 200
        assert len(listing.json()["skills"]) == 3

        found = client.get("/v1/skills/search?q=dedupe%20csv&limit=3", headers=headers)
        assert found.status_code == 200
        assert found.json()["results"][0]["id"].startswith("data.")

        detail = client.get("/v1/skills/text.stats.inline", headers=headers)
        assert detail.status_code == 200 and detail.json()["engine"] == "text_op"

        missing = client.get("/v1/skills/text.nope.inline", headers=headers)
        assert missing.status_code == 404

        ran = client.post("/v1/skills/text.stats.inline/run", headers=headers,
                          json={"args": {"text": "one two three"}})
        assert ran.status_code == 200 and ran.json()["result"]["words"] == 3

        bad = client.post("/v1/skills/text.stats.inline/run", headers=headers, json={"args": {}})
        assert bad.status_code == 422

        external_id = next(iter(skills._load_external()))
        refused = client.post(f"/v1/skills/{external_id}/run", headers=headers, json={"args": {}})
        assert refused.status_code == 503
        assert refused.json()["detail"].startswith("unavailable:")
    finally:
        if previous is None:
            os.environ.pop("BACKEND_API_KEY", None)
        else:
            os.environ["BACKEND_API_KEY"] = previous


# --- from JARVIS ---------------------------------------------------------------

def test_jarvis_runs_a_skill_by_id():
    from app import jarvis

    answer = jarvis.chat('skill text.stats.inline text="a b c"')
    assert '"words": 3' in answer["reply"]
    assert answer["intent"] == "skill:text.stats.inline"


def test_jarvis_resolves_a_skill_sentence_to_an_id():
    from app import jarvis

    answer = jarvis.chat("skill convert video to webm path=/nonexistent.mp4")
    reply = answer["reply"]
    assert "media.video.convert.mp4-to-webm-vp9" in reply
    assert "nahi chala" in reply  # honest refusal, not a fabricated file


def test_jarvis_reports_the_skill_count_when_asked():
    from app import jarvis

    reply = jarvis.chat("kitne skills hain?")["reply"]
    assert "registered" in reply and "native" in reply
