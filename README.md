# Universal AI Backend

API-only backend for an existing app. It is designed as an extensible integration gateway and searchable catalog for AI models, agents, MCP servers, voice, image/video, search, RAG, coding assistants, and automation tools.

> **Honest scope:** no single backend can contain every current tool, and no one can enumerate future tools that do not exist yet. This project combines a curated starter catalog with live GitHub repository discovery and a documented adapter boundary. A catalog entry is a reference, not proof that the tool has been installed, tested, or securely integrated.

## Features

- FastAPI REST API with OpenAPI docs at `/docs` and built-in interactive web dashboard at `/explorer`.
- Global searchable AI & MCP catalog (`6,100+` unique open-source repositories, `1,760+` MCP servers/SDKs/gateways, LLMOps tools, voice/video/image/music models, and flagship commercial AI platforms across `85+` categories, plus `229` REA MCP reverse-engineering/AI-inspection tools); exact live counts are exposed by `GET /v1/catalog/stats`. Repository and platform references are metadata, not executed integrations.
- REA (`morluto/rea` / `rea-agents`) MCP catalog (`GET /v1/rea/status`, `GET /v1/rea/tools`) **plus** an isolated, approval-gated REA inspection worker (`workers/rea_worker` via `POST /v1/rea/inspect`).
- `45` configurable LLM & multimodal inference provider adapters (`GET /v1/models/providers`) including OpenAI, Anthropic, Google Gemini, xAI Grok, Groq, DeepSeek, Qwen/DashScope, Perplexity, Cohere, Moonshot/Kimi, Zhipu/GLM, MiniMax, NVIDIA NIM, OpenRouter, Together, Fireworks, Cerebras, Mistral, Azure OpenAI, Bedrock Gateway, Cloudflare AI, Ollama, vLLM, SGLang, TGI, TabbyAPI, KoboldCpp, Jan, LM Studio, and LiteLLM.
- Live GitHub discovery with `30` built-in AI category presets (`GET /v1/discover/categories`) and filters: `GET /v1/discover/github?category_preset=mcp-servers&license_filter=mit&min_stars=100&sort=stars`.
- API-key protection for chat, worker dispatches, and catalog writes.
- Vercel-compatible FastAPI entrypoint and unified Docker Compose stack (`workers/docker-compose.yml`) for GPU/async workers.
- Safe-by-default integration model: listing a repo never installs or executes its code.



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

Open `http://127.0.0.1:8000/docs`.

## Environment variables

- `BACKEND_API_KEY`: long random secret required by protected endpoints. Do not put it in the frontend bundle.
- `AI_BASE_URL`: base URL ending at an OpenAI-compatible API root, e.g. `https://api.groq.com/openai/v1`.
- `AI_API_KEY`: server-side model provider key.
- `AI_DEFAULT_MODEL`: optional model used when the request omits a model.
- `GITHUB_TOKEN`: optional GitHub token to improve GitHub API rate limits for repository discovery.
- `CORS_ORIGINS`: comma-separated web origins; use your app's exact origin for production.

## API routes

- `GET /` — service metadata
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
- `GET /v1/providers` & `GET /v1/models/providers` — `45` provider configuration states (never returns secrets)
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

