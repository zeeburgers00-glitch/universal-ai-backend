import os
import re
from pathlib import Path
from typing import Any

from youtube_worker.app import celery_app


@celery_app.task(bind=True, name="youtube_worker.publish_video", acks_late=True)
def publish_video(self, payload: dict[str, Any]) -> dict[str, Any]:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    task_id = str(self.request.id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise ValueError("Invalid task identifier")
    if not payload.get("user_approved"):
        raise PermissionError("Publishing must be explicitly approved")

    configured_connection = os.getenv("YOUTUBE_CHANNEL_CONNECTION_ID", "").strip()
    if payload.get("channel_connection_id") != configured_connection or not configured_connection:
        raise PermissionError("This channel connection is not configured")
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CHANNEL_ID"]
    if not all(os.getenv(key, "").strip() for key in required):
        raise RuntimeError("YouTube OAuth environment is incomplete")

    asset_id = str(payload.get("video_asset_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,160}", asset_id):
        raise ValueError("Invalid video asset ID")
    asset_root = Path(os.getenv("YOUTUBE_MEDIA_ASSET_ROOT", "/data/assets/videos")).resolve()
    metadata_path = (asset_root / f"{asset_id}.json").resolve()
    if asset_root not in metadata_path.parents or not metadata_path.is_file():
        raise FileNotFoundError("Video asset metadata was not found in the configured media store")
    import json
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    stored_name = str(meta.get("stored_filename", ""))
    if Path(stored_name).name != stored_name:
        raise ValueError("Invalid stored asset filename")
    video_path = (asset_root / stored_name).resolve()
    if asset_root not in video_path.parents or not video_path.is_file():
        raise FileNotFoundError("Video asset file is not available")

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=scopes,
    )
    creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    channel_check = youtube.channels().list(part="id", mine=True, maxResults=10).execute(num_retries=2)
    configured_channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
    authorized_channel_ids = {str(item.get("id", "")) for item in channel_check.get("items", [])}
    if configured_channel_id not in authorized_channel_ids:
        raise PermissionError("The OAuth token does not authorize the configured YouTube channel ID")
    privacy = payload.get("privacy_status", "private")
    status_body: dict[str, Any] = {"privacyStatus": privacy}
    made_for_kids = payload.get("self_declared_made_for_kids")
    if made_for_kids is not None:
        if not isinstance(made_for_kids, bool):
            raise ValueError("self_declared_made_for_kids must be a boolean or null")
        status_body["selfDeclaredMadeForKids"] = made_for_kids
    publish_at = payload.get("publish_at")
    if publish_at:
        # YouTube scheduling requires a future ISO 8601 time and a private status.
        if privacy != "private":
            raise ValueError("Scheduled YouTube videos must use privacy_status='private'")
        status_body["publishAt"] = publish_at

    snippet = {
        "title": str(payload.get("title", ""))[:100],
        "description": str(payload.get("description", ""))[:5000],
        "tags": [str(tag)[:100] for tag in payload.get("tags", [])[:100]],
        "categoryId": os.getenv("YOUTUBE_DEFAULT_CATEGORY_ID", "22"),
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body={"snippet": snippet, "status": status_body},
        media_body=MediaFileUpload(str(video_path), mimetype=meta.get("mime_type", "video/mp4"),
                                   chunksize=8 * 1024 * 1024, resumable=True),
        notifySubscribers=False,
    )
    response = request.execute(num_retries=3)
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube accepted no video ID")
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel_id": os.getenv("YOUTUBE_CHANNEL_ID"), "privacy_status": privacy, "status": "uploaded"}
