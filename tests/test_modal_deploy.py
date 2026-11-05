"""Configuration tests for the Modal GPU deployment kit.

These never contact Modal. They check the things that silently cost money or
break a deploy: an unconstrained GPU class, a missing secret, no weight cache.
"""

from __future__ import annotations

import importlib.util
import py_compile
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODAL_DIR = ROOT / "deploy" / "modal"
APP_FILE = MODAL_DIR / "modal_app.py"
README = MODAL_DIR / "README.md"


def _source() -> str:
    return APP_FILE.read_text(encoding="utf-8")


def test_kit_exists_and_compiles():
    assert APP_FILE.is_file()
    assert README.is_file()
    py_compile.compile(str(APP_FILE), doraise=True)


def test_gpu_class_is_explicit_never_any():
    """gpu='any' can silently pick an H100 at ~$3.95/hr instead of a T4."""
    import ast

    source = _source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "gpu" and isinstance(keyword.value, ast.Constant):
                assert keyword.value.value != "any", (
                    "never deploy with gpu='any'; pin a class such as T4"
                )
    assert 'VOICE_GPU = "T4"' in source


def test_worker_runs_redis_and_celery_in_process():
    # /v1/voice/tts queues a Celery task, so the broker must live beside the API.
    source = _source()
    assert "redis-server" in source
    assert "celery" in source
    assert "voice_worker.app:app" in source or "voice_worker.app import app" in source
    assert "/srv/voice_worker" in source


def test_secrets_volume_and_cache_are_wired():
    source = _source()
    assert 'Secret.from_name("voice-worker-secret")' in source
    assert 'Volume.from_name("universal-ai-voice-data", create_if_missing=True)' in source
    assert "HF_HOME" in source, "model weights must be cached on the volume"
    assert "VOICE_WORKER_API_KEY" in source


def test_no_leftover_placeholder_identifiers():
    # Guards against the half-edited expression this file once contained.
    source = _source()
    assert "sd_image_cache" not in source


def test_readme_covers_the_operational_essentials():
    text = README.read_text(encoding="utf-8").lower()
    assert "modal secret create" in text
    assert "https" in text
    assert "scale" in text and "zero" in text
    assert "30" in text  # the free credit
    assert "celery" in text and "scaledown" in text or "scales down" in text
    assert "voice_worker_url" in text


def test_app_registers_its_functions(monkeypatch):
    pytest.importorskip("modal", reason="modal SDK is only needed to deploy")
    sys.path.insert(0, str(MODAL_DIR))
    try:
        spec = importlib.util.spec_from_file_location("modal_app_under_test", APP_FILE)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(MODAL_DIR))

    assert module.app.name == "universal-ai-voice-worker"
    import warnings

    # The public accessor is deprecated in Modal 1.6 but still the only reliable
    # way to introspect an app offline; silence the warning rather than the check.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        registered = set(module.app.registered_functions)
    assert {"voice_api", "prewarm", "thumbnail"} <= registered
