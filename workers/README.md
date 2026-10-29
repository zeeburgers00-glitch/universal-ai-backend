
# Worker deployment guide

All worker source code lives in this repository. Vercel deploys the lightweight `app.main:app` control plane; Linux services host persistent Redis queues, GPU inference, media, agent planning and workflow dispatch; the Windows agent runs on the user's PC.

## Start the Linux workers together

From the repo root:

```bash
cp workers/.env.workers.example workers/.env.workers
# Edit workers/.env.workers and set unique secrets/provider OAuth details.
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml up --build -d
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml ps
```

The Compose file defines:
- Redis with password protection and persistent data;
- F5-TTS/MeloTTS voice API + GPU queue runner;
- FFmpeg/ComfyUI media API + queue runner;
- YouTube official API + queue runner;
- Telegram/Discord/Slack/WhatsApp channel API;
- LLM agent planner API + queue runner;
- workflow dispatch API + queue runner.

Voice requires a CUDA-compatible Linux host, GPU driver and NVIDIA Container Toolkit. Other services can run on a regular Linux host. Media files, voice assets and queue results require persistent volumes and backup/retention rules.

## Expose securely

The Compose ports bind to `127.0.0.1`. Leave them loopback-only and use a protected HTTPS reverse proxy, private network or access-controlled tunnel. Configure the matching URLs and shared secrets in Vercel. Do not place shared keys in public frontend code.

## Individual services

- `voice_worker/`: GPU TTS and consented voice profiles.
- `media_worker/`: authenticated uploads and media processing; ComfyUI needs a configured remote/local engine and reviewed workflow templates.
- `youtube_worker/`: official YouTube upload using OAuth and a single configured channel connection.
- `channel_worker/`: Telegram, Discord, Slack and WhatsApp Cloud approved templates.
- `agent_worker/`: JSON plan creation from a configured model; proposed actions are never auto-executed.
- `automation_worker/`: plan-only workflow manifests or dispatch of explicit fixed action types after approval.
- `windows_agent/`: local Windows app, mouse/keyboard and workspace-bound file actions; arbitrary shell and software installation are disabled by default.

The repository also has other provider/channel/model references that are catalog-only. Each still needs its own adapter, credentials/consent, license review and tests before being described as active.
