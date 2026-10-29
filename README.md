# Universal AI Backend

**API-only backend** for an existing app. This repository brings together a searchable AI/software catalog, provider routing, worker-facing APIs, creator/channel workflows, specialist-agent blueprints, and a paired Windows JARVIS agent.

> **Architecture truth:** keep the code and deployment instructions in this single Git repository, but use the right runtime for each job. Vercel hosts the lightweight FastAPI control plane. GPU model inference, durable queues, media rendering and local Windows interaction run as worker services from this same repository. Vercel Functions are not a persistent GPU host. See the [Vercel Function limits](https://vercel.com/docs/functions/limitations).

## What's in this repository

- `app/`: FastAPI control plane, provider routing, API-key protection, manifest registry and safe outbound worker gateway.
- `catalog/`: curated repository references plus separate manifests for providers, voice/media engines, agents, workflows and social/business channels.
- `workers/voice_worker/`: asynchronous GPU voice worker with F5-TTS and MeloTTS adapters, consent-aware voice references, WAV/MP3/OGG/FLAC output and a Redis/Celery queue.
- `workers/media_worker/`: authenticated asset store, fixed FFmpeg render presets, thumbnail/audio/subtitle handling, and dispatch to reviewed ComfyUI workflows.
- `workers/youtube_worker/`: OAuth-backed official YouTube Data API video-upload worker with explicit approval and channel-ownership checks.
- `workers/channel_worker/`: approval-gated message adapters for Telegram, Discord, Slack and WhatsApp Business approved templates.
- `workers/agent_worker/`: asynchronous AI agent planner that returns a validated JSON action plan. It does not run arbitrary code or auto-execute plans.
- `workers/automation_worker/`: durable workflow dispatcher with an allowlist of voice, media, YouTube, messaging and desktop action routes.
- `workers/windows_agent/`: local paired Windows executor with app/URL allowlists, workspace-bounded file access, an optional persistent REA MCP bridge and approvals for sensitive actions.
- `workers/docker-compose.yml`: one Compose file for Redis and the Linux-hosted voice/media/YouTube/channel/agent/workflow services.
- `tests/` and `.github/workflows/tests.yml`: catalog safety, manifest and Python compile checks.

## What is working vs. what needs a separate deployment

The API and worker source code are committed to the repository. A catalog entry, API contract or Dockerfile **does not mean the worker is already running**.

| Capability | Implemented in this repo | Needs configuration / deployment |
|---|---|---|
| Chat/provider routing | OpenAI-compatible adapters and Anthropic Messages adapter | Provider API keys/model IDs and compatible base URLs |
| Voice TTS / voice cloning | F5-TTS CLI and MeloTTS worker paths, reference assets, profile metadata, async tasks | GPU host, model weights, queue, persistent storage and consent evidence |
| Image/video/audio | FFmpeg preset jobs and ComfyUI API workflow runner | Media worker, persistent disk, configured ComfyUI server and reviewed workflow/model files |
| YouTube publishing | Official OAuth/API upload task and approval checks | Google Cloud project, OAuth refresh token, quota, authorized channel and media asset |
| Channel messaging | Telegram, Discord, Slack and WhatsApp template-message adapters | Tokens, allowlisted targets, permissions/scopes and worker host; other catalog connectors are manifest-only |
| Agent planning | Async plan generation with configured chat model | Agent worker and model credentials; generated actions still require review |
| Workflow dispatch | Async dispatcher for explicit, typed actions | Automation worker, downstream worker URLs/secrets and explicit approval |
| Windows JARVIS | Paired local agent for selected computer actions | Install on your Windows PC and securely connect it to the control plane |
| Everything else in the catalog | Searchable metadata and GitHub discovery | A reviewed adapter, credentials, licenses, dependencies and tests for each integration |

This is an expandable integration hub, not a claim that every listed upstream project is installed, licensed for your use, or executable through the API. No repository can contain every tool that exists now, let alone future tools.

## Main API endpoints

After Vercel deploys this repository, open:

- API root: `/`
- Health: `/health`
- Swagger/OpenAPI: `/docs`
- Runtime and worker readiness: `/v1/runtime/capabilities`
- Tool catalog: `/v1/tools?q=voice`
- Skill catalog: `/v1/skills?q=browser`
- Catalog totals and license review statuses: `/v1/catalog/stats`
- Provider adapter status: `/v1/providers`
- Provider catalog: `/v1/models/providers`
- Voice engines and worker readiness: `/v1/voice/providers`
- Workflow blueprints: `/v1/workflows`
- Agent blueprints: `/v1/agents`
- Channel connector manifests: `/v1/channels`
- Live public repository discovery: `/v1/discover/github?q=browser+automation&license_filter=mit&min_stars=100`

Protected action endpoints require `X-API-Key: <BACKEND_API_KEY>` from a trusted server. **Do not put `BACKEND_API_KEY` in frontend JavaScript or mobile app source.** For a real multi-user app, put a login/session layer in front of these routes and bind approvals, assets and credentials to authenticated users/tenants.

### Action endpoints

- `POST /v1/chat/completions` — route a chat request to a configured provider.
- `POST /v1/voice/assets` — submit a small consented reference-audio asset to the voice worker.
- `POST /v1/voice/tts` and `POST /v1/voice/clone` — queue TTS or register a consented reference voice profile.
- `GET /v1/voice/results/{task_id}` — download generated voice audio.
- `POST /v1/media/jobs` — dispatch an FFmpeg/ComfyUI/ASR job.
- `POST /v1/agents/{agent_id}/run` — generate a safe action plan asynchronously; it does not execute model-proposed actions.
- `POST /v1/workflows/{workflow_id}/run` — return a workflow plan or dispatch explicitly typed actions supplied via `inputs.actions`.
- `POST /v1/channels/{channel_id}/actions` — run supported channel actions after approval.
- `POST /v1/youtube/publish` — queue an approved YouTube upload.
- `POST /v1/desktop/actions` — route approved actions to the paired Windows agent.
- `GET /v1/rea/tools` and `POST /v1/rea/jobs` — discover and queue allowlisted REA MCP analysis tools on the paired Windows PC; poll via `GET /v1/tasks/rea/{task_id}`.
- `GET /v1/tasks/{service}/{task_id}` — check a worker task's status.

Large video/audio uploads should go directly to the secured media worker's `POST /v1/assets/upload` endpoint, not through a Vercel function. Use asset IDs in subsequent requests; do not pass arbitrary server file paths.

## Deploy the control plane to Vercel

This repository is already connected to a Vercel project. Every push to `main` triggers a new deployment.

1. In Vercel Project Settings → Environment Variables, configure `BACKEND_API_KEY` with a strong random secret.
2. Add only the model provider variables you will use: for example `GROQ_API_KEY`, `GROQ_DEFAULT_MODEL`, or `AI_BASE_URL`, `AI_API_KEY`, `AI_DEFAULT_MODEL`.
3. Set `CORS_ORIGINS` to the exact origin of your existing app. Leave broad wildcard origins out of production.
4. Set worker variables such as `VOICE_WORKER_URL` and `VOICE_WORKER_API_KEY` after the worker is securely reachable over HTTPS.
5. Redeploy, then test `/health`, `/docs`, `/v1/catalog/stats` and `/v1/runtime/capabilities`.

A `READY` Vercel build only confirms the control-plane deployment. It does not indicate that optional GPU/media/channel/desktop workers are running or configured.

## Run the worker stack

The worker API ports in Compose bind to loopback; do not expose those ports directly to the public internet. The worker host needs Docker Compose. For the voice GPU service, use a Linux host with an NVIDIA GPU, compatible driver and NVIDIA Container Toolkit.

```bash
cp workers/.env.workers.example workers/.env.workers
# Edit workers/.env.workers: set unique secrets and only the OAuth/provider keys you need.
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml up --build -d
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml ps
```

Then expose each selected worker through a private network or an HTTPS reverse proxy/tunnel with strong access controls. Configure these Vercel environment variables with the corresponding secure URLs and matching secrets:

- `VOICE_WORKER_URL` / `VOICE_WORKER_API_KEY`
- `MEDIA_WORKER_URL` / `MEDIA_WORKER_API_KEY`
- `YOUTUBE_WORKER_URL` / `YOUTUBE_WORKER_API_KEY`
- `CHANNEL_WORKER_URL` / `CHANNEL_WORKER_API_KEY`
- `AGENT_WORKER_URL` / `AGENT_WORKER_API_KEY`
- `AUTOMATION_WORKER_URL` / `AUTOMATION_WORKER_API_KEY`

Set `AGENT_MODEL_BASE_URL`, `AGENT_MODEL_API_KEY` and `AGENT_DEFAULT_MODEL` in the worker host environment for the agent planner. The Windows desktop agent is not part of the Linux Compose stack; install `workers/windows_agent` locally on your own Windows PC and expose it only through a protected HTTPS tunnel/private network. For REA, install `rea-agents@6.8.0` globally on that PC, set `REA_ENTRY_SCRIPT`, enable the bridge locally, configure allowed target roots/URL hosts and manually allowlist exact MCP tool names.

### Model and license safety

F5-TTS is included as an engine adapter, but its source-code license and model-weight license are separate. The upstream F5-TTS project says the standard pretrained model weights are CC-BY-NC; the worker blocks commercial generation until a compatible checkpoint with commercial rights has been selected and reviewed. The `F5_TTS_MODEL_LICENSE_CLASS=commercial_approved` environment value is an operator attestation, not proof of rights. See the [F5-TTS repository](https://github.com/SWivid/F5-TTS).

Voice cloning, voice conversion and talking-avatar workflows require consent and rights to the reference voice/identity. The worker records a consent ID and checks that it matches; a production app must maintain genuine consent evidence, user identity, retention and revocation controls. Do not impersonate people without authorization.

The official [YouTube videos.insert endpoint](https://developers.google.com/youtube/v3/docs/videos/insert) requires OAuth, quotas and applicable YouTube API terms. The YouTube worker is configured for a single authorized channel connection at a time; multi-account production use needs a persistent encrypted OAuth connection store and per-tenant authorization.

## REA reverse-engineering integration

REA is an optional specialized CLI/MCP integration for evidence-backed analysis of authorized application artifacts—not a TTS model or universal action engine. Its npm package is MIT at the REA-authored-code level, while external analysis engines and third-party dependencies retain their own terms. The Windows-agent bridge uses local stdio, retains state across sequential calls and queues longer tasks. It is disabled by default and requires a local tool-name allowlist, explicit approval per call, file-root restrictions and URL-host restrictions. Do not expose REA's documented plain-HTTP MCP listener publicly; upstream says it has no TLS/client authentication and that runtime analysis is not a sandbox. More details: https://github.com/morluto/rea and https://github.com/morluto/rea/blob/main/docs/mcp-contracts.md.

## Commercial/open-source license classification

The catalog intentionally includes three different kinds of records:
- projects reported as open-source candidates;
- source-available/open-core/mixed-license projects whose enterprise edition or some components may have restrictions;
- hosted proprietary APIs with open-source SDKs.

Every catalog candidate still carries `license_status=review_required`. Verify the current code license, model weights, training data, bundled custom nodes, voice assets, dependencies, commercial/hosted-service terms and target platform policies before deployment. A free or open-source SDK does not make the connected hosted AI service free or open-source.

## Tests

GitHub Actions runs Python compile checks and catalog/manifest tests on pushes and pull requests. Worker images and GPU inference still need to be built and tested on a suitable worker host; the CI runner does not have the user's GPU, OAuth accounts or external worker credentials.

## Operational readiness and go-live

Run `python scripts/preflight.py --env-file .env` before local startup. For production, run `python scripts/preflight.py --env-file .env --worker-env-file workers/.env.workers --production`; add `--strict-workers` only when every declared worker is intended to be active. The checker prints configuration names/status only, never secret values.

After deploying the same commit SHA as GitHub `main`, run `python scripts/smoke_test.py https://universal-ai-backend.vercel.app --json`. The smoke test exercises read-only API endpoints and never posts content, sends a message or starts a worker job.

See [the complete Windows + production go-live checklist](docs/GO_LIVE_CHECKLIST.md) for Vercel setup, Docker Compose deployment, Windows JARVIS/REA setup, external provider credentials, live verification and production hardening.
