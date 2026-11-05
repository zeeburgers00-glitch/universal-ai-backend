# BG LABS video-factory integration plan

This document defines how BG LABS should use this repository as its orchestration backend and connect dedicated editing/rendering projects. It is an integration plan, not a claim that third-party projects have already been installed or executed.

## Product contract

The BG LABS frontend sends one natural-language brief. The backend converts it into a durable, resumable production task. The user should not need to select every model or editing tool manually.

A command should capture, either explicitly or through a clarification step:
- niche, audience, topic, goal, language and tone
- destination platform and aspect ratio
- target runtime (including long-form runtimes)
- voice, visual style, source/stock-footage policy and brand rules
- output requirements (captions, music, effects, thumbnail, title, description, tags)

Never silently invent factual claims or use unlicensed media. Show a review step before publishing or other consequential account actions.

## Reuse the existing backend

Use the existing FastAPI gateway and task system rather than creating a second orchestration backend.

- `POST /v1/chat/tasks`: enqueue the user's command as a durable task.
- `GET /v1/chat/tasks/{task_id}`: retrieve task state.
- `GET /v1/chat/tasks/{task_id}/events`: retrieve progress events.
- `GET /v1/agent-fleet`: discover the existing YouTube specialist role families.
- `GET /v1/tools`, `GET /v1/skills`, and `GET /v1/models/providers`: discover available adapters and configured providers.

The task engine currently requires the configured AI provider and its documented persistence/queue dependencies (Supabase, Redis/Celery and workers). A task must not be shown as running or complete until the relevant worker confirms it.

The BG LABS frontend must call a server-side proxy. Never put `BACKEND_API_KEY`, provider API keys, or worker credentials in browser JavaScript or local storage. Store secrets in the deployment secret manager.

## Video production architecture

1. **Command planner** — parse the brief, detect missing essentials, build a structured production plan and estimate resource requirements.
2. **Research and script** — gather cited facts where needed, write an original script, check timing and split it into scenes.
3. **Media sourcing** — search approved stock libraries (including the existing Pexels integration), download only permitted assets, retain attribution and source metadata.
4. **Voice and audio** — call a configured TTS/voice adapter; voice cloning requires explicit speaker consent and provider/model rights checks.
5. **Visual generation** — call the selected text-to-video or image-to-video adapter for short shots, backgrounds, motion graphics or generated inserts.
6. **Assembly** — create a versioned edit-decision list (EDL/timeline manifest) with scene durations, source clips, transitions, overlays, audio, captions and effects.
7. **Rendering** — dispatch the manifest to a dedicated FFmpeg worker; keep rendering outside the web request process.
8. **Captions and QA** — generate/align subtitles, check audio levels, missing media, black frames, aspect ratio, duration and output integrity.
9. **Delivery** — store the MP4, SRT/VTT, thumbnail and project manifest; return signed download links and a complete audit trail.
10. **Optional publishing** — upload only after explicit approval and platform authorization.

## Long-form production without a fixed product duration preset

Do not try to generate a 20–60 minute video as one model call. Generate a scene plan, produce short shots/voice segments, then assemble and render the full timeline. Use:
- resumable scene-level jobs and idempotency keys
- bounded worker concurrency and retry/backoff
- checkpoints after research, script, voice, media, scene generation and render
- chunked rendering/concatenation for very large outputs
- storage quotas, per-provider limits, timeouts and spend alerts
- an explicit estimated runtime/cost before expensive generation

The product can avoid an arbitrary fixed duration dropdown, but no service can honestly promise unlimited generation. Real limits come from GPU/CPU, storage, provider quotas, concurrency and cost. Never bypass provider rate limits or billing controls.

## Video editing and rendering repositories

| Project | Intended role | License / integration note |
|---|---|---|
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | Primary headless render, transcode, concat, filters, audio mix and subtitle burn-in engine | Mainly LGPL with optional GPL components. Pin and audit the exact build and enabled codecs/filters. |
| [MoviePy](https://github.com/Zulko/moviepy) | Python-level timeline composition, titles and custom effects for simpler jobs | MIT. Uses FFmpeg underneath and can be slower for large projects than direct FFmpeg graphs. |
| [OpenShot libopenshot](https://github.com/OpenShot/libopenshot) | Optional advanced compositing, keyframes, transitions and audio/video effects | LGPL-3.0-or-later; its Qt desktop client is a separate GPL project. Check linking and distribution obligations. |
| [OpenChatCut](https://github.com/0xsline/OpenChatCut) | Optional agent-native timeline editor through its MCP interface; useful for editable project workflows | AGPL-3.0. Keep it as a separately deployed/user-operated integration unless legal review approves a networked/modified deployment. It is not a drop-in headless render library. |
| [Remotion](https://github.com/remotion-dev/remotion) | Programmatic React-based motion graphics and templated scenes | Special license; confirm the current company/commercial terms before production use. |

Do not copy whole editor repositories into this backend. Prefer pinned, isolated workers or documented APIs/MCP bridges. Keep each upstream license and dependency inventory with the adapter.

## Video generation model adapters

Keep models swappable behind a common interface such as `submit_generation`, `get_generation_status`, `cancel_generation`, and `download_result`. Candidate families include Wan, LTX Video and other supported providers. Verify the exact checkpoint's license, hardware needs, output duration, commercial-use conditions and model terms before enabling it. "Open weights" does not automatically mean unrestricted open source or commercial use.

## Worker boundaries

Recommended independently scalable workers:
- `research_worker`
- `script_worker`
- `media_worker`
- `tts_worker`
- `video_generation_worker`
- `caption_worker`
- `render_worker` (FFmpeg / optional MoviePy)
- `quality_worker`
- `delivery_worker`

Workers should accept a task ID and immutable job payload, write artifacts to durable object storage, emit progress events, and return verified artifact metadata. Use least-privilege credentials and isolate third-party code/model runtimes from the API process.

## Required configuration before live production

- Public backend base URL and server-side `BACKEND_API_KEY`
- AI provider base URL, key and selected model
- Supabase project/database configuration for durable task and artifact records
- Redis/Celery broker and worker deployment
- Object storage bucket, access policy and signed URL configuration
- TTS provider/model credentials
- Video-generation provider or GPU worker endpoint
- FFmpeg worker image with an audited build
- Optional Pexels and other stock-media credentials
- Optional OpenChatCut MCP endpoint and its own authentication

Until these are configured and health-checked, BG LABS must label generation as **not connected** and must not claim that a video has been created.
