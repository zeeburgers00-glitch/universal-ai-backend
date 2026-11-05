# GPU voice worker on Modal

Modal is the least-effort way to give the backend a GPU: you deploy a Python
file, it hands back an **HTTPS URL**, and you pay **per second with scale to
zero**. That matters here because only `workers/voice_worker` needs a GPU — the
other six workers are plain CPU images.

| | |
|---|---|
| Free tier | **$30 / month of compute**, resets monthly |
| T4 | ~$0.59/hr (16 GB — enough for MeloTTS and F5-TTS) |
| Idle cost | **$0** — containers scale to zero |
| Endpoint | HTTPS by default, no tunnel needed |

Why not a rented pod: the API only accepts a remote worker over **HTTPS**
(`http://` is allowed for `127.0.0.1` only). Rented pods expose `IP:port`, so you
would need a tunnel. Modal gives HTTPS for free.

---

## 1. One-time setup

```bash
pip install modal
modal token new                      # opens the browser, links this machine
```

Create the worker secret. Use a long random string — this is the same value the
backend will send as `Authorization: Bearer …`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # copy this

modal secret create voice-worker-secret VOICE_WORKER_API_KEY=<paste-the-value>
```

Deploying without this secret fails immediately rather than starting an
unauthenticated worker. That is intentional.

## 2. Deploy

```bash
modal deploy deploy/modal/modal_app.py
```

First build takes a few minutes (PyTorch + F5-TTS + MeloTTS ≈ 3 GB of image
layers). Modal caches layers, so later deploys are seconds.

You get a URL shaped like:

```
https://<your-workspace>--universal-ai-voice-worker-voice-api.modal.run
```

## 3. Pre-pull the model weights (recommended)

Without this, the first synthesis downloads several GB and may exceed the request
timeout:

```bash
modal run deploy/modal/modal_app.py::prewarm
```

Weights land on the `universal-ai-voice-data` volume, so every later container
reuses them.

## 4. Wire it into the backend

**Vercel / hosted backend** — project → Settings → Environment Variables:

```
VOICE_WORKER_URL=https://<your-workspace>--universal-ai-voice-worker-voice-api.modal.run
VOICE_WORKER_API_KEY=<the same secret you created>
```

**Self-hosted / docker** — add both lines to `deploy/cpu-free/.env` (or
`deploy/runpod/.env`) and restart the API.

Then:

```bash
curl -s http://127.0.0.1:8000/v1/workers/status        # voice -> configured
curl -s "$VOICE_WORKER_URL/health"                     # {"status":"ok"}
```

## 5. Prove it works

```bash
curl -s -H "Authorization: Bearer $VOICE_WORKER_API_KEY" \
  "$VOICE_WORKER_URL/v1/voice/providers" | python3 -m json.tool
```

A `401` means the key does not match the secret. A `503` means
`VOICE_WORKER_API_KEY` never reached the container — recreate the secret and
redeploy.

---

## Optional: thumbnail images

The same file also deploys a text-to-image endpoint on a T4:

```bash
curl -s -X POST "$THUMBNAIL_URL" -H "Content-Type: application/json" \
  -d '{"prompt": "tea garden at sunrise, cinematic, 35mm"}' \
  | python3 -c "import sys,json,base64; open('thumb.png','wb').write(base64.b64decode(json.load(sys.stdin)['image_base64']))"
```

`modal deploy` prints its URL (`…thumbnail.modal.run`). It runs Stable Diffusion
1.5 — **CreativeML OpenRAIL-M** licence: commercial use is allowed subject to
use-based restrictions you should read before shipping. `gpu="any"` is
deliberately not used anywhere in this kit: it can quietly pick an H100 at
~$3.95/hr instead of a T4 at ~$0.59/hr.

---

## Costs, honestly

| Usage | Monthly cost |
|---|---|
| Idle (nothing generated) | **$0** |
| 50 h of T4 (the whole free credit) | **$0** |
| 100 h of T4 | ~$59 − $30 credit ≈ **$29** |

Set `min_containers=1` only if you need a permanently warm worker — that removes
scale-to-zero and turns a $0 idle month into ~$430.

## Known limits

- **Scaling down loses in-flight jobs.** The worker queues Celery tasks in a
  Redis living inside the container. If the container scales down while a job is
  queued, that job is lost. `scaledown_window=300` keeps it warm for five minutes
  after the last request, which covers normal use. For guaranteed delivery, run
  the worker on a persistent GPU host (`deploy/runpod/`).
- **First request after a cold start is slow** while TTS weights load into VRAM.
  `prewarm` makes this much better but does not eliminate it.
- **T4 has 16 GB.** F5-TTS with long inputs can get tight; MeloTTS is
  comfortable. Use `gpu="A10G"` if you hit OOM on very long text.
- **Not tested from the deploy sandbox** — that environment cannot reach Modal.
  The file is validated for syntax, app registration and configuration, but the
  first real `modal deploy` runs on your machine.
