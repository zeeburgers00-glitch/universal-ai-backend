# Workers in the same repository

The repository stores the API control plane, catalog, workflow/agent manifests, and worker code. **Vercel should host the lightweight FastAPI control plane.** Heavy GPU inference, long-lived queues, and desktop control run as services whose code remains in this same Git repository.

## Why not put every model in a Vercel Function?

Vercel Functions have deployment bundle, memory and execution-duration constraints; they are not a persistent GPU host. For example, current Vercel documentation describes a 500 MB uncompressed bundle limit for Python functions and plan/runtime-specific memory/duration ceilings. F5-TTS, voice conversion, avatar generation and video diffusion require model weights plus GPU dependencies that do not fit the serverless execution model reliably. See https://vercel.com/docs/functions/limitations.

## GPU voice worker

The first worker scaffold is at `workers/voice_worker`. It contains:
- an authenticated API for consented voice-reference assets, profile metadata, TTS jobs, task status and result download;
- Redis/Celery for async jobs so a Vercel request does not wait for a multi-minute GPU generation;
- F5-TTS CLI inference and MeloTTS preset-speaker inference;
- isolated generated files under a persistent mounted volume;
- explicit consent checks for user-provided reference voices.

### Run it on a GPU host

1. Install Docker Engine/Compose and an NVIDIA driver plus NVIDIA Container Toolkit.
2. Copy `workers/.env.voice.example` to a private environment file on the worker host.
3. Change `VOICE_WORKER_API_KEY` and `REDIS_PASSWORD` to unique, long secrets.
4. From the repository root run `docker compose --env-file workers/.env.voice -f workers/docker-compose.voice.yml up --build -d`.
5. Put the API endpoint behind HTTPS/private networking. The compose file binds port 8100 to loopback only.
6. In Vercel Environment Variables, configure `VOICE_WORKER_URL=https://your-private-or-tunnel-host` and `VOICE_WORKER_API_KEY` using the same secret. Redeploy the Vercel project.
7. Test `GET /v1/runtime/capabilities`, `GET /v1/voice/providers`, upload a consented voice sample, enqueue a TTS job and poll `GET /v1/tasks/voice/{task_id}`.

### Model and commercial-use caution

F5-TTS code is MIT, but its upstream README says the standard pretrained model weights are CC-BY-NC. The worker therefore blocks commercial generation unless a compatible model/checkpoint has been reviewed and `F5_TTS_MODEL_LICENSE_CLASS=commercial_approved` is set by the operator. This setting is an attestation, not a license: keep evidence of the actual model/checkpoint rights. See https://github.com/SWivid/F5-TTS.

MeloTTS is included as a preset-speaker engine, but its library/voice assets and other dependency licenses still need review. OpenVoice, GPT-SoVITS, CosyVoice, XTTS-v2, Fish Speech, RVC and external voice APIs are cataloged and routed through the same worker boundary; they are **not all implemented by this first worker image**. Do not label an engine active until its runtime and licenses have been tested.

## Worker contract

Vercel sends JSON requests to these configured HTTPS base URLs:
- `VOICE_WORKER_URL` — `POST /v1/voice/tts`, `POST /v1/voice/clone`, `POST /v1/voice/assets`, `GET /v1/tasks/{task_id}`, `GET /v1/voice/results/{task_id}`
- `MEDIA_WORKER_URL` — media jobs (image/video/audio/render)
- `AUTOMATION_WORKER_URL` — durable workflow orchestration
- `AGENT_WORKER_URL` — specialist agent plans and tool calls
- `DESKTOP_AGENT_URL` — paired, authenticated Windows desktop agent
- `YOUTUBE_WORKER_URL` — OAuth-backed YouTube publishing/analytics worker
- `CHANNEL_WORKER_URL` — allowlisted Telegram, Discord, Slack, and WhatsApp channel worker
- `REA_WORKER_URL` — isolated REA (`morluto/rea`) static artifact, JS bundle, and GGUF/safetensors inspection worker

Worker scaffolds are provided under `workers/` (`voice_worker`, `media_worker`, `youtube_worker`, `channel_worker`, `agent_worker`, `automation_worker`, `rea_worker`, and `windows_agent`) and orchestrated via `workers/docker-compose.yml`. Keep all secrets in each hosting provider's secret/environment settings, never commit them to GitHub.

