"""Claude integration: the client, the router branch, and JARVIS using the tool belt.

No test here touches the network. The one HTTP seam (``anthropic._post``) and the router's
httpx client are stubbed, so what is verified is our logic — request shape, tool loop,
error handling — not Anthropic's uptime.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app import anthropic, ai_router, jarvis, quota, toolbelt

REPO = Path(__file__).resolve().parent.parent
KEY_VARS = ("ANTHROPIC_API_KEY",)


@pytest.fixture(autouse=True)
def clean_key(monkeypatch):
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)


def _text_body(text: str, **extra) -> dict:
    payload = {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
               "model": "claude-sonnet-4-5", "usage": {"input_tokens": 10, "output_tokens": 5}}
    payload.update(extra)
    return payload


def _tool_body(name: str, args: dict, tool_id: str = "tu_1") -> dict:
    return {
        "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": tool_id, "name": name, "input": args},
        ],
        "stop_reason": "tool_use", "model": "claude-sonnet-4-5",
        "usage": {"input_tokens": 50, "output_tokens": 20},
    }


# --- the client ---------------------------------------------------------------

def test_without_a_key_everything_says_unavailable():
    assert anthropic.available() is False
    assert anthropic.status()["configured"] is False

    with pytest.raises(anthropic.AnthropicError) as caught:
        anthropic.messages("system", [{"role": "user", "content": "hi"}])
    assert "unavailable: ANTHROPIC_API_KEY" in str(caught.value)
    assert caught.value.unavailable is True
    assert caught.value.status == 503


def test_model_and_base_can_be_overridden(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_DEFAULT_MODEL", "claude-opus-4-1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.com/")
    assert anthropic.model() == "claude-opus-4-1"
    assert anthropic.base_url() == "https://proxy.example.com"


def test_key_never_leaks_in_status(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret-value")
    status = anthropic.status()
    assert status["configured"] is True
    assert "super-secret" not in json.dumps(status)


def test_messages_parses_text_and_tool_calls(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    seen: dict = {}

    def fake_post(payload, timeout=90.0):
        seen.update(payload)
        return {"content": [{"type": "text", "text": " hello "},
                            {"type": "tool_use", "id": "tu_9", "name": "run_git",
                             "input": {"op": "status"}}],
                "stop_reason": "tool_use", "model": "claude-sonnet-4-5",
                "usage": {"input_tokens": 1, "output_tokens": 2}}

    monkeypatch.setattr(anthropic, "_post", fake_post)
    result = anthropic.messages("sys", [{"role": "user", "content": "hi"}], max_tokens=64)

    assert result["text"] == "hello"
    assert result["tool_calls"] == [{"id": "tu_9", "name": "run_git", "input": {"op": "status"}}]
    assert result["provider"] == "anthropic"
    assert seen["max_tokens"] == 64 and seen["system"] == "sys"
    assert seen["model"] == anthropic.model()


# --- the tool-use loop ---------------------------------------------------------

def test_tool_turn_runs_the_tool_then_answers(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    rounds: list[dict] = []

    def fake_post(payload, timeout=90.0):
        rounds.append(payload)
        if len(rounds) == 1:
            return _tool_body("run_git", {"op": "branch"})
        return _text_body("branch: arena/demo")

    monkeypatch.setattr(anthropic, "_post", fake_post)
    result = anthropic.tool_turn("sys", "which branch?", [{"name": "run_git"}],
                                 toolbelt.run_from_claude, max_rounds=2)

    assert result["text"] == "branch: arena/demo"
    assert result["rounds"] == 2 and result["stopped"] == "answer"
    assert result["tool_runs"][0]["ok"] is True
    fed_back = rounds[1]["messages"][-1]["content"][0]
    assert fed_back["type"] == "tool_result" and fed_back["tool_use_id"] == "tu_1"
    assert json.loads(fed_back["content"])["result"]["op"] == "branch"


def test_tool_turn_reports_a_failing_tool_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    rounds: list[dict] = []

    def fake_post(payload, timeout=90.0):
        rounds.append(payload)
        if len(rounds) == 1:
            return _tool_body("run_pillow", {"path": "x.png"})
        return _text_body("Pillow install nahi hai, pehle pip install Pillow.")

    monkeypatch.setattr(anthropic, "_post", fake_post)
    result = anthropic.tool_turn("sys", "thumbnail banao", [], toolbelt.run_from_claude,
                                 max_rounds=2)

    assert "pip install" in result["text"]
    assert result["tool_runs"][0]["ok"] is False
    assert rounds[1]["messages"][-1]["content"][0]["is_error"] is True


def test_tool_turn_stops_at_max_rounds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(anthropic, "_post",
                        lambda payload, timeout=90.0: _tool_body("run_git", {"op": "status"}))
    result = anthropic.tool_turn("sys", "loop forever", [], toolbelt.run_from_claude,
                                 max_rounds=2)
    assert result["stopped"] == "max_rounds"
    assert len(result["tool_runs"]) == 2


# --- ai_router branch ----------------------------------------------------------

def test_router_resolves_anthropic_with_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    routes = ai_router.resolve_all("anthropic")
    assert len(routes) == 1
    assert routes[0].mode == "anthropic"
    assert routes[0].base == "https://api.anthropic.com"


def test_router_posts_to_messages_endpoint(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AI_PROVIDER_ORDER", "anthropic")
    quota.reset()
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return _text_body("bonjour")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            captured.update({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(ai_router.httpx, "Client", FakeClient)
    answer = ai_router.complete("be nice", "say hi")

    assert answer["text"] == "bonjour"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["messages"] == [{"role": "user", "content": "say hi"}]


def test_router_without_a_key_has_no_anthropic_route():
    assert ai_router.resolve_all("anthropic") == []


# --- JARVIS -------------------------------------------------------------------

def test_jarvis_uses_claude_with_the_tool_belt(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    posts: list[dict] = []

    def fake_post(payload, timeout=90.0):
        posts.append(payload)
        if len(posts) == 1:
            return _tool_body("run_git", {"op": "branch"})
        return _text_body("Aap arena branch par hain.")

    monkeypatch.setattr(anthropic, "_post", fake_post)
    reply = jarvis.chat("kaunsi branch par hain?", session="claude-test")

    assert reply["used_model"] is True
    assert reply["model"]["provider"] == "anthropic"
    assert reply["reply"] == "Aap arena branch par hain."
    assert reply["actions"][0]["ok"] is True
    assert posts[0]["tools"], "Claude must be offered the free tool belt"


def test_jarvis_falls_back_to_rules_when_claude_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    def boom(payload, timeout=90.0):
        raise anthropic.AnthropicError("Claude HTTP 500: overloaded")

    monkeypatch.setattr(anthropic, "_post", boom)
    reply = jarvis.chat("aaj ka mausam kaisa hai", session="claude-fail")

    # The failure is reported, not hidden, and the rule-based answer still lands.
    assert reply["used_model"] is False
    assert "Claude HTTP 500" in reply["model_note"]
    assert reply["reply"].startswith("Ye mujhe samajh nahi aaya")
    assert "free tools" in reply["reply"]


def test_jarvis_tool_command_works_without_any_model():
    reply = jarvis.chat("tool git op=branch", session="tool-cmd")
    assert reply["intent"] == "tool:git"
    assert reply["actions"][0]["ok"] is True
    assert "arena/" in reply["reply"]


def test_jarvis_reports_an_unavailable_tool_plainly():
    from importlib.util import find_spec

    if find_spec("PIL") is not None:
        pytest.skip("Pillow is installed here")
    reply = jarvis.chat("tool pillow path=x.png", session="tool-missing")
    assert reply["actions"][0]["ok"] is False
    assert "unavailable: pip install Pillow" in reply["reply"]


def test_jarvis_status_reports_brain_and_belt(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    state = jarvis.status()
    assert state["model"]["claude"] is True
    assert state["model"]["claude_model"]
    assert state["tools"]["total"] >= 60
    assert state["tools"]["ready"] >= 1


# --- the Kaggle bootstrap ------------------------------------------------------

def _load_kaggle_module():
    path = REPO / "deploy" / "kaggle" / "jarvis_kaggle.py"
    spec = importlib.util.spec_from_file_location("jarvis_kaggle", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_kaggle_bootstrap_parses_the_tunnel_url():
    module = _load_kaggle_module()
    banner = ("2026-11-05T13:00:00Z INF |  https://brave-tiger-violet-123.trycloudflare.com  |")
    assert module.public_url(banner) == "https://brave-tiger-violet-123.trycloudflare.com"
    assert module.public_url("nothing here") is None


def test_kaggle_bootstrap_reads_secrets_from_env(monkeypatch):
    module = _load_kaggle_module()
    monkeypatch.setenv("BACKEND_API_KEY", "from-env")
    assert module.read_secret("BACKEND_API_KEY") == "from-env"
    monkeypatch.delenv("BACKEND_API_KEY", raising=False)
    assert module.read_secret("BACKEND_API_KEY") == ""
