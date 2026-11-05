# Deploy: Vercel (serverless) ya Render (container)

Dono raaste is repo me ready hain. Farq sirf ek hai: **Vercel par ffmpeg + long jobs
par serverless limits lagti hain, Render par poora process chalta hai.**

## Vercel — ready

| File | Kaam |
|---|---|
| `api/index.py` | ASGI entry (`app`), data root `/tmp/uai-data`, workers off |
| `vercel.json` | 60s maxDuration, 1 GB memory, catch-all rewrite |
| `.vercelignore` | tests/docs/.venv hataata hai, `catalog/` rakhta hai |

Project already bana hua hai: **universal-ai-backend-api** (repo root se build hota hai).
Env vars set hain: `BACKEND_API_KEY`, `UAI_SERVERLESS=1`, `UAI_DATA_ROOT=/tmp/uai-data`,
`UAI_JOBS_DISABLE=1`.

Live URL shape: `https://universal-ai-backend-api.vercel.app/health`

### Vercel par kya kaam karega, kya nahi

| Kaam karega | Nahi karega |
|---|---|
| 141+ routes, editor (`/editor`), SDK (`/v1/sdk`), metrics | **Background job workers** (lambda me process nahi rehta) |
| video probe/chapters/thumbnails (chhoti files, 60s ke andar) | 10+ minute renders (60s function limit) |
| BM25 tool search, git panel, governance, audit | Persistent SQLite (har lambda me `/tmp` naya hota hai) |

Jobs chahiye to `POST /v1/jobs` + `POST /v1/jobs/run-once` (cron ya client tick) —
payload 60s ke andar khatam hona chahiye.

## Render — ready (recommended for real work)

`render.yaml` blueprint pehle se hai. Render par:

```bash
# Blueprint deploy (dashboard se ek click):
https://dashboard.render.com/blueprint/new?repo=https://github.com/zeeburgers00-glitch/universal-ai-backend
```

Ya manual Web Service:

| Setting | Value |
|---|---|
| Runtime | Python 3.11 |
| Build | `pip install -r requirements.txt` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health | `/health/deep` |
| Disk | mount `/data`, 1 GB (`UAI_DATA_ROOT=/data`) |

Render par: ffmpeg image ke andar (Dockerfile use karo), background workers chalte hain,
SQLite persist hoti hai, aur koi 60s cap nahi.

Dockerfile se deploy karna ho to: Build `docker build -t api .`, Start `docker run -p $PORT:8000 api`.
