# Backends + Features — poori list (verified)

Aakhri verification: **135 tests pass, 0 fail**. Har backend ko sirf import nahi kiya — asli
`uvicorn` par chalaya, `/health` maanga, bina key ke protected route par 401/403 confirm kiya,
aur **asli job** chala kar output file bhi banai (Section 3 dekho).

---

## 1. Kitne backend hain?

| # | Backend | Port | Routes | Kaam |
|---|---------|------|--------|------|
| 1 | **api** (control plane, `app/`) | 8000 | **87** | Command center, catalog, agents, vault, AI router — sab kuch yahan se |
| 2 | `voice_worker` | 8100 | 7 | TTS, voice clone, providers, results |
| 3 | `youtube_worker` | 8200 | 3 | YouTube upload/publish |
| 4 | `channel_worker` | 8300 | 2 | 37 channels par action |
| 5 | `media_worker` | 8400 | 6 | Upload, media jobs, Pexels stock, render |
| 6 | `agent_worker` | 8500 | 3 | 42 agents chalana |
| 7 | `automation_worker` | 8600 | 3 | 28 workflows chalana |
| 8 | `rea_worker` | 8700 | 3 | 229 REA tools se inspect |
| 9 | `windows_agent` | host | 5 | Desktop actions + REA jobs (sirf Windows) |
| 10 | `autopilot_worker` | — | Celery | Background consumer, koi port nahi |

**Total: 10 services.** Control plane ke andar 12 worker *slots* hain, 9 ke worker shipped.

---

## 2. Is round me kya fix hua (ye pehle toota hua tha)

1. **`media_worker` boot hi nahi hota tha** — `python-multipart` missing tha, par uske upload
   routes multipart use karte hain. Ab dependency me hai.
2. **`autopilot_worker` kahin deploy hi nahi hota tha** — dono compose stacks me add kiya.
3. **`.env` kabhi load nahi hoti thi** — `python-dotenv` dependency thi par kahin `load_dotenv`
   call nahi tha. Local `uvicorn` par aap keys bharte to app unhe **ignore** kar deta. Ab
   `app/config.py` import par load karta hai; asli env vars (Docker/Vercel) hamesha jeette hain.
4. **Broker down par workers 500 dete the** — ab saaf **503**:
   `"Task queue unavailable: cannot reach the Redis broker..."` (6 workers me fix).
5. **FFmpeg sirf apt se milta tha** — local `.venv` me render fail hota tha. Ab system binary na
   ho to pip-bundled `imageio-ffmpeg` use hota hai. **Matlab bina root, bina apt, render chalta hai.**
6. **`/v1/command` typo chup-chaap ignore karta tha** — `duration_seconds` bhejne par 60s video
   banta tha (sahi field `scene_seconds` hai). Ab unknown field = **422** with clear error.
7. **5 purane test fail the** (brittle assertions + drift) — theek kar diye.
8. **Naya smoke suite** — `tests/test_all_backends_smoke.py` (16 tests) + `tests/test_config_env.py`.

---

## 3. Asli proof — jo maine chala kar dekha ($0, koi API key nahi)

### a) Ek command se poori video
```
POST /v1/command {"command": "3 tips for a small shop in Pakistan"}
→ 202 job, ~60s me complete
→ data/command/output/cmd-*.mp4
```
Output check: **1920×1080, H.264, 60.0s, AAC audio track, 3.3 MB** — template script + captions +
timeline + render, sab local. AI script/TTS ke bina bhi **valid video** banti hai.

### b) media_worker asli job
Real HTTP upload (`multipart`) → asset → task:
| Task | Result |
|---|---|
| `thumbnail` | ✅ JPG 8.9 KB |
| `render` | ✅ MP4 144 KB |
| `audio` (extract) | ✅ MP3 49 KB |

### c) Har worker par auth + health
`/health` → 200. Protected route bina key → **401/403**. Broker band ho → **503** (pehle 500).

---

## 3.5 Naya: model catalog + GitHub tool registry

- **`catalog/models.json`** — OpenAI / Gemini / Groq ke latest models (ID, kind, capabilities,
  status, free-tier, confidence). Endpoints: `/v1/ai/models`, `/v1/ai/models?capability=image-out`,
  `/v1/ai/models/resolve?capability=vision`, `/v1/ai/models/stats`. Detail: `docs/MODELS.md`.
- **`catalog/github_repos.json`** — **196 verified repos**, GitHub API se generate, 19 categories
  (agents, mcp, voice, video, whatsapp, comfyui...). Endpoints: `/v1/discover/github/registry`
  (+ `/stats`, `/{owner}/{repo}`). Detail: `docs/GITHUB_TOOL_REGISTRY.md`.
- **Fixed:** `gemini-2.0-flash` default dead tha (Google ne June 2026 me band kiya) → ab
  `gemini-3.8-flash`.

## 3.4a Naya: backup / restore

`/v1/data/manifest|backup|backups|restore|verify|download` — poora data dir ek tar.gz me,
restore se pehle auto-snapshot, path-traversal wale archives refuse. Detail: `docs/DATA_BACKUP.md`.

## 3.4b Naya: metrics + rate limiting

`/metrics` (Prometheus text) + per-key sliding-window rate limit (default 600/min, `/health`
aur `/metrics` exempt). Koi external service nahi. Detail: `docs/OBSERVABILITY.md`.

## 3.5a Naya: job queue (SQLite, Redis ke bina)

`/v1/jobs/*` — durable async jobs (video ops built-in). Redis ki zarurat khatam, restart ke
baad bhi jobs bache rehte hain. Detail: `docs/JOB_QUEUE.md`.

## 3.5b Naya: video toolkit (FFmpeg, zero keys)

`/v1/video/*` — probe, **silence cut**, **auto-chapters**, thumbnail set, loudnorm (−14 LUFS),
vertical clip (9:16 / 1:1 / 4:5), SRT↔VTT. Sab local FFmpeg, koi key nahi. Detail: `docs/VIDEO_TOOLKIT.md`.

## 3.6 Naya: AI editor + code assistant (zero keys)

**`GET /editor`** — backend-served poora code editor (21 KB single HTML, zero CDN/npm):
file tree, line numbers, Ctrl+S save with `.bak`, outline jump, static review, test
scaffold, plan, coloured diff, aur optional local-model chat.

## 3.7 Code assistant (Cursor-style, zero keys)

`/v1/code/*` — index (252 files / 1,203 symbols in 246 ms), search, outline, diff,
safe apply (dry-run + `.bak`), static review, test scaffolding, commit-message draft,
rules files, multi-step plan. Koi model call nahi → koi key/limit nahi.
Detail: `docs/CODE_ASSISTANT.md`.

## 4. Features jo aap use kar sakte hain

### Command Center — ek prompt se video
`POST /v1/command` → script → voice → visuals → captions → **logo overlay** → SEO → MP4.
Fields: `command`, `render`, `scene_seconds`, `fps`, `captions`, `image_paths`, `grade`,
`caption_style`, `logo_path`, `seo`, `avatar`.
- `GET /v1/command/{job_id}` — progress (`stage`, `progress`)
- `GET /v1/command/capabilities` — abhi kya ready hai, kya missing

### AI Router — 48 providers
`/v1/ai/providers`, `/v1/ai/health`, `/v1/models/providers`, `/v1/chat/completions`
OpenAI-compatible, fallback chain, key masking. Groq/Gemini/OpenRouter free tier → **$0**.

### Catalog / Explorer / Studio
**6,122 tools**, **89 categories** (llm-runtime 80, llm-gateways 37, agents 35, mcp-integrations 16).
`/v1/catalog/stats`, `/v1/discover/*`, `/v1/tools*`, `/v1/skills`, `/studio`, `/explorer`.

### Agents — 42 agents, 17 fleet roles, 120 slots
`/v1/agents`, `/v1/agent-fleet`, `agent_worker` → `POST /v1/agents/run`

### Workflows — 28 workflows
`automation_worker` → `POST /v1/workflows/run`; `autopilot_worker` background tasks

### Channels — 37 catalog
`/v1/channels`, `channel_worker` ⚠️ connectors abhi `manifest_only` (Section 6)

### YouTube — `POST /v1/youtube/publish` (free OAuth)

### Voice — TTS, clone, providers
`voice_worker`; **clone ke liye GPU** → Modal free $30/mo credits (`deploy/modal/`)

### Media — upload, render, stock
`media_worker` + Pexels free key; render/thumbnail/audio **bina key chalte hain**

### Desktop / REA — Windows only
`windows_agent` + **229 REA tools**

### Vault / Campaigns / Integrations
`/v1/vault/*` (Supabase), client campaigns (`do_not_contact` guard), base44 + metricool

---

## 5. $0 kya hai, paisa kahan lagega

**Bina kisi key ke (verified, aaj):**
- Poora video render (1080p MP4), captions, thumbnail, audio extract
- Saare catalogs, capabilities, studio/explorer UI
- Sab workers boot + health

**Free tier (key chahiye, paisa nahi):**
- AI script/SEO → Groq / Gemini free
- Pexels stock → free key
- YouTube upload → free OAuth
- Vault/tasks → Supabase free
- Voice clone → Modal $30/mo credits

**Paid:** heavy render volume, bulk TTS minutes, 4K, high concurrency, image/video generation
(ComfyUI GPU).

---

## 6. Jo abhi wired nahi hai (seedhi baat)

| Cheez | Status |
|---|---|
| `openvoice` / `plugins` / `mail` / `finance` slots | Worker nahi — sirf slot |
| `channel_worker` connectors | `manifest_only` — catalog hai, live publish nahi |
| `windows_agent` | Sirf Windows host (Linux container me nahi) |
| `POST /v1/chat/tasks` | Supabase ke bina **503** |
| Image/video generation from prompt | `COMFYUI_BASE_URL` chahiye (GPU). Render/thumbnail ko nahi chahiye |
| MediaMTX / RTMP live | Default stack me nahi |
| Celery jobs (async queue) | Redis chahiye — warna 503 (ab saaf message) |

---

## 7. Chalane ke tareeke

```bash
# A) Sab kuch docker me (api + 8 workers + redis)
cd deploy/cpu-free && cp .env.cpu-free.example .env && docker compose up -d --build
# GPU voice ke saath:
cd deploy/runpod && cp .env.runpod.example .env && docker compose up -d --build

# B) Sirf control plane, local
cp .env.example .env      # keys bharo -- ab ye sach me load hoti hai
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# C) Ek worker alag se (workers/ root PYTHONPATH par hona chahiye)
PYTHONPATH=workers CELERY_BROKER_URL=redis://localhost:6379/2 \
  MEDIA_WORKER_API_KEY=dev .venv/bin/python -m uvicorn media_worker.app:app --port 8400

# Redis nahi hai? Bas render chahiye? Task seedha chalao:
PYTHONPATH=workers MEDIA_DATA_ROOT=/tmp/md .venv/bin/python -c "
from media_worker import tasks; print(tasks.process_media.apply(kwargs={'payload':{'task_type':'thumbnail','inputs':{'source_asset_id':'asset-...','timestamp_seconds':1},'user_approved':True,'task_id':'t1'}}).result)"
```

Test:
```bash
.venv/bin/python -m pytest -q                                  # 135 passed
.venv/bin/python -m pytest tests/test_all_backends_smoke.py -q  # 16 passed
```
