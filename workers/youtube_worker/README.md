# YouTube publisher worker

This worker implements an approval-gated video upload job using the official YouTube Data API. It is separate from the Vercel FastAPI control plane but its source code is part of this repository.

## Required secrets / settings

- `YOUTUBE_WORKER_API_KEY`: shared secret for the Vercel-to-worker connection.
- `CELERY_BROKER_URL`: Redis broker reachable by both API and Celery runner.
- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`: OAuth credentials for the owner-authorized channel.
- `YOUTUBE_CHANNEL_ID`: expected channel ID.
- `YOUTUBE_CHANNEL_CONNECTION_ID`: stable connection ID accepted by this single-channel worker.
- `YOUTUBE_MEDIA_ASSET_ROOT`: directory containing generated/uploaded video assets.

## Uploading

The worker accepts a video asset ID, never an arbitrary path or URL, then resolves it under the configured media root. Each asset needs a JSON sidecar such as `<asset_id>.json` with a safe `stored_filename` and `mime_type`. The asset should come from a reviewed media worker in the same trusted private network/volume. Do not expose local filesystem paths or worker secrets to callers.

The endpoint returns a task ID immediately; poll `GET /v1/tasks/{task_id}`. It performs an actual API upload only if the channel OAuth config exists and the caller has set `user_approved=true`.

## Limits and platform policies

The official API has quotas and OAuth scope requirements. Default video upload quota allocation/behavior can change; review the current Google developer console quota and YouTube API terms. Do not use this worker for unauthorized copyrighted uploads, spam, fake engagement, or bypassing platform restrictions.

For multiple accounts, do not reuse one refresh token for every user. Replace the single-channel environment setup with an encrypted, audited OAuth connection store keyed by tenant/account, and verify every connection's scopes and channel ownership.
