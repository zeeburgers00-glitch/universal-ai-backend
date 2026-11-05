"""The PC launchers are deliverables too: if they lie, the user finds out at home."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _load(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- the Windows launcher ------------------------------------------------------

def test_windows_launcher_files_exist():
    bat = SCRIPTS / "start_windows.bat"
    ps1 = SCRIPTS / "start_windows.ps1"
    assert bat.is_file() and ps1.is_file()
    bat_text = bat.read_text(encoding="utf-8", errors="replace")
    ps1_text = ps1.read_text(encoding="utf-8")

    # the double-click wrapper must actually reach the real script
    assert "start_windows.ps1" in bat_text
    assert "ExecutionPolicy Bypass" in bat_text

    # and the script must do the four things it promises
    assert "venv" in ps1_text
    assert "requirements.txt" in ps1_text
    assert "uvicorn app.main:app" in ps1_text
    assert "/editor" in ps1_text
    assert "BACKEND_API_KEY" in ps1_text


def test_windows_launcher_binds_locally_by_default():
    ps1_text = (SCRIPTS / "start_windows.ps1").read_text(encoding="utf-8")
    assert '"127.0.0.1"' in ps1_text
    assert '"0.0.0.0"' in ps1_text  # only under -Lan
    assert "if ($Lan)" in ps1_text


def test_windows_launcher_never_hardcodes_a_key():
    ps1_text = (SCRIPTS / "start_windows.ps1").read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in ps1_text
    assert ".backend_api_key" in ps1_text


# --- desktop window ------------------------------------------------------------

def test_build_url_handles_missing_and_extra_slashes():
    module = _load("desktop_app.py")
    assert module.build_url(port=8000) == "http://127.0.0.1:8000/editor"
    assert module.build_url(port=8100, path="editor") == "http://127.0.0.1:8100/editor"
    assert module.build_url(host="0.0.0.0", port=9000, path="/app") == "http://0.0.0.0:9000/app"


def test_app_window_command_uses_chrome_app_mode(monkeypatch):
    module = _load("desktop_app.py")

    # pretend a chrome binary exists, whatever the sandbox has
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/google-chrome"
                        if name == "google-chrome" else None)
    command = module.app_window_command("http://127.0.0.1:8000/editor", platform="linux")
    assert command is not None
    assert command[0] == "/usr/bin/google-chrome"
    assert "--app=http://127.0.0.1:8000/editor" in command
    assert any(part.startswith("--window-size=") for part in command)


def test_missing_browser_falls_back_instead_of_pretending(monkeypatch):
    module = _load("desktop_app.py")
    # `shutil` and `webbrowser` are process-wide modules: patch through monkeypatch so the
    # rest of the suite still finds git, ripgrep and friends afterwards.
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    assert module.app_window_command("http://127.0.0.1:8000/editor", platform="linux") is None

    opened: list[str] = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url) or True)
    how = module.open_window("http://127.0.0.1:8000/editor", platform="linux")
    assert how == "browser"
    assert opened == ["http://127.0.0.1:8000/editor"]


def test_windows_candidates_include_edge_and_chrome():
    module = _load("desktop_app.py")
    flattened = " ".join(part for command in module.browser_candidates("win32") for part in command)
    assert "chrome.exe" in flattened and "msedge.exe" in flattened


def test_healthy_is_false_when_nothing_listens():
    module = _load("desktop_app.py")
    assert module.healthy("http://127.0.0.1:9", timeout=0.3) is False


def test_print_command_mode_does_not_open_anything(monkeypatch, capsys):
    module = _load("desktop_app.py")
    monkeypatch.setattr(module, "app_window_command", lambda url, platform=None: None)
    assert module.main(["--print-command"]) == 0
    assert "would open http://127.0.0.1:8000/editor" in capsys.readouterr().out


def test_missing_server_gives_an_actionable_error(monkeypatch, capsys):
    module = _load("desktop_app.py")
    monkeypatch.setattr(module, "healthy", lambda url, timeout=2.0: False)
    code = module.main(["--port", "9"])
    assert code == 1
    assert "start_windows.bat" in capsys.readouterr().err


# --- docs touch the same reality ----------------------------------------------

def test_pc_doc_covers_the_three_platforms():
    text = (REPO / "docs" / "RUN_ON_YOUR_PC.md").read_text(encoding="utf-8")
    for needle in ("Windows", "macOS", "Linux", "start_windows.bat",
                   "desktop_app.py", "editor", ".backend_api_key"):
        assert needle in text, needle
    assert "ffmpeg" in text.lower()
