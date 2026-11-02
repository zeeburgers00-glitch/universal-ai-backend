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

## Open-source, self-hosted provider options

GitHub repositories provide deployable software, not automatically hosted public API endpoints or free API credentials. These options avoid a third-party inference key when deployed on infrastructure we control. They still require compute, monitoring, network security, and model/license review.

### Text generation and script writing

The production YouTube worker already reads `MODEL_BASE_URL`, `MODEL_API_KEY`, and `MODEL_NAME` and calls the OpenAI-compatible `/chat/completions` route. It can therefore be pointed at an internal OpenAI-compatible server without changing the script-generation contract:

- LocalAI: https://github.com/mudler/LocalAI — self-hosted OpenAI-compatible runtime supporting multiple modalities. Example internal base URL: `http://local-ai:8080/v1`.
- Ollama: https://github.com/ollama/ollama — local model server with an OpenAI-compatible API. Example internal base URL: `http://ollama:11434/v1`; its local OpenAI-compatible example uses the placeholder key `ollama`, which is ignored by the local server.
- vLLM: https://github.com/vllm-project/vllm — higher-throughput OpenAI-compatible serving for suitable GPU infrastructure.
- LiteLLM: https://github.com/BerriAI/litellm — an OpenAI-compatible gateway/router for many model providers. LiteLLM is a gateway, not a model: cloud upstreams still need their own credentials and billing.

Use private service DNS (for example, `http://ollama:11434/v1`) when the API and model server share a private network. Do not expose an unauthenticated model endpoint to the public internet. For a self-hosted endpoint, set `MODEL_API_KEY` to the local server's configured credential or its documented placeholder; do not copy any leaked third-party key into the deployment.

### Research and topic discovery

SearXNG: https://github.com/searxng/searxng provides a self-hosted metasearch HTTP API. Its JSON interface is `/search?q=...&format=json`; the operator must enable JSON in the instance's `search.formats` setting. It avoids a single paid search-provider API key, but results depend on configured upstream search engines, rate limits, and availability. The current YouTube worker still calls Tavily directly, so SearXNG is an alternative implementation target, not an already-active fallback.

### Speech transcription and captions

- faster-whisper: https://github.com/SYSTRAN/faster-whisper — local Whisper-compatible transcription engine using CTranslate2. It is a library/engine, not a ready public API; run it inside a worker or wrap it with an authenticated HTTP service.
- LocalAI also provides an OpenAI-style runtime with audio backends.

The current YouTube video renderer still sends captions requests to OpenAI's `/v1/audio/transcriptions`. A self-hosted transcription endpoint must be configured and tested before `OPENAI_API_KEY` can be removed from that path.

### Voice generation

The repository already contains `workers/voice_worker`, with asynchronous F5-TTS and MeloTTS job scaffolding. This is separate from the current YouTube render path, which still calls ElevenLabs directly.

**Important commercial-use restriction:** F5-TTS source code is MIT, but the upstream standard pretrained model weights are CC-BY-NC. The current voice-worker configuration intentionally defaults to `F5_TTS_MODEL_LICENSE_CLASS=noncommercial` and blocks commercial jobs unless a checkpoint with documented commercial rights is reviewed and approved. Do not flip that setting merely to bypass the check. See https://github.com/SWivid/F5-TTS and its model cards.

MeloTTS is a preset-speaker option in the existing worker; review the exact package, model, voice-asset, and output-use terms before enabling it commercially. It is not a reference-audio voice-cloning substitute in this worker.

### What still needs credentials

- Pexels stock footage: keep using the official Pexels API with a rotated key; do not rely on a shared or leaked key.
- YouTube upload and channel management: requires the channel owner's Google OAuth consent and the YouTube Data API. GitHub cannot provide a legitimate substitute credential.
- Any hosted commercial LLM, speech, or research service: requires credentials from the actual account owner and may incur provider charges.

### Deployment boundary

Self-hosted software is not the same as a free hosted API. LocalAI/Ollama/SearXNG/faster-whisper/F5-TTS need a machine or service that remains online; GPU-backed models need appropriate GPU capacity. Do not mark a provider active until its service is deployed, health-checked, and exercised by an integration test. Keep credentials in the hosting provider's secret manager, never in Git, source files, logs, or chat.

## Continuous tool discovery and safe self-improvement

The existing `GET /v1/discover/github` endpoint continuously enables fresh searches across AI categories. New repository discoveries must first enter a candidate/review stage. A future scheduler may run discovery at a fixed interval and create candidate records automatically, but it must never execute arbitrary repository code in the API process. Before a candidate becomes an installed integration, verify upstream licence, maintainer/release history, dependency and vulnerability posture, required permissions, secrets, sandbox compatibility, tests, resource limits and rollback. Keep the production backend running while candidate checks happen in isolated workers.

A catalogue entry means "discovered", not "installed". A tested adapter means "available". A worker health check means "running". These statuses must remain distinct.
