# Free GPU for voice, using Kaggle

Kaggle is the only free tier that hands you a **real GPU without a credit card**:
T4 ×2 (16 GB each) or P100, ~30 hours/week, 12-hour sessions.

It also has the two limitations that decide the architecture:

| Limitation | Consequence |
|---|---|
| No public inbound port / no static IP | The worker must be pushed out through a **tunnel** to get an HTTPS URL |
| Session dies at 12 h (and ~20 min idle) | This is **best-effort testing**, not a production worker |

Because the API accepts a remote worker only over **HTTPS** (plain `http://` is
allowed for `127.0.0.1` only), the tunnel is not optional — it is what makes the
URL acceptable to `app/task_gateway.py`.

```
[Kaggle notebook]  voice_worker :8100
                          │
                   cloudflared quick tunnel
                          │
        https://<random>.trycloudflare.com
                          │
[Oracle free VM]   API ───┘   VOICE_WORKER_URL=https://…
```

---

## Step 1 — Notebook setup

1. kaggle.com → **Create → Notebook**.
2. Right sidebar → **Settings**:
   - **Accelerator: GPU T4 ×2**
   - **Internet: On** ← required, the script downloads packages and cloudflared
3. Add the script to a cell:

```python
!curl -fsSL https://raw.githubusercontent.com/zeeburgers00-glitch/universal-ai-backend/main/deploy/kaggle/run_voice_worker.py -o run_voice_worker.py
!python run_voice_worker.py
```

Or upload `run_voice_worker.py` via **File → Upload** and run the second line.

## Step 2 — Wait (5-10 minutes, first run only)

The cell prints progress. Roughly:

```
GPU ready: Tesla T4 (15.6 GB)
Installing worker dependencies
Installing redis-server
Cloning the repository
Starting Celery worker
Starting Uvicorn API
Worker health check passed
Opening the HTTPS tunnel
```

Then a banner:

```
================================================================
  VOICE WORKER IS LIVE
================================================================
  Worker URL : https://something-random.trycloudflare.com
  Worker key : xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Keep the cell running.** If you stop it, everything dies and the URL changes
on the next run.

## Step 3 — Wire it to your backend

On the free CPU VM:

```bash
cd /opt/universal-ai-backend/deploy/cpu-free
nano .env

VOICE_WORKER_URL=https://something-random.trycloudflare.com
VOICE_WORKER_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxx

docker compose restart api
curl -s http://127.0.0.1:8000/v1/workers/status | python3 -m json.tool
```

`voice` should now read `"configured": true`. Test end to end:

```bash
curl -s http://127.0.0.1:8000/v1/voice/providers -H "X-API-Key: <BACKEND_API_KEY>"
```

## Step 4 — Generating speech

`POST /v1/voice/tts` queues a Celery task, so allow a few seconds and poll:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/voice/tts \
  -H "X-API-Key: <BACKEND_API_KEY>" -H "Content-Type: application/json" \
  -d '{"engine":"melo-tts","text":"Free GPU voice test.","speaker_consent_confirmed":true,"consent_record_id":"consent-demo-0001"}'

# then
curl -s http://127.0.0.1:8000/v1/voice/results/<task_id> -H "X-API-Key: <BACKEND_API_KEY>"
```

First synthesis is slow — F5-TTS downloads its pretrained weights on the first
call.

---

## Honest limitations

- **12-hour ceiling.** Kaggle ends the session. The tunnel URL dies with it and
  your API starts returning `503` for voice. That is visible and safe, but it is
  downtime.
- **Idle cutoff.** Kaggle suspends notebooks after ~20 minutes without activity.
  The script logs every 10 minutes, which usually keeps it awake, but it is not a
  guarantee.
- **Quick tunnels are unauthenticated at the transport layer.** Anyone who learns
  the URL can reach the worker — but every route requires
  `Authorization: Bearer <VOICE_WORKER_API_KEY>`, and the key is randomly
  generated per run. Keep it secret and rotate by restarting the notebook.
- **Kaggle's terms** target interactive data-science work, not running public
  services. Use it for development and demos; move to a paid GPU host for
  anything users depend on.
- **No Docker on Kaggle**, so the worker runs from source here rather than from
  the image. The image build is handled separately by
  `.github/workflows/voice-worker-image.yml`.

## When to stop using Kaggle

Move to `deploy/modal/` for a managed HTTPS endpoint that scales to zero, or
`deploy/runpod/` (~$0.35-0.70/hour) for a persistent pod, as soon as anything
real depends on voice. Kaggle is a testing bench, not a host.

---

# JARVIS + the free tool belt on the same box

The section above hosts the **voice worker**. This one hosts the **whole API** — JARVIS,
the 65-tool free belt, and Claude — if you want a chat-able assistant instead of a worker.

Files: `jarvis_kaggle.py` (bootstrap) and `JARVIS_kaggle.ipynb` (same thing as a notebook).

```bash
git clone --depth 1 https://github.com/zeeburgers00-glitch/universal-ai-backend.git
cd universal-ai-backend
pip install -q -r requirements.txt
python deploy/kaggle/jarvis_kaggle.py --port 8000 --provider anthropic
```

Add two Kaggle secrets (Add-ons → Secrets): `ANTHROPIC_API_KEY` and `BACKEND_API_KEY`.
The script starts uvicorn, waits for `/health`, opens a `cloudflared` quick tunnel, and
prints the public URL plus ready-to-paste `curl` commands. Without a Claude key it still
runs: JARVIS answers in rules mode and says so, and the belt tools work unchanged.

| Constraint | Consequence for an assistant |
|---|---|
| 12-hour session, ~20 min idle timeout | Not an always-on assistant; a session per day |
| `/kaggle/working` wiped | JARVIS memory (SQLite) is temporary unless synced |
| Public tunnel URL | Protect it with `BACKEND_API_KEY`; the URL alone is not a secret |
| No inbound port | The tunnel is mandatory — nothing else can reach the box |

Full detail: `docs/KAGGLE_HOSTING.md`. For a local brain instead of Claude:
`ollama serve` + `--provider ollama` (see `docs/JARVIS_UPGRADE.md`).
