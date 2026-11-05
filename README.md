# Universal AI Backend

API-only backend for an existing app. It is designed as an extensible integration gateway and searchable catalog for AI models, agents, MCP servers, voice, image/video, search, RAG, coding assistants, and automation tools.

> **Honest scope:** no single backend can contain every current tool, and no one can enumerate future tools that do not exist yet. This project combines a curated starter catalog with live GitHub repository discovery and a documented adapter boundary. A catalog entry is a reference, not proof that the tool has been installed, tested, or securely integrated.

## Features

- FastAPI REST API with OpenAPI docs at `/docs` and built-in interactive web dashboard at `/explorer`.
- Global searchable AI & MCP catalog (`6,100+` unique open-source repositories, `1,760+` MCP servers/SDKs/gateways, LLMOps tools, voice/video/image/music models, and flagship commercial AI platforms across `85+` categories, plus `229` REA MCP reverse-engineering/AI-inspection tools); exact live counts are exposed by `GET /v1/catalog/stats`. Repository and platform references are metadata, not executed integrations.
- REA (`morluto/rea` / `rea-agents`) MCP catalog (`GET /v1/rea/status`, `GET /v1/rea/tools`) **plus** an isolated, approval-gated REA inspection worker (`workers/rea_worker` via `POST /v1/rea/inspect`).
- `48` configurable LLM & multimodal inference provider adapters (`GET /v1/models/providers`) including OpenAI, Anthropic, Google Gemini, xAI Grok, Groq, DeepSeek, Qwen/DashScope, Perplexity, Cohere, Moonshot/Kimi, Zhipu/GLM, MiniMax, NVIDIA NIM, OpenRouter, Together, Fireworks, Cerebras, Mistral, Azure OpenAI, Bedrock Gateway, Cloudflare AI, Ollama, vLLM, SGLang, TGI, TabbyAPI, KoboldCpp, Jan, LM Studio, and LiteLLM.
- Live GitHub discovery with `30` built-in AI category presets (`GET /v1/discover/categories`) and filters: `GET /v1/discover/github?category_preset=mcp-servers&license_filter=mit&min_stars=100&sort=stars`.
- API-key protection for chat, worker dispatches, and catalog writes.
- Vercel-compatible FastAPI entrypoint and unified Docker Compose stack (`workers/docker-compose.yml`) for GPU/async workers.
- Universal Agent Runtime (`/v1/agent-runtime`): SQLite-backed task queue, worker leases/heartbeats, retries, DAG workflows, approval gates, scoped memory and task event history; polling executor at `workers/agent_runtime`.
- Safe-by-default integration model: listing a repo never installs or executes its code. Agent runtime execution is disabled until the worker is explicitly attested as free/no-card; high/critical tasks require approval.



## Universal Agent Runtime

See [`docs/AGENT_RUNTIME.md`](docs/AGENT_RUNTIME.md) for API examples, worker setup, no-card attestation and storage durability notes. The runtime uses SQLite; on serverless hosts the default `/tmp` filesystem is ephemeral, so use a persistent mounted disk for durable queues and memory.

## Quick start (Windows PowerShell)

Requires Python 3.11+.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set BACKEND_API_KEY, AI_BASE_URL, AI_API_KEY
uvicorn app.main:app --reload --env-file .env
```

Open `http://127.0.0.1:8000/app` for the Studio UI, or `http://127.0.0.1:8000/docs` for the API reference.

## Environment variables

- `BACKEND_API_KEY`: long random secret required by protected endpoints. Do not put it in the frontend bundle.
- `AI_BASE_URL`: base URL ending at an OpenAI-compatible API root, e.g. `https://api.groq.com/openai/v1`.
- `AI_API_KEY`: server-side model provider key.
- `AI_DEFAULT_MODEL`: optional model used when the request omits a model.
- `GITHUB_TOKEN`: optional GitHub token to improve GitHub API rate limits for repository discovery.
- `CORS_ORIGINS`: comma-separated web origins; use your app's exact origin for production.

## API routes

- `GET /` — service metadata
- `GET /app` — **Universal AI Studio**, a dependency-free single-page app (catalog search, chat, providers, agents, workflows, discovery, finance) served from the same origin as the API
- `GET /explorer` — interactive web explorer across all AI tools, REA MCP tools, providers, blueprints, and live discovery
- `GET /health` — health check
- `GET /v1/tools?q=voice&category=audio-voice&min_stars=500&language=Python` — search the global AI & MCP registry
- Filter candidate license states with `license_status=review_required` or a partial `source_classification` value
- `GET /v1/tools/categories` — categories
- `GET /v1/catalog/stats` — live counts of entries/categories/license-review statuses and REA MCP manifests
- `GET /v1/catalog/sources` — catalog discovery sources and classification policy
- `GET /v1/rea/status` — REA (`morluto/rea`) MCP server metadata, setup commands, verification Evidence IDs, and responsible-use policy
- `GET /v1/rea/tools?ai_only=true` — search/filter REA's `229` MCP tools (`q`, `family`, `ai_only`, `read_only`, `destructive`)
- `POST /v1/rea/inspect` — dispatch bounded static REA inspection to isolated `rea_worker` (requires `X-API-Key`, `authorized_target_confirmed=true`, `user_approved=true`)
- `GET /v1/tools/{tool_id}` — one record
- `GET /v1/skills?q=browser` — searchable skills/tool references
- `GET /v1/providers` & `GET /v1/models/providers` — `48` provider configuration states (never returns secrets)
- `POST /v1/chat/completions` — multi-provider chat proxy (requires `X-API-Key`)
- `POST /v1/tools` — add catalog metadata (requires `X-API-Key`; does not install or execute code)
- `GET /v1/discover/categories` — `30` built-in global AI discovery presets and live catalog counts
- `GET /v1/discover/github?q=computer+use` or `GET /v1/discover/github?category_preset=mcp-servers` — find current GitHub repositories



### Example chat call

```powershell
$headers = @{ "X-API-Key" = "YOUR_BACKEND_API_KEY"; "Content-Type" = "application/json" }
$body = @{
  provider = "openai_compatible"
  model = "YOUR_MODEL"
  messages = @(@{ role = "user"; content = "Hello" })
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/chat/completions" -Headers $headers -Body $body
```

## Add the next tool safely

1. Search GitHub via `/v1/discover/github?q=your+capability`.
2. Review repository activity, maintainer, dependency tree, security posture, hardware needs, and upstream license.
3. Add a metadata record to `catalog/tools.json` or submit it to `POST /v1/tools`.
4. If actual execution is needed, implement a dedicated adapter under `app/`, add authentication and permission checks, tests, and explicit timeouts.
5. Never auto-install arbitrary GitHub code in a live server. Run untrusted integrations in a separate sandbox/worker and require approval for side effects such as file changes, computer control, account changes, publishing, or spending.

## Deployment on Vercel

1. Import this GitHub repository at https://vercel.com/new.
2. Let Vercel detect the FastAPI app (the entrypoint is configured in `pyproject.toml`).
3. Set `BACKEND_API_KEY`, `AI_BASE_URL`, `AI_API_KEY`, and `CORS_ORIGINS` in Vercel Project Settings → Environment Variables.
4. Optionally set `AI_DEFAULT_MODEL` and `GITHUB_TOKEN`.
5. Deploy, then test `/health`, `/docs`, and `/v1/tools`.

Do not add any secret to GitHub source files. A serverless filesystem and in-memory registration are not durable databases; use managed PostgreSQL/Supabase or another persistent store before relying on users registering tools in production.

## License and third-party projects

This backend's code and each linked integration have their own licenses and terms. A link in the catalog does not grant permission to bundle, host, or redistribute that project's code or models. Always check the upstream repository's current `LICENSE`, model license, and service terms before integration.

## Expanded catalog and license policy

The registry loads `catalog/tools.json`, `catalog/extended.json`, `catalog/commercial.json`, `catalog/llmops.json`, `catalog/voice_media.json`, `catalog/mcp_ecosystem.json`, and `catalog/global_ai_directory.json`, merging duplicate repository URLs while preserving stable IDs from the original seed catalog. REA's own MCP tool/prompt catalog is indexed separately in `catalog/rea_mcp_tools.json` and served via `/v1/rea/status` and `/v1/rea/tools`. The static catalog snapshots thousands of known open-source and commercial AI tools across `35+` categories, while `/v1/discover/github` provides live discovery over newly published repositories.

Many candidate rows are deliberately marked `license_status=review_required`. The catalog includes open-source candidates, commercial/SaaS AI platforms, and source-available/fair-code or mixed-license projects. Those classes are labeled separately when known. Do not treat source-available, an open-source SDK, model weights, and a vendor's hosted API as equivalent.

For the most current public GitHub metadata, use `/v1/discover/github` with filters or `category_preset`. The API may be rate-limited without `GITHUB_TOKEN`. A GitHub SPDX field is helpful metadata, not legal advice or proof that every dependency, model, dataset, or enterprise feature has the same license.

### Useful searches

```text
GET /v1/tools?category=mcp-servers
GET /v1/tools?min_stars=10000&language=Python
GET /v1/rea/status
GET /v1/rea/tools?ai_only=true
GET /v1/rea/tools?q=webmcp
GET /v1/discover/categories
GET /v1/discover/github?category_preset=ai-agents&min_stars=500
GET /v1/tools?q=license&license_status=review_required
GET /v1/catalog/stats
```



## Continuous AI tool discovery

A scheduled GitHub Actions workflow runs every six hours and opens/updates a pull request containing fresh AI repository candidates in `catalog/discovery_candidates.json`. It records metadata and licence identifiers only: it does not clone, install, import or execute third-party code. Candidates must pass a separate security/licence/dependency/test review before becoming executable integrations. This keeps discovery continuous without allowing arbitrary repositories to compromise the production backend.

## Provider and stock footage additions

See [provider and stock footage integration guide](docs/AUTOPILOT_PROVIDERS_AND_DISCOVERY.md). Added OpenAI-compatible adapters for Z.ai, HackerAI and OpenCode Zen, plus authenticated Pexels video search at `POST /v1/media/stock/pexels/search`. Pexels assets are returned with creator/source attribution metadata; actual rendering and publishing still require configured media and YouTube workers.


## Chat-first YouTube autopilot

The separate AutoTube frontend is a minimal chat interface; all agent catalogues, orchestration, tool integrations and worker execution remain in the backend. The browser calls a Vercel server-side proxy so `BACKEND_API_KEY` is not exposed to the client.

- `GET /v1/agent-fleet` — 17 YouTube specialist role families and 120 on-demand role slots.
- `POST /v1/chat/tasks` — queue a durable chat task (requires Supabase, Redis/Celery, and a configured AI provider).
- `GET /v1/chat/tasks/{task_id}` — run status and activity events.
- `GET /v1/chat/tasks/{task_id}/events` — task activity stream snapshot.
- `workers/autopilot_worker` — durable Celery worker that dispatches specialist model calls and persists progress events.
- `catalog/youtube_agent_fleet.json` — role/capacity definitions. Slots are templates, not permanently running processes.
- `GET /v1/integrations/metricool/status`, `/brands`, `/youtube/categories`, and `/scheduled-posts` — Metricool brand and planning integration; `POST /v1/integrations/metricool/schedule-youtube` schedules a Metricool-uploaded video/Short after explicit approval.

See [chat-first architecture and deployment requirements](docs/CHAT_FIRST_ARCHITECTURE.md). The chat task engine can generate and review content briefs; actual stock footage downloading, TTS, video rendering and YouTube publishing still require the corresponding configured workers. It must not display those stages as completed unless a worker returns a successful result.


## Multi-business AI Earning Empire

The earning fleet extends the on-demand agent architecture beyond YouTube. It provides **120 role templates across 12 departments**: YouTube, freelancing, content agency, affiliate marketing, AI SaaS, e-commerce, sales, research, media production, operations, finance, and quality/risk.

- `GET /v1/earning/fleet` — fleet summary and department capacities.
- `GET /v1/earning/departments` — department missions and skills.
- `GET /v1/earning/agents?department=freelance` — searchable agent blueprints.
- `GET /v1/earning/workflows` — business workflow templates.
- `POST /v1/earning/plan` — send a planning-only objective to the configured agent worker (requires `X-API-Key`).
- `POST /v1/earning/agents/{agent_id}/run` — dispatch a selected agent to the configured agent worker (requires `X-API-Key`).

Configure `AGENT_WORKER_URL` and `AGENT_WORKER_API_KEY` (or enable the supported built-in cloud runtime) to execute agent jobs. The fleet is a set of blueprints, not 120 continuously running agents. Start with a small worker concurrency and increase only after measuring latency, provider limits, and cost.

The default budget target is USD 100/month. This is a planning target, **not an automatic billing cap**: set hard spending limits and alerts at each model/provider account, monitor usage, and keep paid external actions behind approval. Agents may draft and analyze autonomously; sending messages, publishing, purchases, payments, account changes, and other consequential actions require separate explicit approval. Revenue is never assumed: only verified payment records count as income.



## Plugin hub, QA inboxes, and monetization

- `GET /v1/business/plugins` lists reviewed connector metadata. A catalog listing does not mean a plugin is connected.
- `POST /v1/business/plugins/{plugin_id}/actions` dispatches approved connector actions to the configured plugin worker. Configure `PLUGIN_WORKER_URL` and `PLUGIN_WORKER_API_KEY`; store provider credentials server-side and use least-privilege scopes.
- `POST /v1/business/testing/inboxes` and `POST /v1/business/testing/inboxes/read` use a separately configured Mailpit-compatible QA worker (`MAIL_WORKER_URL`, `MAIL_WORKER_API_KEY`). These temporary inboxes are restricted to authorized QA/staging; they must not be used for mass signups or bypassing third-party account verification.
- `GET /v1/business/monetization` lists ad, affiliate, sponsorship, agency, and SaaS income streams.
- `POST /v1/business/monetization/reports` sends provider statements, verified payments, or estimates to the finance worker (`FINANCE_WORKER_URL`, `FINANCE_WORKER_API_KEY`). Estimates are not recognized as realized revenue.
- `GET /v1/business/monetization/policy` returns ad and affiliate compliance rules.

Ad revenue workflows focus on eligibility, original content, real audiences, policy review, and provider reporting. Automated clicks, refreshes, incentivized ad interactions, fake traffic, and impression manipulation are prohibited. Provider account approval and monetization eligibility are not guaranteed by this software.


## OpenAvatar Studio (no-card-first video/avatar pipeline)

OpenAvatar Studio adds a separate worker-based avatar/video job control plane. It is
designed for free-tier/no-card infrastructure and has no paid GPU provider or paid
fallback. It includes authenticated uploads, job queue/leases, quota tracking, worker
heartbeats, artifacts, and conservative model-license metadata.

- GET /v1/openavatar/status, /providers, /models, and authenticated /quota
- POST /v1/openavatar/assets and /jobs; job status and artifact downloads
- Worker endpoints under /internal/openavatar/*, protected by a dedicated worker token
- Hugging Face ZeroGPU Gradio worker: workers/openavatar/huggingface/
- Optional manual Kaggle and Lightning workers: workers/openavatar/kaggle/ and
  workers/openavatar/lightning/
- Local CPU worker for OpenVoice adapter, whisper.cpp and FFmpeg: workers/openavatar/local_cpu/
- Implementation and setup: docs/OPENAVATAR_STUDIO.md
- Model license review: catalog/openavatar_models.json and
  docs/OPENAVATAR_MODEL_LICENSES.md

The default Hugging Face local quota guard is 270 seconds/day and 60 seconds/job; the
provider's actual quota remains authoritative. Kaggle is enforced as
personal/non-commercial only. Lightning is disabled until the user explicitly confirms
no-card/free-credit-only eligibility. The default SQLite data directory is ephemeral;
configure persistent storage before relying on jobs in production. Commercial rendering
is blocked until all selected code, checkpoints, dependencies, datasets and assets have
been reviewed.


### OpenAvatar Studio AI agent fleet

OpenAvatar includes 120 task-scoped specialist agents across 12 departments and 12
prebuilt production workflows. Browse with GET /v1/openavatar/agents and
GET /v1/openavatar/workflows; plan a production job with POST /v1/openavatar/plan;
dispatch an individual role with POST /v1/openavatar/agents/{agent_id}/run, or selected
teams of up to 120 with POST /v1/openavatar/teams/run.

The fleet reuses the existing authenticated AGENT_WORKER_URL. Agent execution stays
disabled until OPENAVATAR_AGENT_WORKER_NO_CARD_CONFIRMED=true is explicitly set after
checking that the configured worker is genuinely no-card/free-only. Team concurrency
defaults to 5 and is capped at 20. Role definitions are blueprints, not continuously
running agents; worker acceptance is not completion. High-risk/critical tasks require
approval, and the model/license/consent restrictions from docs/OPENAVATAR_STUDIO.md apply.
