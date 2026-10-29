# Universal AI Backend

API-only backend for an existing app. It is designed as an extensible integration gateway and searchable catalog for AI models, agents, MCP servers, voice, image/video, search, RAG, coding assistants, and automation tools.

> **Honest scope:** no single backend can contain every current tool, and no one can enumerate future tools that do not exist yet. This project combines a curated starter catalog with live GitHub repository discovery and a documented adapter boundary. A catalog entry is a reference, not proof that the tool has been installed, tested, or securely integrated.

## Features

- FastAPI REST API with OpenAPI docs at `/docs`.
- Expanded searchable catalog from multiple AI/self-hosting/LLMOps directories plus commercial/open-core candidates; exact count is exposed by `GET /v1/catalog/stats`. Repository references are metadata, not executed integrations.
- Live GitHub discovery with filters: `GET /v1/discover/github?q=browser+automation&license_filter=mit&min_stars=100&sort=stars` fetches current public repo results, including license metadata when GitHub supplies it.
- Configurable OpenAI-compatible chat adapter for endpoints such as OpenAI-compatible hosted providers and self-hosted inference services.
- API-key protection for chat and catalog writes.
- Vercel-compatible FastAPI entrypoint and local Windows instructions.
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
- `GET /health` — health check
- `GET /v1/tools?q=voice&category=audio-voice` — search the registry
- Filter candidate license states with `license_status=review_required` or a partial `source_classification` value
- `GET /v1/tools/categories` — categories
- `GET /v1/catalog/stats` — live counts of entries/categories/license-review statuses
- `GET /v1/catalog/sources` — catalog discovery sources and classification policy
- `GET /v1/tools/{tool_id}` — one record
- `GET /v1/skills?q=browser` — searchable skills/tool references
- `GET /v1/providers` — provider configuration status (never returns secrets)
- `POST /v1/chat/completions` — OpenAI-compatible chat proxy (requires `X-API-Key`)
- `POST /v1/tools` — add catalog metadata (requires `X-API-Key`; does not install or execute code)
- `GET /v1/discover/github?q=computer+use` — find current GitHub repositories

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

The registry loads `catalog/tools.json`, `catalog/extended.json`, `catalog/commercial.json`, and `catalog/llmops.json`, merging duplicate repository URLs while preserving stable IDs from the original seed catalog. The seed is a curated set, not a claim to list every AI project in existence.

Many candidate rows are deliberately marked `license_status=review_required`. The catalog includes open-source candidates as well as some source-available/fair-code and mixed-license projects, since commercial products sometimes expose only part of their code. Those classes are labeled separately when known. Do not treat source-available, an open-source SDK, model weights, and a vendor's hosted API as equivalent.

For the most current public GitHub metadata, use `/v1/discover/github` with filters. The API may be rate-limited without `GITHUB_TOKEN`. A GitHub SPDX field is helpful metadata, not legal advice or proof that every dependency, model, dataset, or enterprise feature has the same license.

### Useful searches

```text
GET /v1/tools?q=paid+cloud
GET /v1/tools?q=license&license_status=review_required
GET /v1/discover/github?q=agent+framework&license_filter=apache-2.0&sort=stars
GET /v1/discover/github?q=voice+tts&license_filter=mit&min_stars=100
GET /v1/catalog/stats
```
