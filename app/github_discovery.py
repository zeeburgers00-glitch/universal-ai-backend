import os
from typing import Any

import httpx


async def search_github_repositories(q: str, per_page: int = 10) -> dict[str, Any]:
    """Search public GitHub repositories live; results are metadata, not verified plugins."""
    query = q.strip()
    if len(query) < 2:
        raise ValueError("q must contain at least 2 characters")
    if len(query) > 180:
        raise ValueError("q is too long")

    count = max(1, min(per_page, 30))
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Universal-AI-Backend",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {"q": f"{query} in:name,description,topics", "sort": "stars", "order": "desc", "per_page": count}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False) as client:
        response = await client.get("https://api.github.com/search/repositories", params=params, headers=headers)
        if response.status_code == 403:
            raise RuntimeError("GitHub API rate limit or permission limit reached; configure GITHUB_TOKEN")
        response.raise_for_status()
        payload = response.json()

    items = []
    for repo in payload.get("items", []):
        license_data = repo.get("license") or {}
        items.append({
            "id": str(repo.get("full_name", "")).lower().replace("/", "--"),
            "name": repo.get("name"),
            "full_name": repo.get("full_name"),
            "description": repo.get("description"),
            "repository_url": repo.get("html_url"),
            "default_branch": repo.get("default_branch"),
            "language": repo.get("language"),
            "stars": repo.get("stargazers_count", 0),
            "topics": repo.get("topics", []),
            "license": license_data.get("spdx_id") or "UNKNOWN — check upstream LICENSE",
            "updated_at": repo.get("updated_at"),
            "status": "discovered_unreviewed",
            "warning": "Discovery result only. Review license, code, dependencies, maintainer activity, and safety before integration.",
        })
    return {
        "query": query,
        "total_count": payload.get("total_count", 0),
        "returned": len(items),
        "items": items,
        "source": "GitHub Search API",
    }
