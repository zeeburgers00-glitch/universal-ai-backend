"""Metricool API adapter for connected-brand discovery and YouTube planning analytics."""
from __future__ import annotations

import os
from typing import Any

import httpx

from .vault import get_secret

BASE_URL = "https://app.metricool.com/api"


def _config() -> tuple[str, str, str]:
    token = get_secret("METRICOOL_API_TOKEN") or os.getenv("METRICOOL_API_TOKEN", "").strip()
    user_id = get_secret("METRICOOL_USER_ID") or os.getenv("METRICOOL_USER_ID", "").strip()
    blog_id = get_secret("METRICOOL_BLOG_ID") or os.getenv("METRICOOL_BLOG_ID", "").strip()
    if not token or not user_id or not blog_id:
        raise RuntimeError("Configure METRICOOL_API_TOKEN, METRICOOL_USER_ID and METRICOOL_BLOG_ID on the backend")
    return token, user_id, blog_id


async def metricool_request(method: str, path: str, *, params: dict[str, Any] | None = None,
                            body: dict[str, Any] | None = None) -> Any:
    token, user_id, blog_id = _config()
    query = {"userId": user_id, "blogId": blog_id, **(params or {})}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=8), follow_redirects=False) as client:
        response = await client.request(method, f"{BASE_URL}{path}", params=query,
            json=body, headers={"X-Mc-Auth": token, "Content-Type": "application/json"})
        response.raise_for_status()
        return response.json() if response.content else {}


def metricool_status() -> dict[str, Any]:
    return {
        "provider": "metricool",
        "configured": bool(
            (get_secret("METRICOOL_API_TOKEN") or os.getenv("METRICOOL_API_TOKEN", "").strip())
            and (get_secret("METRICOOL_USER_ID") or os.getenv("METRICOOL_USER_ID", "").strip())
            and (get_secret("METRICOOL_BLOG_ID") or os.getenv("METRICOOL_BLOG_ID", "").strip())
        ),
        "required_backend_secrets": ["METRICOOL_API_TOKEN", "METRICOOL_USER_ID", "METRICOOL_BLOG_ID"],
        "capabilities": ["connected_brands", "scheduled_posts", "youtube_categories"],
        "channel_connection": "Connect the YouTube channel inside Metricool as the channel owner; the API token does not create a YouTube channel.",
    }


async def schedule_youtube_video(*, title: str, description: str, publication_datetime: str,
                                 timezone: str, media_ids: list[str], tags: list[str],
                                 category: str, privacy: str, made_for_kids: bool,
                                 ai_generated_content: bool, video_type: str) -> Any:
    if not media_ids:
        raise ValueError("At least one Metricool-uploaded media ID is required")
    body = {
        "publicationDate": {"dateTime": publication_datetime, "timezone": timezone},
        "text": description,
        "providers": [{"network": "youtube"}],
        "media": media_ids,
        "autoPublish": True,
        "youtubeData": {
            "title": title[:100],
            "type": video_type,
            "privacy": privacy,
            "tags": tags[:500],
            "category": category,
            "madeForKids": made_for_kids,
            "isAiGeneratedContent": ai_generated_content,
        },
    }
    return await metricool_request("POST", "/v2/scheduler/posts", body=body)
