# Chat-first YouTube autopilot architecture

## User experience

The AutoTube frontend is intentionally reduced to one chat surface. It does not expose agent directories, worker consoles, tool catalogues, provider settings, or production dashboards. The browser sends a message to a Vercel serverless proxy. That proxy holds the backend API key server-side and forwards requests to FastAPI. The browser never receives the backend key.

The chat displays durable task events: queued, request understanding, specialist assignment, specialist progress, quality review, and completion/failure. It polls the task status endpoint; the source of truth is Supabase, not browser memory.

## 120-slot specialist fleet

`catalog/youtube_agent_fleet.json` defines 17 specialist role families and 120 on-demand role slots. These are available worker slots/templates, not 120 continuously running processes. The Celery autopilot worker dynamically assigns a small task-scoped team (default 5 parallel agents) and the cap can be raised with `AUTOPILOT_MAX_PARALLEL_AGENTS` if the worker capacity, provider limits and budget support it.

For YouTube-related prompts, the current orchestrator delegates to five specialist model calls: research/trends, scriptwriting, SEO/packaging, visual storyboard, and quality/policy review. It merges the deliverables into one answer. It must not invent live trend metrics or claim it browsed external sources. Live web research, Pexels download, TTS, FFmpeg rendering and upload remain separate tool/worker integrations; the assistant reports these as pending unless those workers actually execute.

## Durable backend requirements

Apply the `autopilot_chat_runs_events` Supabase migration. Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` only on backend/worker hosts. The migration enables RLS and revokes direct anon/authenticated access; only the backend service role accesses run/event/message rows.

Run Redis and the dedicated Celery worker using `workers/docker-compose.yml`. The API host also needs `CELERY_BROKER_URL`. Keep Redis private and password protected.

Required server-side settings:
- `BACKEND_API_KEY`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `CELERY_BROKER_URL`
- `AUTOPILOT_MODEL_API_KEY`, `AUTOPILOT_DEFAULT_MODEL` and optionally `AUTOPILOT_MODEL_BASE_URL`
- `AUTOPILOT_MAX_PARALLEL_AGENTS` (default 5)

## Vercel chat proxy

The Vercel project with root directory `autotube` serves `index.html` and `api/chat.js`. Set the following Vercel **server-side** environment variables:
- `BACKEND_API_URL`: public HTTPS base URL of the deployed FastAPI service
- `BACKEND_API_KEY`: same secret as the backend's `BACKEND_API_KEY`

Do not use a `VITE_` prefix for either secret. Vite variables are public browser bundle values.

## Metricool and YouTube

Metricool is the connected-channel scheduling and analytics layer, not a YouTube channel creator. The channel owner connects the existing YouTube channel inside Metricool. The backend adapter can then list Metricool brands, scheduled posts and YouTube categories using `METRICOOL_API_TOKEN`, `METRICOOL_USER_ID` and `METRICOOL_BLOG_ID`. Metricool API access requires its Advanced or Custom plan. YouTube channel connection requires the channel Owner role.

The current API adapter provides:
- `GET /v1/integrations/metricool/status`
- `GET /v1/integrations/metricool/brands`
- `GET /v1/integrations/metricool/youtube/categories`
- `GET /v1/integrations/metricool/scheduled-posts?start=...&end=...`

Use the official YouTube Data API worker for channel metadata/branding and video upload where Metricool's documented API does not expose a needed channel-management action. Do not claim a channel was created: YouTube does not provide a general API method for creating new channels.

## Deployment status

These changes are committed to GitHub. They do not deploy a backend automatically. Railway previously rejected project creation because the account trial had expired. The backend still needs an active Railway plan or another connected host, Redis, Supabase backend secrets, model provider credentials, and Vercel's two server-side proxy variables before the chat can run live tasks.
