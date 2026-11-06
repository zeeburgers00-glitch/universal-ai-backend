"""Pexels stock-footage search adapter.

Returns metadata and download links from the official Pexels API. The caller must
retain attribution and verify asset suitability before using it in a rendered video.
"""
import os
from typing import Any
from pathlib import Path

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
            "https://api.pexels.com/videos/search",
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



def download_pexels_videos(
    query: str,
    output_dir: Path,
    orientation: str = "landscape",
    max_downloads: int = 8,
) -> list[dict[str, Any]]:
    """Download a small, bounded set of MP4 clips and retain creator attribution.

    Pexels is optional: callers should catch provider/network errors and keep the
    render usable with its local fallback assets.
    """
    api_key = get_secret("PEXELS_API_KEY") or os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY is not configured")
    if orientation not in {"landscape", "portrait", "square"}:
        raise ValueError("Unsupported orientation")

    output_dir.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(60.0, connect=10.0)
    downloaded: list[dict[str, Any]] = []
    max_bytes = 50 * 1024 * 1024
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(
            "https://api.pexels.com/videos/search",
            params={"query": query.strip()[:160], "orientation": orientation, "size": "medium",
                    "per_page": min(max(max_downloads * 2, 8), 20)},
            headers={"Authorization": api_key},
        )
        response.raise_for_status()
        videos = response.json().get("videos", [])

        for video in videos:
            if len(downloaded) >= min(max(max_downloads, 1), 8):
                break
            files = [
                item for item in (video.get("video_files") or [])
                if item.get("link") and str(item.get("file_type") or "").lower() == "video/mp4"
            ]
            files.sort(
                key=lambda item: (
                    1 if item.get("quality") == "hd" else 0,
                    min(int(item.get("width") or 0), 1920),
                    int(item.get("height") or 0),
                ),
                reverse=True,
            )
            if not files:
                continue

            video_id = str(video.get("id") or len(downloaded))
            target = output_dir / f"pexels_{video_id}.mp4"
            if target.exists() and target.stat().st_size > 1024:
                creator = video.get("user") or {}
                downloaded.append({
                    "path": str(target), "pexels_video_id": video.get("id"),
                    "source_url": video.get("url"), "creator_name": creator.get("name"),
                    "creator_url": creator.get("url"), "attribution": "Video by " + str(creator.get("name") or "Pexels creator") + " via Pexels",
                })
                continue

            partial = target.with_suffix(".mp4.part")
            try:
                with client.stream("GET", files[0]["link"]) as media:
                    media.raise_for_status()
                    content_length = int(media.headers.get("content-length") or 0)
                    if content_length > max_bytes:
                        continue
                    total = 0
                    with partial.open("wb") as handle:
                        for chunk in media.iter_bytes(1024 * 256):
                            total += len(chunk)
                            if total > max_bytes:
                                break
                            handle.write(chunk)
                if total <= 1024 or total > max_bytes:
                    partial.unlink(missing_ok=True)
                    continue
                partial.replace(target)
            except Exception:
                partial.unlink(missing_ok=True)
                continue

            creator = video.get("user") or {}
            downloaded.append({
                "path": str(target), "pexels_video_id": video.get("id"),
                "source_url": video.get("url"), "creator_name": creator.get("name"),
                "creator_url": creator.get("url"),
                "attribution": "Video by " + str(creator.get("name") or "Pexels creator") + " via Pexels",
            })

    return downloaded
