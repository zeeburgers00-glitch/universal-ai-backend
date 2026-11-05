# RunPod GPU deployment kit

One GPU pod runs the whole product: the FastAPI control plane **and** the worker
services that Vercel physically cannot run (no GPU, no long-lived processes).

Validated against `workers/docker-compose.yml` and `app/task_gateway.py` in this
repo. Files here:

| File | Purpose |
|---|---|
| `docker-compose.yml` | API + Redis + 7 HTTP worker services on one pod |
| `.env.runpod.example` | every variable to fill in |
| `bootstrap.sh` | one-command first boot |
| `README.md` | this file |

---

## Why this exists

Vercel is serverless: no GPU, a 300 s function ceiling, no Celery, no local disk.
The 12 worker services in `workers/` therefore report `not_configured` on Vercel
forever. A GPU pod is where they belong.

---

## Step 1 — Create the pod (RunPod console)

1. **Pods → Deploy** → pick **GPU**: RTX 4090 (24 GB) is enough for TTS +
   FFmpeg; A100/H100 only if you run local video generation.
2. **Template**: choose any *"RunPod PyTorch"* template — or "Custom" with image
   `runpod/pytorch:2.6.0-py3.11-cuda12.4.1-devel-ubuntu22.04`.
3. **Disk**: container 60 GB, **volume 100 GB** mounted at `/workspace`
   (rendered video and voice assets live here).
4. **Expose HTTP ports**: `8000` (API + Studio), and optionally `8100`-`8700`.
   RunPod gives you `https://<pod-id>-8000.proxy.runpod.net`.
5. Deploy and open the **Web Terminal**.

## Step 2 — First boot

```bash
cd /workspace
bash <(curl -fsSL https://raw.githubusercontent.com/zeeburgers00-glitch/universal-ai-backend/main/deploy/runpod/bootstrap.sh)
```

Or manually:

```bash
cd /workspace
git clone https://github.com/zeeburgers00-glitch/universal-ai-backend.git
cd universal-ai-backend/deploy/runpod
cp .env.runpod.example .env
nano .env                      # fill in the secrets marked REQUIRED
docker compose up -d
docker compose ps
```

## Step 3 — Verify

```bash
curl -s localhost:8000/health
curl -s localhost:8000/v1/runtime/capabilities | python3 -m json.tool
```

`ready_workers` must climb from `0` toward `7`. Then open:

- `https://<pod-id>-8000.proxy.runpod.net/app` — the Studio UI
- `https://<pod-id>-8000.proxy.runpod.net/docs` — OpenAPI

## Step 4 — Wire the rest of the world

Set `BACKEND_API_KEY` in your downstream apps (Base44, frontends) to the same
value you put in `.env`, and update any hard-coded
`https://universal-ai-backend.vercel.app` reference to the new RunPod URL.

---

## GPU notes (no marketing, just limits)

- `voice_worker` uses `pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` and pulls
  `f5-tts` + `MeloTTS`. First `docker compose build voice_worker` downloads
  several GB — expect 10-20 minutes on a cold pod.
- `media_worker` is CPU-only (`python:3.12-slim` + FFmpeg). It does **not** need
  the GPU; it is here because it needs a real disk and no time limit.
- The Celery workers in `workers/docker-compose.yml` are optional. The API talks
  to workers over HTTP, so the HTTP services in this file are what make
  `/v1/voice/tts` and friends return `configured`.
- Restarting the pod does not restore the volume automatically — set up RunPod's
  volume mount at `/workspace` so `/data` survives.

## Security

- `WORKER_ALLOW_INSECURE_HTTP=1` is set **because traffic stays inside the pod's
  private Docker network**. Never expose worker ports publicly on RunPod.
- Only publish `8000`. If you must publish a worker port, put a TLS proxy in
  front and unset `WORKER_ALLOW_INSECURE_HTTP`.
- `BACKEND_API_KEY` is the only thing protecting `/v1/chat/completions`,
  `/v1/finance/*` and `/v1/voice/*`. Use a long random value.

## Cost reality

A 4090 pod is roughly $0.35-0.70/hour while running. Stop the pod when idle;
`docker compose down` inside a stopped pod is not needed. Nothing here is free
at the GPU tier — the cursor-based catalog, catalog search and Studio UI remain
free on Vercel if you keep that deployment alive.
