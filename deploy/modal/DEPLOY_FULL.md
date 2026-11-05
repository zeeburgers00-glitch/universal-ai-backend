# Poora backend Modal par deploy karna (free GPU)

**Modal kyun:** HTTPS URL native milta hai (gateway plain http reject karta hai), idle par
containers band ho jate hain (cost $0), aur free plan me **$30/month compute** milta hai —
T4 GPU par ~50 ghante. Card ki zarurat nahi.

**NOT VERIFIED LIVE — Khulasa (honest):** maine ye kit likhi hai aur har service ke module/import ko locally verify
kia hai, par **sandbox se modal.com reachable nahi hai** (network block) — is liye live deploy
maine nahi chala kar dikhaya. Neeche ke 4 command aap ko chalane honge.

---

## 1. Ek baar ka setup

```bash
pip install modal
modal token new                # browser me login (free account banao)
```

## 2. Secrets (keys ek jagah)

```bash
modal secret create uai-backend \
  BACKEND_API_KEY="$(openssl rand -hex 24)" \
  MEDIA_WORKER_API_KEY="$(openssl rand -hex 24)" \
  VOICE_WORKER_API_KEY="$(openssl rand -hex 24)" \
  YOUTUBE_WORKER_API_KEY="$(openssl rand -hex 24)" \
  CHANNEL_WORKER_API_KEY="$(openssl rand -hex 24)" \
  AGENT_WORKER_API_KEY="$(openssl rand -hex 24)" \
  AUTOMATION_WORKER_API_KEY="$(openssl rand -hex 24)" \
  REA_WORKER_API_KEY="$(openssl rand -hex 24)"
```

AI keys baad me add karni ho to dobara `modal secret create` chalao (same naam par update hota hai),
ya dashboard se edit karo: `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `PEXELS_API_KEY`,
`YOUTUBE_*` OAuth values.

## 3. Deploy

```bash
modal deploy deploy/modal/full_stack.py
```

Output me har service ka URL aayega, jaise:

```
api         → https://<workspace>--uai-api.modal.run
voice (T4)  → https://<workspace>--uai-voice.modal.run
media       → https://<workspace>--uai-media.modal.run
youtube / channel / agent / automation / rea → ...--uai-<name>.modal.run
```

## 4. Verify karo

```bash
python deploy/modal/smoke.py --api https://<workspace>--uai-api.modal.run
```

Sab `/health` par 200 chahiye. Pehli hit par cold start ~30–60s le sakta hai.

Fir control plane ko workers ke bare me batao (apne `.env` / secret me):

```
VOICE_WORKER_URL=https://<workspace>--uai-voice.modal.run
MEDIA_WORKER_URL=https://<workspace>--uai-media.modal.run
...
```

## 5. Ek video render (GPU par, bina server warm rakhe)

```bash
modal run deploy/modal/full_stack.py::render_command --command "3 tips for small shop" --scene-seconds 2
# phir file nikalo:
modal volume get uai-renders <job_id>.mp4 .
```

Ye wahi code path use karta hai jo API use karti hai (`/v1/command`), is liye drift nahi hota.
Local verification: is path se **6 MB, 1080p MP4** bana (86 second me).

---

## Kya deploy hota hai / kya nahi

| Service | Deploy | Note |
|---|---|---|
| `api` (control plane) | ✅ CPU | 87 routes |
| `voice` | ✅ **T4 GPU** | TTS + cloning |
| `media` | ✅ CPU | ffmpeg render/thumbnail/audio |
| `youtube`, `channel`, `agent`, `automation`, `rea` | ✅ CPU | Celery enqueue ke liye container ke andar redis-server start hota hai |
| `windows_agent` | ❌ | Windows machine chahiye |
| `autopilot_worker` | ❌ | Celery consumer (port nahi) — Modal request-scoped hai; iske liye chhota always-on box ya Upstash Redis chahiye |

## Cost (free credits ke andar rehne ke liye)

- `scaledown_window` chhota rakha hai; `min_containers` **jaan bujh kar nahi** lagaya (warna 24/7 bill)
- GPU sirf `voice` par, `T4` — `gpu="any"` kabhi nahi (H100 ~$3.95/hr par land kar sakta hai)
- Idle stack = **$0**. $30/month free credits ~50 ghante T4 ke barabar.
- Credits **roll over nahi hote** — mahine ke end me khatam ho jate hain.

## Troubleshooting

| Problem | Wajah / hal |
|---|---|
| `Secret 'uai-backend' not found` | Step 2 dobara chalao |
| worker par 503 `Task queue unavailable` | Container me redis start nahi hua — `UAI_START_REDIS=0` set hai? |
| 401 har route par | `BACKEND_API_KEY` secret me set hai; request me `X-API-Key` bhejo |
| cold start slow | normal — 30–60s pehli hit |
| `render_command` timeout | `--scene-seconds` kam karo ya `wait_seconds` barhao |
