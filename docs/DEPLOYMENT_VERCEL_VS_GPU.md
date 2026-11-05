# Deployment: Vercel vs. a GPU host

Reviewed: 2026-11-05, against the live Vercel project and the worker stack in this repo.

## 1. What is already deployed

| Thing | Where | State |
|---|---|---|
| API control plane (`app/main.py`) | Vercel project `universal-ai-backend` | **Live** — `https://universal-ai-backend.vercel.app` |
| Production deployment | `dpl_GGVobV8WRvLyguiq7kPDVS3VGhgg` (main) | `READY` / `PROMOTED` |
| Env vars | Same project | `BACKEND_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CORS_ORIGINS`, `UNIVERSAL_AI_BACKEND_PUBLIC_URL`, `ENABLE_BUILTIN_CLOUD_RUNTIME=1` |
| 12 worker services (`workers/`) | **Not deployed anywhere** | `0 / 12` configured |

So "deploy the backend" is already done for the API half. What is missing is the
**worker half**, and that is the part a GPU host exists for.

## 2. The hard constraint nobody can code around

Vercel is serverless. It cannot run this half of the product, at any price:

| Vercel limitation | What it blocks here |
|---|---|
| No GPU of any kind | TTS, voice cloning, image/video generation, Whisper, F5-TTS |
| Function timeout (300 s configured here) | Long renders, batch media jobs, autopilot agent loops |
| No long-lived processes | Celery workers, Redis queues, `autopilot_worker` |
| No persistent local disk | FFmpeg temp files, rendered video output |
| Private-IP only between functions | Worker ports `8100`–`8700` are `127.0.0.1`-bound in compose |

**Conclusion: the control plane belongs on Vercel. The workers need a GPU host.**
Trying to force workers onto Vercel is a dead end, not a config problem.

## 3. Correct topology

```
                 ┌──────────────────────────────┐
   browser ──────►│  Vercel: universal-ai-backend │  catalog, chat proxy,
                 │  app/main.py (control plane)  │  auth, finance, discovery
                 └───────────────┬──────────────┘
                                 │ HTTPS + worker API key
                 ┌───────────────▼──────────────┐
                 │  GPU host (RunPod / Vast /    │  12 worker services
                 │  Lambda / any Docker host)    │  + Redis
                 │  workers/docker-compose.yml   │
                 └──────────────────────────────┘
```

The control plane never needs GPU. The GPU host never needs the catalog.

## 4. Wiring the two halves

For each worker you actually run, set on the **Vercel** side:

| Worker | URL env var | Key env var |
|---|---|---|
| Voice / TTS | `VOICE_WORKER_URL` | `VOICE_WORKER_API_KEY` |
| Media (FFmpeg, video) | `MEDIA_WORKER_URL` | `MEDIA_WORKER_API_KEY` |
| Automation | `AUTOMATION_WORKER_URL` | `AUTOMATION_WORKER_API_KEY` |
| Agents | `AGENT_WORKER_URL` | `AGENT_WORKER_API_KEY` |
| YouTube | `YOUTUBE_WORKER_URL` | `YOUTUBE_WORKER_API_KEY` |
| Channels | `CHANNEL_WORKER_URL` | `CHANNEL_WORKER_API_KEY` |
| REA inspection | `REA_WORKER_URL` | `REA_WORKER_API_KEY` |
| Plugins / mail / finance | `PLUGIN_` / `MAIL_` / `FINANCE_WORKER_*` | same pattern |
| Desktop control | `DESKTOP_AGENT_URL` | `DESKTOP_AGENT_API_KEY` |

`GET /v1/runtime/capabilities` and `GET /v1/workers/status` flip from
`not_configured` to `configured` as you add each pair — that endpoint is the
honest readiness check, and the Studio Overview reads it live.

`WORKER_ALLOW_INSECURE_HTTP` must stay unset in production; workers are expected
over HTTPS.

## 5. Deploying the worker stack (any Docker host)

```bash
# on the GPU host
git clone https://github.com/zeeburgers00-glitch/universal-ai-backend.git
cd universal-ai-backend/workers
cp .env.workers.example .env.workers      # set REDIS_PASSWORD + provider keys
docker compose up -d                       # redis + 12 worker services
docker compose ps                          # each service should be healthy
```

Notes taken from `workers/docker-compose.yml`:

- Worker HTTP APIs bind `127.0.0.1:8100`–`8700`, so put a reverse proxy (Caddy,
  nginx, or the host's public gateway) in front to expose them over HTTPS.
- Celery workers share one Redis (`CELERY_BROKER_URL`).
- `autopilot_worker` is started with `--concurrency=${AUTOPILOT_MAX_PARALLEL_AGENTS:-5}`;
  keep it low on a single GPU.
- GPU images (`voice_worker`, `media_worker`) need the CUDA base image variant;
  check each `workers/*/Dockerfile` before provisioning.

## 6. Before deleting anything on Vercel

Deleting the project `universal-ai-backend` would immediately:

1. **Kill `https://universal-ai-backend.vercel.app`**, which is the value of
   `UNIVERSAL_AI_BACKEND_PUBLIC_URL` and is what the Base44 apps
   (`ytlabbybg.base44.app`, `bglabs-nexus-core.base44.app`) call.
2. **Permanently destroy secrets.** `BACKEND_API_KEY` and
   `SUPABASE_SERVICE_ROLE_KEY` are stored as Vercel `sensitive` values — Vercel
   never shows them again, so once deleted they cannot be recovered from Vercel.
3. **Lose the GitHub link**, so future `main` pushes stop deploying.

A safer ordering when migrating to a GPU host:

1. Deploy the worker stack and verify `/v1/workers/status`.
2. Deploy the control plane to the new host and verify `/health` + `/app`.
3. Re-point Base44 / frontend URLs at the new host.
4. Only then pause the project on Vercel, wait a few days, and delete last.
   `pause_project` stops traffic without destroying secrets — use it as the
   reversible first step instead of `delete_project`.
