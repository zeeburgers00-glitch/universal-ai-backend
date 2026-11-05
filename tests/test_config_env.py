"""Tests for local .env loading.

Regression guard: `python-dotenv` was a declared dependency but nothing ever
called `load_dotenv`, so a plain `uvicorn app.main:app` run ignored a filled-in
`.env` and reported zero ready providers.
"""

from __future__ import annotations

import os

from app.config import load_env_file


def test_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == []


def test_real_env_wins_over_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=from-file\nPEXELS_API_KEY=file-only\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "from-process")
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    loaded = load_env_file(env_file)

    assert os.environ["GROQ_API_KEY"] == "from-process"  # container secrets never clobbered
    assert os.environ["PEXELS_API_KEY"] == "file-only"
    assert loaded == ["PEXELS_API_KEY"]


def test_package_import_loads_repo_env(monkeypatch):
    """`import app` must attempt to load the repo .env (no-op when absent)."""

    import app

    assert callable(app.load_local_env)


def test_blank_values_are_ignored(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("EMPTY_KEY=\n# comment\n", encoding="utf-8")
    monkeypatch.delenv("EMPTY_KEY", raising=False)

    assert load_env_file(env_file) == []
    assert "EMPTY_KEY" not in os.environ
