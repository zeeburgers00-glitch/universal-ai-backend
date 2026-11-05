"""The repo catalog must never be silently replaced by a partial fetch."""

from __future__ import annotations

import json
from pathlib import Path

from app import github_registry

REPO = Path(__file__).resolve().parent.parent


def test_catalog_in_the_repository_is_complete():
    github_registry.load.cache_clear()
    catalog = github_registry.load()
    assert len(catalog["repos"]) >= 100, "a 2-repo snapshot once overwrote the 205-repo catalog"
    for repo in catalog["repos"][:25]:
        assert repo["full_name"] and "url" in repo


def test_fetch_script_refuses_to_shrink_the_catalog():
    script = (REPO / "scripts" / "fetch_github_repos.py").read_text(encoding="utf-8")
    assert "MINIMUM_REPOS" in script
    assert "refusing to write" in script, "a partial fetch must exit instead of writing"


def test_minimum_is_at_least_a_hundred():
    import importlib.util

    spec = importlib.util.spec_from_file_location("fetch_repos", REPO / "scripts" / "fetch_github_repos.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.MINIMUM_REPOS >= 100
