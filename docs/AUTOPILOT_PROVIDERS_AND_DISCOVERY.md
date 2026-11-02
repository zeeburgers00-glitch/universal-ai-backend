# AI YouTube Autopilot: provider and stock-footage integration

## Newly mapped model gateways

The backend now exposes separate provider IDs and server-side environment variables for:

- Groq: `GROQ_API_KEY`
- Gemini: `GEMINI_API_KEY`
- Mistral: `MISTRAL_API_KEY`
- OpenRouter: `OPENROUTER_API_KEY`
- Hugging Face: `HUGGINGFACE_API_KEY`
- Z.ai / GLM: `ZAI_API_KEY` (default general API base: `https://api.z.ai/api/paas/v4`)
- HackerAI: `HACKER_AI_API_KEY` (OpenAI-compatible API)
- OpenCode Zen: `OPENCODE_ZEN_API_KEY` (OpenAI-compatible chat-completions endpoint; choose a model supported by that endpoint)

OpenCode Zen exposes more than one API protocol. This adapter uses its OpenAI-compatible `/chat/completions` route; do not assume every model listed by Zen supports that route. If your account/model requires the Responses or Anthropic Messages protocol, it needs a matching adapter.

"HackerAI" is mapped to the public OpenAI-compatible service documented at `https://api.hackerai.sh/v1`. If the supplied credential belongs to a different vendor, use the generic `openai-compatible` provider and configure its verified base URL instead.

## Pexels stock video search

Configure `PEXELS_API_KEY` server-side, then call:

```http
POST /v1/media/stock/pexels/search
X-API-Key: YOUR_BACKEND_API_KEY
Content-Type: application/json

{"query":"ocean waves","orientation":"landscape","size":"medium","per_page":12}
```

The endpoint returns video metadata, creator details, Pexels page URL and the selected downloadable video file URL. It does not silently download or publish footage. Store creator/source attribution alongside every chosen asset, verify the current Pexels licence/terms, and render only footage compatible with the target format.

Pexels requires API requests to carry the Pexels key in the Authorization header and asks integrations to display a prominent Pexels link. See https://www.pexels.com/api/documentation/.

## Continuous tool discovery and safe self-improvement

The existing `GET /v1/discover/github` endpoint continuously enables fresh searches across AI categories. New repository discoveries must first enter a candidate/review stage. A future scheduler may run discovery at a fixed interval and create candidate records automatically, but it must never execute arbitrary repository code in the API process. Before a candidate becomes an installed integration, verify upstream licence, maintainer/release history, dependency and vulnerability posture, required permissions, secrets, sandbox compatibility, tests, resource limits and rollback. Keep the production backend running while candidate checks happen in isolated workers.

A catalogue entry means "discovered", not "installed". A tested adapter means "available". A worker health check means "running". These statuses must remain distinct.
