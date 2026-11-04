# Free-first technology stack and hosting layout

Reviewed: 2026-11-04.

## Deployment separation

- **Backend:** this FastAPI repository is deployed as one lightweight Railway service from the root Dockerfile.
- **Database:** use the already connected Supabase Free PostgreSQL project for CRM records. Do not create a second database or provision Redis by default.
- **Frontend:** a separate Next.js application lives in `frontend/`. It uses React Three Fiber and Three.js for a procedural 3D command centre. Its server-side proxy keeps `BACKEND_API_KEY` out of browser code.
- **Frontend release gate:** the connected Vercel team currently uses Hobby. Vercel's official Hobby terms limit it to personal, non-commercial use, so this business control panel must not be deployed as a production business frontend on that plan. Keep the source ready; use an eligible commercial Vercel plan or a free host whose terms permit the use.

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

Set `CORS_ORIGINS` to the exact frontend origin after the frontend has an approved hosting target. The UI server-side proxy calls Railway and does not need a browser-side backend API key.

## Frontend environment variables

- `BACKEND_API_URL`: Railway HTTPS origin.
- `BACKEND_API_KEY`: copied into a Vercel server-only encrypted environment variable; never use the `NEXT_PUBLIC_` prefix.
- `DASHBOARD_PASSWORD`: a strong dashboard login password, server-side only.
- `DASHBOARD_SESSION_SECRET`: at least 32 random bytes, server-side only.

See `frontend/README.md` for local build and release instructions.
