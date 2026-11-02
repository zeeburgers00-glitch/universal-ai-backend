# AI YouTube Studio Autopilot — architecture and real API limits

## Deployment topology

- studio/: Next.js App Router frontend intended for Vercel.
- services/youtube-api/: Fastify API intended for Railway. It verifies Supabase access tokens, owns Google OAuth, encrypts refresh tokens, writes user-scoped rows and enqueues work.
- services/youtube-worker/: isolated BullMQ worker intended for Railway. Media generation and publishing do not run inside Vercel request handlers.
- database/migrations/: Supabase schema, RLS and private media bucket.

The existing Universal AI Backend (FastAPI and Celery modules) remains in the repository. This product-specific Node service is a separate deployable surface so the previous agent platform is not removed.

## User identity and Google OAuth

The user signs in to the studio through Supabase Auth email OTP. The API verifies the bearer token with Supabase Auth getUser before accessing user data. YouTube authorization is a separate Google OAuth flow. The API requests youtube.readonly and youtube.upload. OAuth state is HMAC-signed, bound to the user and single-use in Redis. Google refresh and access tokens are encrypted with AES-256-GCM before they are stored in the private youtube_connections table. The encryption key and OAuth secret must exist only in Railway variables.

The YouTube channel is discovered with channels.list(mine=true). The API does not create a Google account or channel. When no channel exists, the UI directs the user to YouTube's official channel creation interface.

## YouTube capabilities verified from the current official API reference

- The YouTube Data API reference lists channels.list and channels.update; there is no channels.insert method for creating a channel. Channel creation must be done by the user in YouTube.
- channels.update supports selected branding settings such as description, keywords, default language and localization fields. It does not allow changing the channel title through this API operation.
- The official reference lists channelBanners.insert, followed by channels.update, as the banner upload flow. Profile picture replacement is not presented as an equivalent supported channel API operation in this implementation; use YouTube Studio for that manual step.
- videos.insert uploads a video. For a scheduled publication, status.privacyStatus must be private and status.publishAt must be a future ISO timestamp; publishAt is only allowed for a private video that has never previously been published.
- The video status resource includes containsSyntheticMedia for declaring realistic altered or synthetic content, and selfDeclaredMadeForKids for the audience declaration. The product must collect these user decisions; it does not guess either field.

References:
- https://developers.google.com/youtube/v3/docs/
- https://developers.google.com/youtube/data/reference/rest/v3/videos
- https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- https://developers.google.com/youtube/data/reference/rest/v3/channels
- https://developers.google.com/youtube/data/reference/rest/v3/channels/update
- https://developers.google.com/youtube/data/reference/rest/v3/channelBanners/insert
- https://developers.google.com/identity/protocols/oauth2/scopes

## Fail-closed autopublish

The API keeps autopublish disabled by default. Enabling it requires a connected YouTube channel, a positive daily budget, Redis, and the configured research/model/media providers. Audience and altered/synthetic-content declarations must be explicit. Worker stages write durable status and audit rows. A failed provider call, missing licensing information, failed quality check, budget exhaustion, missing OAuth, or policy gate blocks upload. Retries reuse the same production job ID and idempotency key.

Scheduled uploads use videos.insert with private privacy and publishAt in the future. The worker records the returned YouTube video ID and watch URL; a queue event or local file is never reported as a successful YouTube upload.

## Media pipeline configuration

The intended production worker uses:
- TAVILY_API_KEY for source-backed research results
- MODEL_API_KEY, MODEL_BASE_URL and MODEL_NAME for original brief and script generation
- PEXELS_API_KEY for stock video clips, with Pexels source URLs retained in job output
- ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID for voiceover generation
- OPENAI_API_KEY for Whisper transcription
- FFmpeg and ffprobe installed inside the worker image
- Supabase private storage bucket youtube-media for final assets and signed previews
- GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and TOKEN_ENCRYPTION_KEY on the API; only the worker service role accesses encrypted connection rows

RunPod is a configurable optional GPU execution adapter for heavy rendering or model inference. It is not itself an AI model. Do not mark RunPod enabled unless an endpoint URL, model workflow and credential are configured and health checked.

## Required environment settings

API:
SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, REDIS_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, TOKEN_ENCRYPTION_KEY, OAUTH_STATE_SECRET, WEB_APP_URL, CORS_ORIGINS.

Worker:
SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, REDIS_URL, TOKEN_ENCRYPTION_KEY, MODEL_API_KEY, MODEL_BASE_URL, MODEL_NAME, TAVILY_API_KEY, PEXELS_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, OPENAI_API_KEY, VIDEO_COST_ESTIMATE_USD, MAX_VIDEO_DURATION_SECONDS.

Frontend:
NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_BASE_URL. No provider secrets or service-role key may use a NEXT_PUBLIC prefix.

## Initial status

Source code and migrations are not equivalent to a running deployment. The API and worker require host-side credentials and a live Redis/Supabase project. Google OAuth requires the exact callback URL to be registered in Google Cloud. Vercel must use studio/ as its root directory and the frontend environment variables must be set. The Railway workspace in this account currently has offline services and a plan limitation, so code changes alone do not activate a worker or start paid jobs.



## Four-agent YouTube creator team

The repository now includes a dedicated four-seat team manifest at `catalog/youtube_creator_team.json` and the `youtube-four-agent-team` workflow:

1. **Thumbnail Designer** — creates a truthful thumbnail concept, 16:9 layout, overlay options and image-generation prompt. A rendered image is only confirmed when the media worker returns an actual asset.
2. **YouTube SEO Specialist** — creates title options, keyword clusters, source-aware description, tags, hashtags, chapters when timeline evidence exists and a pinned-comment draft.
3. **Long-form Video Production Agent** — plans a 16:9 long-form production using licensed stock-video footage, narration, synchronized captions and FFmpeg.
4. **Shorts Video Production Agent** — plans standalone 9:16 Shorts with opening hooks, highlight/timecode selection, reframing and readable captions.

The long-form and Shorts production steps share a `video-production` parallel group. Both depend on the approved script; thumbnail design depends on the SEO package and long-form video plan. Review is required before the publisher step.

### Team API and execution status

- `GET /v1/youtube/team` returns the four-seat team manifest.
- `GET /v1/agents` lists the four individual agent blueprints.
- `POST /v1/agents/{agent_id}/run` sends an agent task to the agent worker when deployed.
- `POST /v1/workflows/youtube-four-agent-team/run` requests a workflow plan. Workflow step dependencies, parallel group labels and expected outputs are included in the returned plan.

**Important:** The agent worker is currently a plan-only worker. These are registered specialist blueprints, not four continuously running processes. Its response describes actions and expected outputs; it does not itself render the thumbnail, encode the video or publish to YouTube. Actual asset creation needs the media/voice/caption services, and upload/scheduling remains behind the connected channel owner's explicit approval. A workflow plan or queued task is not proof of a completed media asset or YouTube upload.


## Operational API endpoints

Authenticated routes use a Supabase Auth access token in the Authorization bearer header:
- GET /v1/dashboard — channel, settings, recent jobs, rolling-24-hour reserved cost and provider readiness.
- GET /v1/providers/status — configured/not-configured state for model, research, Pexels, voice, captions, YouTube OAuth, Redis, worker heartbeat, storage and optional RunPod. Secret values are never returned.
- POST /v1/jobs with an Idempotency-Key — queue a production job.
- GET /v1/jobs/:jobId/events — user-scoped durable audit events for that job.
- POST /v1/jobs/:jobId/retry — retries only failed/blocked jobs that have no YouTube upload-start marker or video ID; duplicate-upload risk is blocked.
- POST /v1/automation/enable — explicit user opt-in after configured prerequisites are checked.
- POST /v1/automation/disable and /v1/automation/stop-all — cancel future automation; stop-all also cancels queued/running DB jobs.

## Budget enforcement

Every production job calls reserve_creator_video_budget in Postgres. The function serializes reservations per user with an advisory transaction lock, checks the rolling 24-hour budget and writes one idempotent estimated reservation per job. The worker does not launch media generation if the reservation is rejected. This is an estimate, not an exact provider invoice; vendor billing dashboards remain authoritative. The reservation is intentionally conservative and may count failed attempts until the job is reconciled.

## Storage and progress

youtube-media is a private Supabase Storage bucket. Worker files are not made public; the API returns only signed preview URLs. The worker publishes a 60-second Redis heartbeat which the provider-status endpoint uses to distinguish a configured queue from a live worker. Audit events are keyed by user and job and are queried only after verifying ownership of the job.
