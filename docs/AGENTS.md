# Agents — jo asli me chalte hain

`catalog/agents.json` me **42 blueprints** hain, par wo sirf description hain — koi worker
service na ho to kuch execute nahi karte. Iske saath ek **runtime** hai jisme **37 agents**
is process ke andar chalte hain, **zero API key** ke saath.

| | Blueprints | Runtime |
|---|---|---|
| Kahan | `catalog/agents.json` | `app/agents.py` |
| Kitne | 42 | **37** |
| Chalte hain? | Nahi (worker chahiye) | **Haan, abhi** |
| Endpoints | `/v1/agents` | `/v1/agents/runtime/*` |
| Engine | — | ffmpeg, code index, rules, model |

## Endpoints

| Route | Kaam |
|---|---|
| `GET /v1/agents/runtime` | sab runnable agents (filter: `category`, `engine`) |
| `GET /v1/agents/runtime/{id}` | inputs, required fields, risk, engine |
| `POST /v1/agents/runtime/{id}/run` | abhi chalao, result wapas |
| `POST /v1/agents/runtime/{id}/submit` | queue me daalo (job `agent.run`) |
| `POST /v1/agents/runtime/crew/run` | kai agents chain me |
| `GET /v1/agents/runtime/blueprints` | 42 blueprints + kaunsa yahan chalta hai |
| `GET /v1/agents/runtime/runs/recent` | audit log se recent runs |

## Team (category-wise)

**code (10)** — repo-scout, code-reviewer, test-planner, refactor-planner, python-compiler,
changelog-writer, release-notes, import-auditor, route-guard, doc-writer

**video (8, ffmpeg)** — media-prober, video-editor (silence cut), chapter-writer,
thumbnail-designer, loudness-master, clip-maker (9:16), subtitle-smith, publish-packager

**ops (7)** — health-warden, backup-keeper, job-runner, metrics-reporter, audit-reader,
sdk-builder, capacity-planner

**content (6, rule-based)** — seo-planner, title-suggester, hashtag-smith,
description-writer, schedule-planner, brand-namer

**discovery (2)** — tool-scout (BM25 over 205 repos / 143 routes), api-cartographer

**model (4)** — summarizer, translator, copywriter, code-explainer
(model ke bina **422** + saaf message; Ollama free chalao to chal jayenge)

## Examples

```bash
KEY=...; H="X-API-Key: $KEY"; B=localhost:8000

# video se upload manifest banao
curl -s -X POST $B/v1/agents/runtime/publish-packager/run -H "$H" -H 'content-type: application/json' \
  -d '{"input":{"path":"renders/ep12.mp4","title":"Episode 12"}}'

# repo ki review + changelog ek chain me
curl -s -X POST $B/v1/agents/runtime/crew/run -H "$H" -H 'content-type: application/json' \
  -d '{"agents":["code-reviewer","changelog-writer"],"input":{"path":"app/"}}'

# lamba kaam queue me
curl -s -X POST $B/v1/agents/runtime/video-editor/submit -H "$H" -H 'content-type: application/json' \
  -d '{"input":{"path":"raw/talk.mp4"}}'
```

## Crew kaise chalta hai

Har agent ka result agle agent ko `context` ke roop me milta hai, aur simple scalar values
aage merge ho jate hain. Isliye `repo-scout → seo-planner` chain me dusra agent pehle ka
`total_files` dekh sakta hai.

## Sach (jo chhupaya nahi)

- **content agents rule-based hain** — titles/tags composing karte hain, keyword volume ya
  trend data nahi laate (wo paid API maangta hai). Response me `note` field ye likhta hai.
- **model agents** bina provider ke 422 dete hain — filler text nahi banate.
- `video-editor` audio-less file par **422** deta hai ("file has no audio track").
- Blueprints ke worker-service wale agents yahan nahi chalte; `blueprints` endpoint
  `runnable_here: false` dikhata hai.
- Har run audit log me `agent.run` ke roop me jata hai (key ka fingerprint, secret nahi).
