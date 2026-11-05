"""The tool belt has to be honest: measured availability, real runs, no fake output."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import toolbelt
from videoengine.assembly import find_ffmpeg

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalogue() -> dict:
    return json.loads((REPO / "prompts" / "free_toolbelt.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sample_video(isolated_data_root) -> Path:
    """A real 1-second clip made by ffmpeg — nothing downloaded, nothing faked.

    It lives under UAI_DATA_ROOT because that is the only place the media tools accept.
    """

    directory = Path(isolated_data_root) / "toolbelt-media"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "sample.mp4"
    subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=128x72:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-shortest", "-pix_fmt", "yuv420p", str(target)],
        capture_output=True, check=True, timeout=120,
    )
    return target


# --- the registry matches the catalogue ---------------------------------------

def test_every_catalogued_tool_is_registered(catalogue):
    assert len(toolbelt.list_tools()["tools"]) == catalogue["count"]
    for entry in catalogue["tools"]:
        assert toolbelt.get(entry["id"]).name


def test_unknown_tool_is_rejected_with_a_clear_error():
    with pytest.raises(toolbelt.ToolError):
        toolbelt.get("definitely-not-a-tool")


def test_availability_is_measured_not_assumed():
    ok, detail = toolbelt.availability("ffmpeg")
    assert ok is True and "ffmpeg" in detail.lower()

    ok, detail = toolbelt.availability("libreoffice")
    if not ok:  # normal case in CI
        assert detail.startswith("unavailable:")
        assert "install" in detail.lower()


def test_missing_tool_reports_the_install_command():
    """Pillow is optional; when it is absent the answer must say how to fix it."""

    from importlib.util import find_spec

    if find_spec("PIL") is not None:
        pytest.skip("Pillow is installed in this environment")
    ok, detail = toolbelt.availability("pillow")
    assert ok is False
    assert detail.startswith("unavailable: pip install")


def test_run_refuses_to_pretend():
    from importlib.util import find_spec

    if find_spec("PIL") is not None:
        pytest.skip("Pillow is installed in this environment")
    with pytest.raises(toolbelt.ToolUnavailable) as caught:
        toolbelt.run("pillow", {"path": "whatever.png"})
    assert str(caught.value).startswith("unavailable:")


def test_network_tools_are_off_by_default(monkeypatch):
    monkeypatch.delenv("UAI_TOOLS_ALLOW_NETWORK", raising=False)
    toolbelt.refresh()
    ok, detail = toolbelt.availability("httpx")
    assert ok is False
    assert "UAI_TOOLS_ALLOW_NETWORK" in detail
    toolbelt.refresh()


# --- real execution ------------------------------------------------------------

def test_ffmpeg_probe_returns_real_numbers(sample_video):
    result = toolbelt.run("ffmpeg", {"op": "probe", "path": str(sample_video)})
    probe = result["result"]["probe"]
    assert 0.5 < probe["duration"] < 2.0
    assert probe["width"] == 128 and probe["height"] == 72
    assert probe["has_video"] is True


def test_ffmpeg_extract_audio_produces_a_file(sample_video):
    result = toolbelt.run("ffmpeg", {"op": "extract_audio", "path": str(sample_video),
                                     "format": "wav"})
    output = Path(result["result"]["output"])
    assert output.exists() and output.stat().st_size > 100
    output.unlink(missing_ok=True)


def test_ffmpeg_says_so_when_there_is_no_audio_track(isolated_data_root):
    """A video-only file must produce an error, not a zero-byte audio file."""

    directory = Path(isolated_data_root) / "toolbelt-media"
    directory.mkdir(parents=True, exist_ok=True)
    silent = directory / "silent.mp4"
    subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=64x64:rate=10", "-pix_fmt", "yuv420p", str(silent)],
        capture_output=True, check=True, timeout=120,
    )
    with pytest.raises(toolbelt.ToolError) as caught:
        toolbelt.run("ffmpeg", {"op": "extract_audio", "path": str(silent), "format": "wav"})
    assert "stream" in str(caught.value).lower()


def test_ffmpeg_rejects_an_impossible_trim(sample_video):
    with pytest.raises(toolbelt.ToolError):
        toolbelt.run("ffmpeg", {"op": "trim", "path": str(sample_video), "start": 5, "end": 2})


def test_git_tool_is_read_only():
    result = toolbelt.run("git", {"op": "status"})
    assert result["result"]["op"] == "status"

    with pytest.raises(toolbelt.ToolError) as caught:
        toolbelt.run("git", {"op": "commit"})
    assert "read-only" in str(caught.value)


def test_ast_tool_lists_real_symbols():
    result = toolbelt.run("ast", {"path": "app/jarvis.py"})
    names = {item["name"] for item in result["result"]["symbols"]}
    assert {"chat", "status", "detect_intents"} <= names


def test_ast_refuses_paths_outside_the_repo():
    with pytest.raises(toolbelt.ToolError):
        toolbelt.run("ast", {"path": "/etc/passwd"})


def test_sqlite_tool_reads_but_never_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path))
    db = tmp_path / "belt.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE notes (id INTEGER, text TEXT)")
    connection.execute("INSERT INTO notes VALUES (1, 'hello')")
    connection.commit()
    connection.close()

    result = toolbelt.run("sqlite3", {"db": "belt.db", "query": "SELECT text FROM notes"})
    assert result["result"]["rows"] == [{"text": "hello"}]

    with pytest.raises(toolbelt.ToolError):
        toolbelt.run("sqlite3", {"db": "belt.db", "query": "DELETE FROM notes"})


def test_ripgrep_finds_a_known_string():
    result = toolbelt.run("ripgrep", {"pattern": "def claude_tools", "path": "app/toolbelt.py"})
    assert result["result"]["matches"] == 1


# --- discovery -----------------------------------------------------------------

def test_search_maps_plain_words_to_tools():
    for query, expected in (("subtitles", "ffmpeg"), ("spreadsheet", "openpyxl"),
                            ("sql", "sqlite3"), ("gst", None)):
        ids = [row["id"] for row in toolbelt.search(query)["results"]]
        if expected:
            assert expected in ids, (query, ids)
    assert toolbelt.search("")["count"] == 0


def test_summary_separates_available_from_actually_ready():
    summary = toolbelt.summary()
    assert summary["total"] >= 60
    assert summary["ready"] <= summary["available"]
    assert set(summary["ready_ids"]) <= set(summary["available_ids"])


def test_verify_runs_the_catalogues_own_test_command():
    result = toolbelt.verify("git")
    assert result["passed"] is True
    assert result["command"] == "git --version"


def test_claude_schema_only_offers_tools_that_work():
    definitions = toolbelt.claude_tools(only_available=True)
    assert definitions
    names = {item["name"] for item in definitions}
    assert "run_ffmpeg" in names
    for item in definitions:
        assert item["input_schema"]["type"] == "object"
        tool_id = next(tid for tid in toolbelt.list_tools()["tools"]
                       if toolbelt.claude_name(tid["id"]) == item["name"])
        assert toolbelt.get(tool_id["id"]).binding.params


def test_run_from_claude_round_trips():
    result = toolbelt.run_from_claude("run_git", {"op": "branch"})
    assert result["ok"] is True
    with pytest.raises(toolbelt.ToolError):
        toolbelt.run_from_claude("nonsense", {})
