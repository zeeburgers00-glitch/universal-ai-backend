"""The prompt pack is a deliverable, so it is tested like one."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROMPTS = REPO / "prompts"


@pytest.fixture(scope="module")
def toolbelt() -> dict:
    return json.loads((PROMPTS / "free_toolbelt.json").read_text(encoding="utf-8"))


def test_prompt_files_exist():
    for name in ("README.md", "JARVIS_BUILD_PROMPT.md", "JARVIS_FULL_TOOLBELT_PROMPT.md",
                 "free_toolbelt.json"):
        path = PROMPTS / name
        assert path.is_file(), name
        assert path.stat().st_size > 500, f"{name} looks empty"


def test_toolbelt_count_matches_the_list(toolbelt):
    assert toolbelt["count"] == len(toolbelt["tools"])
    assert toolbelt["count"] >= 60, "the whole point is a full belt, not a sampler"


def test_every_tool_is_actionable(toolbelt):
    for tool in toolbelt["tools"]:
        for field in ("id", "name", "category", "kind", "install", "does", "test"):
            assert tool.get(field), f"{tool.get('id')} is missing {field}"
        assert tool["free"] is True, f"{tool['id']} must be free"
        assert isinstance(tool["offline"], bool)
        assert isinstance(tool["needs"], list)


def test_categories_cover_the_real_work(toolbelt):
    counts = Counter(tool["category"] for tool in toolbelt["tools"])
    assert {"media", "docs", "code", "data", "ai", "web", "ops", "comms", "security"} <= set(counts)
    assert counts["media"] >= 10


def test_most_tools_work_offline(toolbelt):
    offline = sum(1 for tool in toolbelt["tools"] if tool["offline"])
    assert offline / len(toolbelt["tools"]) > 0.6, "a free belt should mostly run without network"


def test_unofficial_tools_are_labelled(toolbelt):
    caveats = {tool["id"] for tool in toolbelt["tools"] if tool.get("tos_caveat")}
    assert {"yt-dlp", "edge-tts", "duckduckgo-search", "nominatim"} <= caveats


def test_only_free_signups_need_credentials(toolbelt):
    signup_needs = {"bot_token", "webhook_url", "app_password", "cloud_account"}
    for tool in toolbelt["tools"]:
        for need in tool["needs"]:
            if need in signup_needs:
                continue
            assert need in {"network", "ffmpeg", "~400MB disk", "local_gpu_or_cpu"}, \
                f"{tool['id']} has an unexplained requirement: {need}"


def test_waves_add_up_to_the_belt(toolbelt):
    text = (PROMPTS / "JARVIS_FULL_TOOLBELT_PROMPT.md").read_text(encoding="utf-8")
    waves = [int(match) for match in re.findall(r"^### Wave \d+ .*?\((\d+)", text, re.MULTILINE)]
    assert len(waves) == 5, waves
    assert sum(waves) == toolbelt["count"], f"waves claim {sum(waves)} of {toolbelt['count']} tools"


def test_prompt_forbids_faking():
    text = (PROMPTS / "JARVIS_FULL_TOOLBELT_PROMPT.md").read_text(encoding="utf-8").lower()
    assert "never fake" in text
    assert "unavailable:" in text
    assert "not free" in text or "genuinely not free" in text


def test_build_prompt_has_a_definition_of_done():
    text = (PROMPTS / "JARVIS_BUILD_PROMPT.md").read_text(encoding="utf-8")
    assert "Definition of done" in text
    assert "pytest -q" in text
    assert "BLOCKED:" in text
