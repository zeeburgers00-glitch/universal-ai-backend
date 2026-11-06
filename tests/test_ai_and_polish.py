"""Provider routing, look-and-feel, SEO packaging and avatar consent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import ai_router, command_center
from app.main import app
from fastapi.testclient import TestClient
from videoengine import build_timeline
from videoengine.assembly import FfmpegNotFound, find_ffmpeg
from videoengine.avatar import AvatarSpec, evaluate
from videoengine.effects import CAPTION_STYLES, GRADE_PRESETS, caption_style, grade_filter, overlay_logo
from videoengine.seo import fallback_pack, seo_pack

client = TestClient(app)
KEY = "ai-test-secret"
HEADERS = {"X-API-Key": KEY}

ALL_KEY_ENVS = [
    "GROQ_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY", "ZAI_API_KEY", "OPENROUTER_API_KEY",
    "HUGGINGFACE_API_KEY", "HUGGINGFACE_DEFAULT_MODEL", "OPENCODE_ZEN_API_KEY", "HACKER_AI_API_KEY", "HACKER_AI_DEFAULT_MODEL", "AI_API_KEY",
    "OPENCODE_ZEN_BASE_URL", "AI_BASE_URL",
]


@pytest.fixture()
def clean_keys(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", KEY)
    for name in ALL_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ------------------------------------------------------------------ ai router
def test_router_reports_every_provider_and_masks_keys(clean_keys):
    clean_keys.setenv("GROQ_API_KEY", "gsk_abcdefghijklmnop")
    clean_keys.setenv("GROQ_DEFAULT_MODEL", "llama-3.3-70b-versatile")
    data = client.get("/v1/ai/providers", headers=HEADERS).json()
    ids = [item["provider"] for item in data["providers"]]
    assert {"groq", "gemini", "mistral", "zai", "openrouter", "huggingface"} <= set(ids)
    groq = next(item for item in data["providers"] if item["provider"] == "groq")
    assert groq["usable"] is True
    assert "abcdefghijklmnop" not in json.dumps(data), "the full key must never be returned"
    assert groq["key_preview"].startswith("gsk_ab")


def test_router_explains_why_a_provider_is_unusable(clean_keys):
    clean_keys.setenv("OPENCODE_ZEN_API_KEY", "sk-zen-1234567890")
    data = ai_router.health()
    entry = next(item for item in data["providers"] if item["provider"] == "opencode_zen")
    assert entry["usable"] is False
    assert "OPENCODE_ZEN_DEFAULT_MODEL" in entry["problem"]


def test_router_uses_documented_huggingface_and_hackerai_environment_names(clean_keys):
    clean_keys.setenv("HUGGINGFACE_API_KEY", "hf_test_token_123456")
    clean_keys.setenv("HUGGINGFACE_DEFAULT_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
    clean_keys.setenv("HACKER_AI_API_KEY", "hacker_test_token_123456")
    clean_keys.setenv("HACKER_AI_DEFAULT_MODEL", "hacker-model")
    hf = ai_router.resolve("huggingface")
    hacker = ai_router.resolve("hackerai")
    assert hf is not None and hf.key_env == "HUGGINGFACE_API_KEY"
    assert hf.base == "https://router.huggingface.co/v1"
    assert hacker is not None and hacker.key_env == "HACKER_AI_API_KEY"
    assert hacker.base == "https://api.hackerai.sh/v1"


def test_router_honours_the_configured_order(clean_keys):
    clean_keys.setenv("GROQ_API_KEY", "gsk_test_12345678")
    clean_keys.setenv("MISTRAL_API_KEY", "mistral_test_1234")
    clean_keys.setenv("AI_PROVIDER_ORDER", "mistral,groq")
    chain = ai_router.chain()
    assert [route.id for route in chain] == ["mistral", "groq"]
    assert ai_router.health()["active_default"] == "mistral"


def test_router_falls_back_to_the_next_provider(clean_keys, monkeypatch):
    clean_keys.setenv("GROQ_API_KEY", "gsk_fails_12345")
    clean_keys.setenv("GEMINI_API_KEY", "gemini_works_1234")
    seen: list[str] = []

    class FakeResponse:
        def __init__(self, status: int, payload: dict | None = None):
            self.status_code = status
            self._payload = payload or {}

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            seen.append(url)
            if "groq" in url:
                return FakeResponse(429)
            return FakeResponse(200, {"choices": [{"message": {"content": "from gemini"}}]})

    monkeypatch.setattr(ai_router.httpx, "Client", FakeClient)
    result = ai_router.complete("sys", "user")
    assert result["text"] == "from gemini"
    assert result["provider"] == "gemini"
    assert any(attempt["provider"] == "groq" for attempt in result["attempts"])
    assert len(seen) == 2


def test_router_fails_loudly_when_nothing_is_configured(clean_keys):
    with pytest.raises(RuntimeError, match="No model provider is configured"):
        ai_router.complete("a", "b")


# --------------------------------------------------------------------- effects
def test_grade_and_caption_presets_are_stable():
    for name in ("cinematic", "warm", "noir", "teal_orange", "film"):
        assert grade_filter(name), f"{name} must produce a filter"
    assert grade_filter("nonsense") == ""
    assert caption_style("nonsense") == CAPTION_STYLES["clean"]
    assert "FontSize" in caption_style("yellow")
    assert "cinematic" in GRADE_PRESETS


def test_logo_overlay_writes_a_video(tmp_path):
    try:
        ffmpeg = find_ffmpeg()
    except FfmpegNotFound:
        pytest.skip("ffmpeg not available")
    import subprocess

    src = tmp_path / "src.mp4"
    logo = tmp_path / "logo.png"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x180:d=1",
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                   capture_output=True, check=True)
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=white:s=100x100:d=1",
                    "-frames:v", "1", str(logo)], capture_output=True, check=True)
    out = overlay_logo(src, logo, tmp_path / "out.mp4", ffmpeg=ffmpeg, position="br")
    assert out.is_file() and out.stat().st_size > 1000


# ------------------------------------------------------------------------- SEO
def _plan_and_timeline():
    plan = {"topic": "tea farming in punjab", "language": "en",
            "beats": ["Intro line.", "Second beat.", "Third beat."]}
    timeline = build_timeline(title="Tea farming", duration_seconds=120, scene_seconds=10,
                              beats=plan["beats"], visual_prompts=["a"] * 12)
    return plan, timeline


def test_seo_fallback_produces_publishable_metadata():
    plan, timeline = _plan_and_timeline()
    pack = fallback_pack(plan, timeline)
    assert len(pack["titles"]) == 5
    assert len(pack["hashtags"]) == 15
    assert pack["chapters"][0]["timestamp"] == "0:00"
    assert "tea farming" in pack["description"].lower() or "Tea farming" in pack["description"]
    assert pack["source"] == "template"


def test_seo_uses_the_model_when_available_and_survives_a_bad_answer():
    plan, timeline = _plan_and_timeline()

    def good(system, user):
        return json.dumps({"titles": ["A", "B"], "hashtags": ["x"], "description": "d",
                           "hook": "h", "keywords": ["k"], "thumbnail_text": ["t"]})

    pack = seo_pack(plan, timeline, good)
    assert pack["source"] == "model" and pack["titles"] == ["A", "B"]
    assert pack["chapters"], "chapters must still come from the timeline"

    def bad(system, user):
        raise RuntimeError("provider down")

    fallback = seo_pack(plan, timeline, bad)
    assert fallback["source"].startswith("template")
    assert fallback["titles"], "a failed model call must never lose the metadata"


# ---------------------------------------------------------------------- avatar
def test_avatar_refuses_a_public_figure():
    status = evaluate(AvatarSpec(name="A Famous Actor", relation="self",
                                 consent_confirmed=True, consent_record_id="c" * 10,
                                 public_figure=True, image_path="x.png",
                                 voice_sample_path="y.wav"))
    assert status["status"] == "blocked"
    assert any("public figure" in reason.lower() for reason in status["blocked"])


def test_avatar_requires_consent_for_a_real_person():
    status = evaluate(AvatarSpec(name="Someone", relation="self"))
    assert status["status"] == "blocked"
    assert any("consent" in reason.lower() for reason in status["blocked"])


def test_consented_avatar_asks_for_the_media_it_needs():
    status = evaluate(AvatarSpec(name="Me", relation="self", consent_confirmed=True,
                                 consent_record_id="consent-123"))
    assert status["status"] == "needs_assets"
    joined = " ".join(status["needs"])
    assert "image_path" in joined and "voice_sample_path" in joined


def test_synthetic_persona_needs_no_consent():
    status = evaluate(AvatarSpec(name="Nova", relation="synthetic"))
    assert status["status"] == "ready"
    assert status["steps"], "the synthetic path must describe how to build it"


# ----------------------------------------------------------------- command API
@pytest.fixture()
def isolated(clean_keys, tmp_path):
    jobs = tmp_path / "jobs"
    output = tmp_path / "output"
    jobs.mkdir()
    output.mkdir()
    clean_keys.setattr(command_center, "DATA_DIR", tmp_path)
    clean_keys.setattr(command_center, "JOB_DIR", jobs)
    clean_keys.setattr(command_center, "OUTPUT_DIR", output)
    command_center._JOBS.clear()
    return tmp_path


def test_command_includes_seo_and_effect_summary(isolated):
    response = client.post("/v1/command", headers=HEADERS, json={
        "command": "make a 20 second video about solar panels",
        "render": False, "grade": "noir", "caption_style": "yellow",
    })
    assert response.status_code == 202
    job = response.json()
    assert job["seo"]["titles"], "SEO must be generated by default"
    assert job["effects"]["grade"] == "noir"
    assert job["effects"]["caption_style"] == "yellow"
    assert job["avatar"]["status"] == "not_requested"


def test_command_rejects_a_logo_outside_the_data_dir(isolated):
    response = client.post("/v1/command", headers=HEADERS, json={
        "command": "make a 10 second video", "render": False, "logo_path": "/etc/passwd",
    })
    assert response.status_code == 400


def test_command_surfaces_a_blocked_avatar_without_failing_the_job(isolated):
    response = client.post("/v1/command", headers=HEADERS, json={
        "command": "make a 10 second video about mountains", "render": False,
        "avatar": {"name": "A Famous Actor", "relation": "self", "public_figure": True},
    })
    assert response.status_code == 202
    avatar = response.json()["avatar"]
    assert avatar["status"] == "blocked"
    assert avatar["blocked"], "the refusal reason must be returned to the caller"


def test_unknown_grade_falls_back_instead_of_failing(isolated):
    response = client.post("/v1/command", headers=HEADERS, json={
        "command": "make a 10 second video about clouds", "render": False, "grade": "not-a-grade",
    })
    assert response.status_code == 202
    assert response.json()["effects"]["grade"] == "none"
