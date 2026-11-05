"""Offline snapshot of vetted GitHub repositories worth wiring into this backend.

`app/github_discovery.py` searches GitHub live (needs network + rate-limit
headroom). This module serves the opposite need: a **frozen, versioned snapshot**
built by `scripts/fetch_github_repos.py`, so the catalog is deterministic, works
with no network, and can be reviewed in a diff.

Honesty rules baked into the data:
  * stars / licence / language come from the GitHub API at build time — never typed by hand;
  * every entry carries ``integration: reference-only`` because the code is NOT vendored;
  * missing licences are surfaced, not hidden.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog" / "github_repos.json"


class RegistryUnavailable(RuntimeError):
    """Raised when the snapshot has not been generated yet."""


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise RegistryUnavailable(
            "catalog/github_repos.json is missing; run: python scripts/fetch_github_repos.py"
        )
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def stats() -> dict[str, Any]:
    data = load()
    repos = data.get("repos", [])
    licensed = sum(1 for repo in repos if repo.get("license"))
    categories: dict[str, int] = {}
    for repo in repos:
        for category in repo.get("categories", []):
            categories[category] = categories.get(category, 0) + 1
    return {
        "total": len(repos),
        "fetched_at": data.get("fetched_at"),
        "source": data.get("source"),
        "categories": dict(sorted(categories.items())),
        "category_count": len(categories),
        "with_license": licensed,
        "without_license": len(repos) - licensed,
        "total_stars": sum(int(repo.get("stars") or 0) for repo in repos),
        "disclaimer": data.get("disclaimer"),
    }


def search(
    category: str | None = None,
    query: str | None = None,
    min_stars: int = 0,
    license_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Filter the snapshot. Pure function over the JSON — no network calls."""

    repos = list(load().get("repos", []))
    if category:
        wanted = category.strip().lower()
        repos = [repo for repo in repos if wanted in {c.lower() for c in repo.get("categories", [])}]
    if query:
        needle = query.strip().lower()
        if needle:
            repos = [
                repo
                for repo in repos
                if needle in repo.get("full_name", "").lower()
                or needle in repo.get("description", "").lower()
                or any(needle in str(topic).lower() for topic in repo.get("topics", []))
            ]
    if min_stars:
        repos = [repo for repo in repos if int(repo.get("stars") or 0) >= min_stars]
    if license_id:
        wanted_license = license_id.strip().lower()
        repos = [repo for repo in repos if str(repo.get("license") or "").lower() == wanted_license]

    repos.sort(key=lambda repo: (-int(repo.get("stars") or 0), repo.get("full_name", "")))
    total = len(repos)
    window = repos[offset: offset + limit] if limit else repos[offset:]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(window),
        "filters": {
            "category": category,
            "query": query,
            "min_stars": min_stars,
            "license": license_id,
        },
        "repos": window,
    }


def get(full_name: str) -> dict[str, Any] | None:
    target = full_name.strip().lower()
    for repo in load().get("repos", []):
        if repo.get("full_name", "").lower() == target:
            return repo
    return None
