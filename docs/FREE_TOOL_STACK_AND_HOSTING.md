# Free-first technology stack and hosting layout

Reviewed: 2026-11-04.

## Deployment separation

- **Backend:** this FastAPI repository is deployed as one lightweight Railway service from the root Dockerfile.
- **Database:** use the already connected Supabase Free PostgreSQL project for CRM records. Do not create a second database or provision Redis by default.
- **Frontend:** removed on request — this repo is backend-only now. The control plane serves its own pages at `/app`, `/studio` and `/explorer`, so a separate Next.js app is not needed.
- **Frontend release gate:** not applicable — there is no separate frontend to deploy.

## Railway Free guardrails

Railway Free currently includes $1/month of resource credit and is limited to one replica, 0.5 GB RAM, one vCPU and 1 GB ephemeral storage. Railway service builds are free. The service is configured to sleep when idle so it does not hold memory continuously. This is a low-volume API/development footprint, not a promise of high availability or always-on worker capacity.

No paid tier, GPU, persistent Railway volume, extra Redis service or always-on agent fleet is enabled by this configuration. Check the Railway workspace's usage dashboard; stop the service if the free monthly credit is exhausted rather than upgrading automatically.

## Included free/open-source components

| Layer | Default | Notes |
|---|---|---|
| API runtime | Python, FastAPI, Uvicorn, Pydantic, HTTPX | Open-source runtime and API packages |
| CRM database | Existing Supabase Free PostgreSQL | Private RLS-enabled tables; service role remains server-side |
| Frontend | Next.js, React | MIT-licensed app framework |
| 3D rendering | Three.js, @react-three/fiber, @react-three/drei | MIT-licensed; geometry is created procedurally, so no paid 3D assets are required |
| Hosted LLM fallback | Groq free developer tier or OpenRouter free model variants | Optional, requires the owner's API key; strict provider quotas; availability can change |
| Local model alternative | Ollama on a user-owned computer | Software is free; local compute and compatible hardware are required |
| Stock media | Pexels API | Optional; per-asset licence/attribution must be checked |
| Local transcription / TTS | whisper.cpp / Piper | Optional local workers; voice-model licenses vary |

## Important limits

- “Free API tier” means quota-limited, not unlimited or guaranteed.
- No AI provider key is configured unless it is explicitly supplied and stored server-side.
- Railway Free's 0.5 GB memory is not suitable for self-hosting a large LLM, video renderer, stable diffusion image model, or Windows desktop worker.
- The 120-agent catalogue contains role blueprints. It is not 120 continuously running agents.
- The backend's built-in worker fallback is disabled in Railway production so unconfigured integrations are not falsely reported as ready.
- Sending outreach, publishing content, accepting clients/payments and spending money remain separate approval-gated actions.

## Railway environment variables

Required core variables copied from the existing backend configuration:
- `BACKEND_API_KEY` (sensitive)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (sensitive)
- `BASE44_ACCESS_TOKEN` (sensitive, only for the existing Base44 connector)
- `ENABLE_BUILTIN_CLOUD_RUNTIME=0`
- `DEPLOY_PLATFORM=railway`

Set `CORS_ORIGINS` only if you add a browser client later; the built-in pages are served by the backend on the same origin.

## Frontend environment variables

- `BACKEND_API_URL`: Railway HTTPS origin.
- `BACKEND_API_KEY`: copied into a Vercel server-only encrypted environment variable; never use the `NEXT_PUBLIC_` prefix.
- `DASHBOARD_PASSWORD`: a strong dashboard login password, server-side only.
- `DASHBOARD_SESSION_SECRET`: at least 32 random bytes, server-side only.


