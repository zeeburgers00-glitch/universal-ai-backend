# API keys: where they go and how to check them

## Never paste keys in chat

Keys pasted into a conversation should be treated as **already leaked**. Rotate
them at the provider dashboard before the next deploy. This repository
deliberately never stores them:

- `.env` is gitignored and never committed.
- Secrets are read through `app/vault.py`, which prefers the OS environment and
  falls back to the runtime vault (Supabase), so nothing is written into source.
- `GET /v1/ai/providers` returns masked previews only (`gsk_lC…XAfT`). No
  endpoint ever returns a full key.

## Two ways to add a key

**1. Environment** (survives restarts, best for a server you control)

```bash
cp .env.example .env    # then fill in what you have
```

**2. Runtime vault** (no restart, best for a hosted deployment)

```bash
curl -s -X POST https://your-host/v1/vault/secrets \
  -H "X-API-Key: $BACKEND_API_KEY" -H "Content-Type: application/json" \
  -d '{"secrets":{"GROQ_API_KEY":"gsk_…","GROQ_DEFAULT_MODEL":"llama-3.3-70b-versatile"}}'
```

## Check them — this is the important part

```bash
curl -s "https://your-host/v1/ai/health?probe=true" -H "X-API-Key: $BACKEND_API_KEY"
```

`probe=true` makes one real request per provider and reports `ok`,
`key rejected`, `rate limited` or the HTTP status. Without `probe` it only checks
that a key, model and HTTPS base URL are present.

Every provider that cannot be used comes back with a `problem` string naming the
exact environment variable to set — no guessing.

## Supported providers

| Provider | Key | Default model | Notes |
|---|---|---|---|
| Groq | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | Fastest of the free tiers |
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.0-flash` | Uses Google's OpenAI-compatible endpoint |
| Mistral | `MISTRAL_API_KEY` | `mistral-large-latest` | |
| Z.ai (GLM) | `ZAI_API_KEY` | `glm-4.6` | |
| OpenRouter | `OPENROUTER_API_KEY` | `meta-llama/llama-3.3-70b-instruct` | One key, many models |
| Hugging Face | `HF_API_KEY` | `meta-llama/Llama-3.3-70B-Instruct` | Router endpoint |
| OpenCode Zen | `OPENCODE_ZEN_API_KEY` | — | Needs `OPENCODE_ZEN_BASE_URL` |
| Hacker AI | `HACKERAI_API_KEY` | — | Needs `HACKERAI_BASE_URL` |
| Custom | `AI_API_KEY` | — | Needs `AI_BASE_URL` |

A provider is only tried when it has **a key, a model and an HTTPS base URL**.
Anything missing and it is skipped with a reason, never silently.

## Failover

```
AI_PROVIDER_ORDER=groq,gemini,mistral,zai,openrouter,huggingface,opencode_zen,hackerai,custom
```

The first provider that answers wins. A 429, a 401, a timeout or an empty
response moves to the next one, and the job payload records every attempt so you
can see who was tried. Only when **all** of them fail does the request fail — and
then it says why, per provider.

This matters for video production: a 40-scene script is one long call, and losing
it because one vendor throttled you would be wasteful.

## Video-specific keys

| Key | Effect |
|---|---|
| `PEXELS_API_KEY` | Stock b-roll instead of colour cards |
| `VOICE_WORKER_URL` + `VOICE_WORKER_API_KEY` | Narration audio (needs a GPU host, see `deploy/kaggle/`) |
| `MEDIA_WORKER_URL` + `MEDIA_WORKER_API_KEY` | Generated visuals, lip-sync, post-processing |

## What happens with no keys at all

Nothing breaks. The pipeline uses the built-in planner for narration, colour
cards for visuals and burned captions for the words, and produces a real MP4.
`GET /v1/command/capabilities` lists exactly what each key would add.
