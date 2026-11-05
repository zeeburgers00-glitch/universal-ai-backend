# Models — jo aaj (Nov 2026) actually chalte hain

Verified: `2026-11-05` · source: provider docs (neeche links)

> **Seedhi baat:** model IDs tezi se badalte hain. Har entry par `confidence` likha hai —
> `high` matlab ID provider ke docs/search results me seedha dekha gaya,
> `medium` matlab naam table me tha par exact suffix infer kiya gaya. Billing se pehle
> provider ki apni list zaroor check karo.

## Endpoints

```bash
GET /v1/ai/models                                  # sab models
GET /v1/ai/models?provider=gemini                   # ek provider
GET /v1/ai/models?capability=image-out              # feature ke hisaab se
GET /v1/ai/models?free_only=true                    # sirf free tier
GET /v1/ai/models/resolve?capability=vision         # best live model
GET /v1/ai/models/stats                             # counts
```

## OpenAI (`openai`)

- Default: `gpt-5.6-sol` · key: `OPENAI_API_KEY` · 21 live / 26 listed

| Model | Kind | Capabilities | Tier | Status | Free |
|---|---|---|---|---|---|
| `gpt-4.1` | chat | text, vision, tools, json | long-context | stable | — |
| `gpt-4.1-mini` | chat | text, vision, tools | budget | stable | — |
| `gpt-4o-mini` | chat | text, vision, tools | legacy-budget | stable | — |
| `gpt-5.1-codex-max` | chat | text, tools, code, long-running | coding | stable | — |
| `gpt-5.1-codex-mini` | chat | text, tools, code | coding-budget | stable | — |
| `gpt-5.2` | chat | text, vision, tools, reasoning | previous-flagship | stable | — |
| `gpt-5.2-chat-latest` | chat | text, vision | chat-alias | stable | — |
| `gpt-5.2-codex` | chat | text, tools, code | coding | stable | — |
| `gpt-5.3-codex` | chat | text, tools, code, reasoning | coding | stable | — |
| `gpt-5.4` | chat | text, vision, tools, reasoning | previous-flagship | stable | — |
| `gpt-5.4-mini` | chat | text, vision, tools, json | budget | stable | — |
| `gpt-5.4-nano` | chat | text, tools, json | cheapest | stable | — |
| `gpt-5.5` | chat | text, vision, tools, reasoning | previous-flagship | stable | — |
| `gpt-5.6-luna` | chat | text, tools, json | budget | stable | — |
| `gpt-5.6-sol` | chat | text, vision, tools, reasoning, json | flagship | stable | — |
| `gpt-5.6-terra` | chat | text, vision, tools, reasoning | balanced | stable | — |
| `gpt-6-astra` | chat | text, vision, reasoning | premium | stable | — |
| `gpt-6-luna` | chat | text, tools, json | budget | stable | — |
| `gpt-6-sol` | chat | text, vision, tools, reasoning, json | flagship | stable | — |
| `gpt-6.1-sol` | chat | text, vision, tools, reasoning, json | flagship | stable | — |
| `gpt-6.1-terra` | chat | text, vision, tools, reasoning | balanced | stable | — |
| `gpt-5` | chat | text, vision, tools, reasoning | legacy | deprecated | — |
| `gpt-5-mini` | chat | text, tools | legacy | deprecated | — |
| `gpt-5-nano` | chat | text, tools | legacy | deprecated | — |
| `gpt-5-pro` | chat | text, reasoning | legacy-premium | deprecated | — |
| `gpt-5.3-chat-latest` | chat | text, vision | chat-alias | shutdown | — |

## Google Gemini (`gemini`)

- Default: `gemini-3.8-flash` · key: `GEMINI_API_KEY` · 23 live / 27 listed
- Free tier: Flash/Flash-Lite models are free within per-project limits (community reports ~20 RPD for 3.8/3.6 Flash, ~500 RPD for Flash-Lite). Pro and Gemini 4 Argon are paid-only.

| Model | Kind | Capabilities | Tier | Status | Free |
|---|---|---|---|---|---|
| `gemini-3-flash-preview` | chat | text, vision, tools, reasoning | preview | preview | ✅ |
| `gemini-3-pro-image` | image | image-out, image-edit, text-in-image | image-premium | stable | — |
| `gemini-3.1-flash-image` | image | image-out, image-edit, text-in-image | image-default | stable | — |
| `gemini-3.1-flash-lite` | chat | text, vision, tools | cheapest | stable | ✅ |
| `gemini-3.1-flash-lite-image` | image | image-out | image-cheap | stable | — |
| `gemini-3.1-flash-live-preview` | live | realtime-voice, audio-in, audio-out | realtime | preview | — |
| `gemini-3.1-flash-tts-preview` | tts | text-to-speech | tts | preview | ✅ |
| `gemini-3.1-pro-preview` | chat | text, vision, tools, reasoning, long-context | pro | preview | — |
| `gemini-3.5-flash` | chat | text, vision, tools, reasoning | fast-legacy | stable | — |
| `gemini-3.5-flash-lite` | chat | text, vision, tools | cheap | stable | ✅ |
| `gemini-3.5-live-translate-preview` | live | realtime, translation, audio-in, audio-out | realtime | preview | — |
| `gemini-3.5-transcribe` | stt | audio-in, transcribe | stt | stable | ✅ |
| `gemini-3.5-transcribe-live` | stt | audio-in, transcribe, realtime | stt | stable | ✅ |
| `gemini-3.6-flash` | chat | text, vision, tools, reasoning | fast | stable | ✅ |
| `gemini-3.7-flash` | chat | text, vision, tools, reasoning, coding | fast | stable | — |
| `gemini-3.8-flash` | chat | text, vision, audio, tools, reasoning | flagship-fast | stable | ✅ |
| `gemini-3.8-live` | live | realtime-voice, audio-in, audio-out | realtime | stable | ✅ |
| `gemini-4-argon` | chat | text, vision, tools, reasoning | flagship | stable | — |
| `gemini-nano-banana-2.1` | image | image-out, image-edit | image | stable | — |
| `gemini-omni-1.1-flash` | omni | text, vision, audio, image-out, tools | omni | preview | — |
| `gemma-4-31b-it` | chat | text | open-weights | stable | ✅ |
| `veo-3.1-fast-generate-001` | video | video-out | video-fast | stable | — |
| `veo-3.1-generate-001` | video | video-out, audio-out | video | stable | — |
| `gemini-2.5-flash` | chat | text, vision, tools | legacy | deprecated | — |
| `gemini-2.5-pro` | chat | text, vision, tools, reasoning | legacy | deprecated | — |
| `gemini-2.0-flash` | chat | text, vision, tools | legacy | shutdown | — |
| `gemini-3-pro-image-preview` | image | image-out | legacy | shutdown | — |

## Groq (`groq`)

- Default: `llama-3.3-70b-versatile` · key: `GROQ_API_KEY` · 14 live / 14 listed
- Free tier: Free tier exists with per-model limits (reported ~30 RPM and up to 14,400 RPD on 8B/70B, tighter on larger models).

| Model | Kind | Capabilities | Tier | Status | Free |
|---|---|---|---|---|---|
| `groq/compound` | agent | text, tools, web-search, code-execution | agentic | stable | — |
| `groq/compound-mini` | agent | text, tools, web-search | agentic | stable | — |
| `kimi-k2-instruct` | chat | text, tools | large | stable | — |
| `llama-3.1-8b-instant` | chat | text, tools | cheapest | stable | — |
| `llama-3.3-70b-versatile` | chat | text, tools, json | workhorse | stable | — |
| `llama-4-maverick-17b-128e-instruct` | chat | text, vision, tools | moE | stable | — |
| `llama-4-scout-17b-16e-instruct` | chat | text, vision, tools | moE-fast | stable | — |
| `meta-llama/llama-guard-4-12b` | moderation | safety-classification | guard | stable | — |
| `moonshotai/kimi-k2-0905` | chat | text, tools | large | stable | — |
| `openai/gpt-oss-120b` | chat | text, reasoning, tools | open-weights | stable | — |
| `openai/gpt-oss-20b` | chat | text, reasoning, tools | open-weights | stable | — |
| `qwen3-32b` | chat | text, reasoning | reasoning | stable | — |
| `whisper-large-v3` | stt | audio-in, transcribe | stt | stable | — |
| `whisper-large-v3-turbo` | stt | audio-in, transcribe | stt-fast | stable | — |

## Dead models jo ab bhi kahin kahin docs me milte hain

Inhe use na karo — provider ne band kar diya:

- `gpt-5.3-chat-latest` (openai) — shut down
- `gemini-2.0-flash` (gemini) — shut down
- `gemini-3-pro-image-preview` (gemini) — shut down

Total listed models: **67**

## Sources

- https://developers.openai.com/api/docs/models/all
- https://ai.google.dev/gemini-api/docs/models
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions
- https://console.groq.com/docs/models
- https://www.requesty.ai/models/google
- https://www.free-model.com/providers/groq/
