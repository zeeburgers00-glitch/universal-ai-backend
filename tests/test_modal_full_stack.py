"""The full-stack Modal kit must stay deployable.

Modal is not installed in CI and the sandbox cannot reach modal.com, so these
tests check the deployable artefact statically: the file parses, registers one
function per HTTP service, asks for no GPU on CPU-only services, keeps cost
guards (no always-warm containers), and only calls functions that really exist.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL_STACK = ROOT / "deploy" / "modal" / "full_stack.py"
SMOKE = ROOT / "deploy" / "modal" / "smoke.py"

EXPECTED_FUNCTIONS = {
    "api", "voice", "media", "youtube",
    "channel", "agent", "automation", "rea", "render_command",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _decorated_names(tree: ast.Module) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = []
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute):
                decorators.append(target.attr)
            elif isinstance(target, ast.Name):
                decorators.append(target.id)
        found[node.name] = decorators
    return found


def test_full_stack_parses_and_registers_every_service():
    tree = _tree(FULL_STACK)
    names = _decorated_names(tree)
    assert EXPECTED_FUNCTIONS <= set(names)
    for name in EXPECTED_FUNCTIONS - {"render_command"}:
        assert "asgi_app" in names[name] or name == "api", name


def test_gpu_is_pinned_to_a_cheap_card():
    source = FULL_STACK.read_text(encoding="utf-8")
    assert 'gpu="T4"' in source
    assert 'gpu="any"' not in source, "gpu='any' can land on a ~$4/hr H100"


def test_no_always_warm_containers():
    """min_containers>=1 would bill 24/7 and burn the $30 free credits."""

    source = FULL_STACK.read_text(encoding="utf-8")
    assert "min_containers" not in source
    assert "scaledown_window" in source


def test_every_registered_service_module_imports_here():
    """The modules named in the kit must expose `app` in this checkout."""

    import importlib
    import os
    import tempfile

    sys.path.insert(0, str(ROOT / "workers"))

    # Worker packages create their data dirs at import time and default to /data.
    data_root = tempfile.mkdtemp(prefix="uai-modal-test-")
    for name in (
        "VOICE_DATA_ROOT", "MEDIA_DATA_ROOT", "YOUTUBE_MEDIA_ASSET_ROOT",
        "REA_ALLOWED_WORKSPACE_ROOT", "WINDOWS_AGENT_WORKSPACE", "UAI_DATA_ROOT",
    ):
        os.environ.setdefault(name, data_root)

    services = None
    for node in _tree(FULL_STACK).body:
        target = getattr(node, "target", None)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and getattr(target, "id", None) == "SERVICES":
            services = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SERVICES" for t in node.targets
        ):
            services = ast.literal_eval(node.value)

    assert services, "SERVICES table not found"
    assert len(services) == 8
    for name, spec in services.items():
        app = getattr(importlib.import_module(spec["module"]), spec["attr"])
        assert app is not None, name


def test_render_function_only_calls_real_videoengine_helpers():
    """Guards against the earlier wrong render_timeline/build_timeline signatures."""

    source = FULL_STACK.read_text(encoding="utf-8")
    assert "render_timeline(" not in source.split("# One-shot video job")[-1], (
        "the one-shot job should drive /v1/command, not call render_timeline directly"
    )
    assert "/v1/command" in source


def test_smoke_script_derives_sibling_urls():
    sys.path.insert(0, str(FULL_STACK.parent))
    import smoke

    assert smoke.derive("https://ws--uai-api.modal.run", "voice") == "https://ws--uai-voice.modal.run"
    assert (
        smoke.derive("https://ws--uai-api-abc123.modal.run", "media")
        == "https://ws--uai-media-abc123.modal.run"
    )
    assert smoke.derive("https://custom.example.com", "rea") == "https://custom.example.com/rea"


def test_deploy_doc_exists_and_is_honest():
    doc = FULL_STACK.parent / "DEPLOY_FULL.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "modal deploy" in text
    assert "not verified" in text.lower(), "the doc must not imply a live deploy was run"
