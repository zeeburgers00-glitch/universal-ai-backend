"""Pexels stock-footage search adapter.

Returns metadata and download links from the official Pexels API. The caller must
retain attribution and verify asset suitability before using it in a rendered video.
"""
import os
from typing import Any

import httpx

from .vault import get_secret


async def search_pexels_videos(
    query: str,
    orientation: str = "landscape",
    size: str = "medium",
    per_page: int = 12,
    page: int = 1,
) -> dict[str, Any]:
    api_key = get_secret("PEXELS_API_KEY") or os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY is not configured")
    if orientation not in {"landscape", "portrait", "square"}:
        raise ValueError("Unsupported orientation")
    if size not in {"large", "medium", "small"}:
        raise ValueError("Unsupported size")
    params = {
        "query": query.strip(),
        "orientation": orientation,
        "size": size,
        "per_page": min(max(per_page, 1), 30),
        "page": min(max(page, 1), 50),
    }
    timeout = httpx.Timeout(25.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(
            "https://api.pexels.com/v1/videos/search",
            params=params,
            headers={"Authorization": api_key},
        )
        response.raise_for_status()
        payload = response.json()
    items = []
    for video in payload.get("videos", []):
        files = [f for f in video.get("video_files", []) if f.get("link")]
        files.sort(key=lambda f: (f.get("width", 0) or 0, f.get("height", 0) or 0), reverse=True)
        best = files[0] if files else {}
        creator = video.get("user") or {}
        items.append({
            "id": video.get("id"),
            "duration_seconds": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
            "url": video.get("url"),
            "creator_name": creator.get("name"),
            "creator_url": creator.get("url"),
            "download_url": best.get("link"),
            "mime_type": best.get("file_type"),
            "quality": best.get("quality"),
            "license_source": "Pexels",
            "attribution_required_by_app": True,
        })
    return {
        "provider": "pexels",
        "attribution": "Videos provided by Pexels",
        "attribution_url": "https://www.pexels.com/",
        "page": payload.get("page", page),
        "per_page": payload.get("per_page", per_page),
        "total_results": payload.get("total_results", len(items)),
        "items": items,
        "note": "Record Pexels and creator attribution with each selected asset; verify current Pexels terms before commercial use.",
    }
