import os
import re
from typing import Any

import httpx


LICENSE_FILTER_RE = re.compile(r"^[A-Za-z0-9.+-]{1,40}$")
SORT_OPTIONS = {"stars", "forks", "updated", "help-wanted-issues"}


async def search_github_repositories(
    q: str,
    per_page: int = 10,
    license_filter: str | None = None,
    min_stars: int = 0,
    sort: str = "stars",
    order: str = "desc",
    page: int = 1,
) -> dict[str, Any]:
    """Search public GitHub repositories live; results are candidates, not verified plugins."""
    query = q.strip()
    if len(query) < 2:
        raise ValueError("q must contain at least 2 characters")
    if len(query) > 180:
        raise ValueError("q is too long")
    if license_filter and not LICENSE_FILTER_RE.fullmatch(license_filter):
        raise ValueError("license_filter may contain only letters, numbers, dot, plus, and hyphen")
    if sort not in SORT_OPTIONS:
        raise ValueError(f"sort must be one of: {', '.join(sorted(SORT_OPTIONS))}")
    if order not in {"asc", "desc"}:
        raise ValueError("order must be asc or desc")
    if min_stars < 0:
        raise ValueError("min_stars cannot be negative")
    if page < 1 or page > 10:
        raise ValueError("page must be between 1 and 10")

    count = max(1, min(per_page, 30))
    github_query = f"{query} in:name,description,topics"
    if license_filter:
        github_query += f" license:{license_filter.lower()}"
    if min_stars:
        github_query += f" stars:>={min_stars}"

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Universal-AI-Backend",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {"q": github_query, "sort": sort, "order": order, "per_page": count, "page": page}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False) as client:
        response = await client.get("https://api.github.com/search/repositories", params=params, headers=headers)
        if response.status_code == 403:
            raise RuntimeError("GitHub API rate limit or permission limit reached; configure GITHUB_TOKEN")
        response.raise_for_status()
        payload = response.json()

    items = []
    for repo in payload.get("items", []):
        license_data = repo.get("license") or {}
        license_name = license_data.get("spdx_id") or "UNKNOWN — check upstream LICENSE"
        items.append({
            "id": str(repo.get("full_name", "")).lower().replace("/", "--"),
            "name": repo.get("name"),
            "full_name": repo.get("full_name"),
            "description": repo.get("description"),
            "repository_url": repo.get("html_url"),
            "default_branch": repo.get("default_branch"),
            "language": repo.get("language"),
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "topics": repo.get("topics", []),
            "license": license_name,
            "license_status": "github_metadata_only_requires_manual_review",
            "archived": repo.get("archived", False),
            "updated_at": repo.get("updated_at"),
            "status": "discovered_unreviewed",
            "warning": "GitHub discovery only. A reported SPDX license is not a legal review; inspect current LICENSE, dependencies, model/data terms, security, and hosted-service boundaries before integration.",
        })
    return {
        "query": query,
        "github_query": github_query,
        "total_count": payload.get("total_count", 0),
        "returned": len(items),
        "page": page,
        "per_page": count,
        "items": items,
        "source": "GitHub Search API",
        "warning": "Discovery results are metadata only. The backend does not download, install, or execute these repositories.",
    }
