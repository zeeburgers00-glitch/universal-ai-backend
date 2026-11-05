# What can still be added

A grounded menu. Every item below was checked against what the repo already has
(**157 OpenAPI paths, 164 operations, 40 runtime agents, 445 tests, `jarvis.py`, 7 workers,
Next studio app, Vercel + Render configs**), so nothing here duplicates existing work.

Effort is measured in agent turns, not calendar time:

| Size | Meaning |
|---|---|
| **S** | one focused change, tests in the same commit |
| **M** | a few dependent pieces (store + route + tests + docs) |
| **L** | needs a decision from you first (credentials, ToS, or a product choice) |

Cost column is the honest one: **free** = no key, no signup, runs in the same container.

---

## 1. Assistant layer — `app/jarvis.py` today is rules + BM25

| # | Addition | What you get | Size | Cost |
|---|---|---|---|---|
| 1 | **Tool belt wiring** (`app/toolbelt.py`) | The 65 tools from `prompts/free_toolbelt.json` become actually callable: registry, runtime availability, `/v1/tools` list + run. JARVIS picks by BM25 instead of 28 hard-coded intents | M | free |
| 2 | **Voice loop** (faster-whisper + piper) | `POST /v1/jarvis/voice` takes audio, replies with audio. Fully local, CPU works | M | free |
| 3 | **Streaming chat** (SSE) | Tokens arrive as they generate; cancel mid-answer. Removes the 60s synchronous Ollama wait feeling | S | free |
| 4 | **Semantic memory** | Hybrid BM25 + local embeddings (`sentence-transformers` or Ollama `nomic-embed-text`), stored in SQLite. "kal wali baat" type recalls start working | M | free |
| 5 | **Heartbeat / scheduler** | Named recurring goals ("9am: aaj ka plan", "Monday: weekly report") fired by the existing worker process, results in history | M | free |
| 6 | **Planner-critic loop** | Plan → execute → self-check → retry once if a step's output looks empty. Catches half-done answers before they reach you | M | free |
| 7 | **Guardrails** | PII redaction in memory, prompt-injection scan on tool output, per-session tool-call cap | S | free |
| 8 | **Approval gate** | Destructive/send/upload tools need `confirm: true` + token; everything else runs | S | free |

## 2. Media engine — ffmpeg is already the bottleneck

| # | Addition | What you get | Size | Cost |
|---|---|---|---|---|
| 9 | **Auto captions** | Whisper transcript → SRT → burned-in or soft subs on any video | S | free |
| 10 | **Shorts cutter** | Scene/silence detection, 9:16 reframe, top-N clips from one long video | M | free |
| 11 | **Thumbnail studio** | Keyframe pick + text overlay + 4 variants with a title-length check | S | free |
| 12 | **Podcast pack** | Transcript, chapters, show notes, RSS feed XML for any audio | S | free |
| 13 | **Local b-roll index** | Index a folder of clips by caption/embedding so the editor can suggest cutaways | M | free |

## 3. Publishing — the part that is blocked without your accounts

| # | Addition | What you get | Size | Cost |
|---|---|---|---|---|
| 14 | **YouTube upload** | OAuth device flow + resumable upload + scheduled publish, using `services/youtube-api` | M | free key, your channel |
| 15 | **Crosspost metadata** | One video → title/description/tags/hashtags per platform, stored with the job | S | free |
| 16 | **Content calendar** | Queue with idempotency, status per slot, ICS export | S-M | free |

## 4. Data and intelligence

| # | Addition | What you get | Size | Cost |
|---|---|---|---|---|
| 17 | **Semantic search over catalog** | 205 repos + docs searchable by meaning, not substring | M | free |
| 18 | **Analytics ingest** | YouTube CSV/API pull → weekly report (views, retention, best slot) | M | needs channel access |
| 19 | **Read-only SQL playground** | `POST /v1/data/query` over the local SQLite stores with a write blocker | S | free |
| 20 | **Fact graph** | Memory facts → entities and relations, "Ali ke projects" becomes a query | M | free |

## 5. Platform, ops, quality

| # | Addition | What you get | Size | Cost |
|---|---|---|---|---|
| 21 | **API key scopes** | `read` / `write` / `admin` per key, enforced per route. Today one key = everything | M | free |
| 22 | **Rate limit + budget ledger** | Requests/minute per key, persisted spend counters, 429 with retry-after | S | free |
| 23 | **`/metrics`** | Prometheus counters for routes, tool runs, queue depth, latency | S | free |
| 24 | **Schema migrations** | `schema_version` table + ordered migrations for `jarvis.db` and friends; today it is `CREATE TABLE IF NOT EXISTS` | M | free |
| 25 | **Typed client for studio** | OpenAPI → generated TS types, studio talks to real shapes instead of `any` | M | free |
| 26 | **One-script smoke** | `scripts/smoke.py` hits a running server end-to-end, prints pass/fail table. Replaces my manual curl chains | S | free |
| 27 | **Backup covers new stores** | Extend `backup.py` to `jarvis.db` + uploads, one restore command | S | free |
| 28 | **Webhook receiver** | Signed GitHub/Telegram webhooks → agent jobs, replay protection | S-M | free |

## 6. Business layer

| # | Addition | What you get | Size | Cost |
|---|---|---|---|---|
| 29 | **Quote/invoice PDF** | From finance ledger rows to a sendable PDF, GST-style fields optional | S | free |
| 30 | **CRM-lite** | Contacts with dedupe, last touch, next action; feeds client campaigns | M | free |

---

## Honestly not available here

| Ask | Why not |
|---|---|
| Real posting to Instagram/TikTok | Needs app review + OAuth per platform; ToS risk automated posting |
| Cloud GPU rendering | No GPU in this sandbox, no paid host |
| Paid model calls | Your standing rule: free keys only, honest `unavailable:` otherwise |
| Something that "just deploys" to Vercel | Free plan limit already hit (402); no `workflows` permission either |
| Silent web scraping at volume | Network from this sandbox is blocked; and it is a ToS grey zone |

## If you only pick three

1. **#1 tool belt** — turns JARVIS from 28 intents into 65 real capabilities.
2. **#4 + #3 semantic memory and streaming** — the two things that make it feel alive.
3. **#9 + #10 captions and shorts** — the fastest path from "video file" to "postable clip".
