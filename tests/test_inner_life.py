"""Character, mood and the self layer — the parts that make it feel like someone.

Every test here checks a mechanism, not a claim: traits change the prompt, events move five
numbers, reflection reads real logs, and proposals never edit code.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from app import affect, character, jarvis, mind, toolbelt


# --- character -----------------------------------------------------------------

def test_default_character_is_jarvis_like():
    current = character.load()
    assert current["name"] == "JARVIS"
    assert current["preset"] == "jarvis"
    assert set(character.TRAITS) <= set(current["traits"])


def test_presets_change_tone_not_facts():
    friend = character.apply_preset("friend", name="Nova")
    block = character.prompt_block(friend)
    assert "Nova" in block and "yaar" in block
    assert "never change the facts" in block

    analyst = character.apply_preset("analyst")
    assert "bullets" in character.prompt_block(analyst).lower()
    character.apply_preset("jarvis")


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError):
        character.apply_preset("gandalf")


def test_traits_are_clamped_and_persisted():
    character.update(traits={"warmth": 5, "humour": -2})
    current = character.load()
    assert current["traits"]["warmth"] == 1.0
    assert current["traits"]["humour"] == 0.0
    character.apply_preset("jarvis")


def test_language_rule_is_explicit():
    character.update(language="hi")
    assert "Hindi" in character.prompt_block()
    character.update(language="auto")


# --- affect --------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_mood():
    affect.reset()
    yield
    affect.reset()


def test_praise_lifts_mood_and_insult_lowers_it():
    before = affect.decay()["valence"]
    affect.touch("praise")
    assert affect.decay()["valence"] > before

    affect.reset()
    affect.touch("insult")
    assert affect.decay()["valence"] < 0.15


def test_unknown_event_is_rejected():
    with pytest.raises(affect.AffectError):
        affect.touch("existential_dread")


def test_values_stay_in_range():
    for _ in range(40):
        affect.touch("praise", weight=3.0)
    values = affect.decay()
    assert all(-1.0 <= v <= 1.0 for v in values.values())


def test_mood_decays_back_toward_baseline():
    affect.touch("insult", weight=3.0)
    dropped = affect.decay()["valence"]
    assert dropped < 0

    # pretend the event happened a day ago
    with sqlite3.connect(affect._db()) as connection:
        connection.execute("UPDATE state SET updated_at = ? WHERE id = 1",
                           (time.time() - 24 * 3600,))
    recovered = affect.decay()["valence"]
    assert recovered > dropped
    assert recovered == pytest.approx(affect.BASELINE["valence"], abs=0.05)


def test_labels_are_words_not_gradients():
    labels = {affect.label_for({"valence": 0.8, "arousal": 0.8, "energy": 0.8,
                                "trust": 0.5, "curiosity": 0.5}),
              affect.label_for({"valence": -0.6, "arousal": 0.7, "energy": 0.5,
                                "trust": 0.5, "curiosity": 0.5})}
    assert labels == {"excited", "chidchida"}


def test_state_is_honest_about_what_it_is():
    state = affect.state()
    assert "not a feeling" in state["honesty"]
    assert state["tone_directive"]


def test_disable_switch_pins_baseline(monkeypatch):
    monkeypatch.setenv("UAI_AFFECT_DISABLED", "1")
    moved = affect.touch("praise")
    assert moved["disabled"] is True
    assert moved["valence"] == affect.BASELINE["valence"]


def test_message_reading_picks_up_hinglish():
    fired = affect.read_message("yaar ye phir se nahi ho raha, bakwas")
    assert "frustration" in fired and "insult" in fired


# --- mind ----------------------------------------------------------------------

@pytest.fixture()
def fresh_mind(tmp_path, monkeypatch):
    monkeypatch.setenv("UAI_DATA_ROOT", str(tmp_path))
    mind.init_db()
    return tmp_path


def test_turns_are_recorded_and_summarised(fresh_mind):
    mind.record_turn(session="s", message="health batao", intent="health", ok=True, tools=1)
    mind.record_turn(session="s", message="kaunsa tool", intent="unknown", ok=True)
    mind.record_turn(session="s", message="tool pillow path=x.png", intent="tool:pillow",
                     ok=False, tools=1, error="unavailable: pip install Pillow")

    report = mind.stats(10)
    assert report["turns"] == 3
    assert report["ok_rate"] == pytest.approx(0.667, abs=0.01)
    assert report["top_intents"]["unknown"] == 1
    assert report["errors"][0][0].startswith("unavailable: pip install")


def test_reflection_turns_failures_into_a_proposal(fresh_mind):
    for _ in range(4):
        mind.record_turn(session="s", message="tool pillow path=x.png", intent="tool:pillow",
                         ok=False, tools=1, error="unavailable: pip install Pillow")
    for _ in range(2):
        mind.record_turn(session="s", message="mujhe kuch samajh nahi aaya", intent="unknown")

    result = mind.reflect(20)
    assert result["ran"] is True
    titles = [item["title"] for item in result["proposals"]]
    assert any("Pillow" in title for title in titles)
    assert any("intents" in title for title in titles)
    assert mind.lessons(10), "reflection must leave a lesson behind"


def test_reflection_is_idempotent(fresh_mind):
    mind.record_turn(session="s", message="x", intent="tool:pip", ok=False, tools=1,
                     error="unavailable: pip install Pillow")
    first = mind.reflect(10)
    second = mind.reflect(10)
    assert first["proposals"][0]["id"] == second["proposals"][0]["id"] or \
        second["proposals"][0].get("duplicate") is True
    assert len(mind.proposals("open")) == 1


def test_deciding_a_proposal_never_applies_it(fresh_mind):
    mind.record_turn(session="s", message="x", intent="tool:pip", ok=False, tools=1,
                     error="unavailable: pip install Pillow")
    proposal_id = mind.reflect(10)["proposals"][0]["id"]

    decided = mind.decide(proposal_id, "accepted")
    assert decided["applied_by_me"] is False
    assert "human" in decided["note"]
    assert mind.proposals("accepted")[0]["id"] == proposal_id

    with pytest.raises(ValueError):
        mind.decide(999, "accepted")
    with pytest.raises(ValueError):
        mind.decide(proposal_id, "done-ish")


def test_self_model_reports_measured_capability(fresh_mind):
    model = mind.self_model()
    belt = toolbelt.summary()
    assert model["capabilities"]["tools_total"] == belt["total"]
    assert model["capabilities"]["tools_ready"] == belt["ready"]
    assert model["capabilities"]["agents"] >= 40
    assert isinstance(model["known_gaps"], list)
    assert "not self-awareness" in model["honesty"]


def test_journal_round_trip(fresh_mind):
    mind.journal("pehli baar mood set hua", mood="khush", kind="note")
    entries = mind.entries(5)
    assert entries[0]["entry"].startswith("pehli baar")
    assert entries[0]["mood"] == "khush"


# --- JARVIS integration --------------------------------------------------------

def test_chat_moves_mood_and_records_a_turn(fresh_mind):
    before = mind.stats(5)["turns"]
    reply = jarvis.chat("shukriya yaar, zabardast!", session="inner-test")
    assert reply["mood"] == "khush"
    assert "praise" in reply["affect_triggered"]
    assert mind.stats(50)["turns"] >= before + 1


def test_character_and_mood_reach_the_model_prompt(fresh_mind, monkeypatch):
    from app import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    captured: dict = {}

    def fake_post(payload, timeout=90.0):
        captured.update(payload)
        return {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                "model": "claude-sonnet-4-5", "usage": {}}

    monkeypatch.setattr(anthropic, "_post", fake_post)
    jarvis.chat("hello", session="prompt-test")

    system = captured["system"]
    assert "You are JARVIS" in system
    assert "CURRENT MOOD" in system
    assert "not a feeling" not in system  # the disclaimer is for humans, not the prompt
