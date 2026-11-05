# Free-tier CPU deployment ($0 / month, 24/7)

Runs the whole backend — API, Studio UI, Redis and **6 of the 7 worker
services** — on the Oracle Cloud Always Free ARM instance. No GPU, no card, no
expiring trial credit.

| File | Purpose |
|---|---|
| `docker-compose.yml` | API + Redis + youtube, channel, media, agent, automation, rea |
| `.env.cpu-free.example` | every variable, with secrets auto-filled by bootstrap |
| `bootstrap.sh` | Docker, firewall, clone, generated secrets, systemd |
| `universal-ai-backend.service` | brings the stack back after a reboot |

---

## Why 6 and not 7

Only `workers/voice_worker` needs a GPU — it is the sole image built on
`pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` (F5-TTS + MeloTTS). Every other
worker is plain `python:3.1x-slim` with pure-Python dependencies, which builds on
ARM64 unchanged. So voice is the one feature this box cannot serve, and the API
says so plainly:

```
GET /v1/voice/providers   -> provider state
POST /v1/voice/tts        -> 503 "voice worker is not configured"
```

That is honest behaviour, not a bug. Add a GPU host later and it lights up.

---

## Step 1 — Create the free instance (Oracle Cloud)

1. Sign in → **Compute → Instances → Create instance**.
2. **Image**: Canonical Ubuntu 22.04 (or 24.04), **aarch64**.
3. **Shape**: `VM.Standard.A1.Flex`. Always Free allows up to 4 OCPU / 24 GB —
   pick what the console offers; 2 OCPU / 12 GB is plenty for this stack.
4. **Boot volume**: 100-200 GB is fine and included.
5. Download the SSH key, create, wait for RUNNING, note the **public IP**.

## Step 2 — Open the port (Oracle needs TWO layers)

This is the step everyone misses.

**Layer 1 — the OCI Security List**
`Networking → Virtual Cloud Networks → your VCN → Security Lists → Default
Security List → Add Ingress Rule`: source `0.0.0.0/0`, protocol TCP,
destination port **8000**.

**Layer 2 — the instance's own iptables**
Handled by `bootstrap.sh` (Oracle images reject everything except 22 by default).

## Step 3 — Run the installer

```bash
ssh ubuntu@<your-vm-ip>
sudo bash <(curl -fsSL https://raw.githubusercontent.com/zeeburgers00-glitch/universal-ai-backend/main/deploy/cpu-free/bootstrap.sh)
```

It generates `REDIS_PASSWORD`, `BACKEND_API_KEY` and all six worker keys for you,
prints the backend key once, opens the firewall, builds, starts, waits for
`/health`, and installs the systemd unit.

## Step 4 — Verify

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/v1/runtime/capabilities | python3 -m json.tool
```

`ready_workers` should read `6`. Then open:

- `http://<your-vm-ip>:8000/app` — the Studio UI
- `http://<your-vm-ip>:8000/docs` — OpenAPI

Add one model provider key to `.env` (`GROQ_API_KEY` is free to start) and
`docker compose restart api` to turn chat on.

---

## Optional: voice on a free GPU host

Free GPU tiers cannot host a 24/7 public service, but they are fine for a
**voice-only** worker while you test. The API accepts a remote worker as long as
the URL is **HTTPS** (`http://` is only allowed for `127.0.0.1`).

```
[free CPU VM]  API ──HTTPS──► [Lightning AI studio] voice_worker :8100
```

### On Lightning AI

1. Sign up at lightning.ai (no card; phone verification).
2. Create a **Studio**, GPU: **T4** (16 GB is enough for MeloTTS; F5-TTS is
   happier on 24 GB — L4/A10G if your free hours allow).
3. In the studio terminal:

```bash
git clone https://github.com/zeeburgers00-glitch/universal-ai-backend.git
cd universal-ai-backend/workers/voice_worker
pip install -r requirements.txt          # pulls torch + f5-tts; several GB
export VOICE_WORKER_API_KEY='same-secret-as-your-vm'
uvicorn voice_worker.app:app --host 0.0.0.0 --port 8100
```

4. Expose port **8100** publicly from the Studio UI (Lightning gives you an
   `https://…lightning.ai` style URL). Ports exposed this way are HTTPS.

### Back on the free VM

```bash
cd /opt/universal-ai-backend/deploy/cpu-free
nano .env      # set both lines, no quotes
#   VOICE_WORKER_URL=https://<your-lightning-https-url>
#   VOICE_WORKER_API_KEY=same-secret-as-above
docker compose restart api
curl -s http://127.0.0.1:8000/v1/workers/status | python3 -m json.tool
```

`voice` flips to `configured`. Keep `WORKER_ALLOW_INSECURE_HTTP` untouched — it
exists only for the loopback workers.

> Free GPU studios stop when you close them, so treat voice as **best-effort**.
> For dependable TTS, put `voice_worker` on the hourly GPU host in
> `../runpod/` and point `VOICE_WORKER_URL` there instead.

---

## Operational notes

- **RAM**: workers are capped (api 1 GB, media 768 MB, others 384-512 MB). The
  whole stack idles well under 3 GB.
- **Celery**: only the HTTP worker APIs are started. The API reaches workers over
  HTTP, so `POST /v1/voice/tts`-style routes work; background Celery queues are
  optional and skipped to save memory.
- **Data**: `DATA_DIR` on the boot volume, so renders survive restarts.
- **Logs**: `docker compose logs -f api`. Compose rotates nothing by default —
  if disk fills, `docker system prune -f`.
- **Updates**: `cd /opt/universal-ai-backend && git pull && cd deploy/cpu-free &&
  docker compose up -d --build`.
- **Cost**: $0. Oracle quietly halved the Ampere A1 Always Free allowance in mid
  2026, so confirm the shape on the create screen rather than trusting blog posts.

## What still needs a paid/real host

| Capability | Needs |
|---|---|
| Voice, TTS and cloning | GPU (`../runpod/`) |
| Windows desktop actions | a Windows machine running `workers/windows_agent` |
| Heavy video rendering | more CPU/RAM than the free shape |
