# One command in, a finished video out

```
POST /v1/command   {"command": "make a 10 minute video about tea farming in Punjab"}
                   -> job id, scene timeline, render progress, final MP4
```

Open `/app#/producer` for the same thing as a text box.

## What actually happens

```
command ──► planner ──► timeline ──► scenes ──► ffmpeg ──► one MP4
             │            │            │
             │            │            └── rendered one at a time, then concatenated
             │            └── absolute offsets, captions, chunk boundaries
             └── model-assisted if a key is set, built-in parser otherwise
```

| Stage | Module | Notes |
|---|---|---|
| Plan | `videoengine/planner.py` | Duration, aspect ratio, language and topic are read out of plain language, including Hinglish |
| Timeline | `videoengine/timeline.py` | Pure maths; no I/O, no ffmpeg |
| Render | `videoengine/assembly.py` | Scene-by-scene ffmpeg, concatenated with stream copy |

## Long video is not a special mode

Scenes are independent and bounded, so total length is only limited by disk and
patience:

| Requested | Scenes at 8s | Timeline proven by tests |
|---|---|---|
| 10 minutes | 75 | yes |
| 1 hour | 450 | yes |
| 3 hours | 1,080 | yes |
| 12 hours (default cap) | 5,400 | cap raises with `COMMAND_MAX_DURATION_SECONDS` |

Rendering is resumable: a crash re-runs only the segments that are missing,
because each scene is written to its own file first.

## It works with zero API keys

That is deliberate — the pipeline is never dead on arrival.

| Without keys | With keys |
|---|---|
| Built-in planner writes templated narration | Model writes a real script per topic |
| Colour cards as visuals | Stock footage (`PEXELS_API_KEY`) or generated images (`MEDIA_WORKER_URL`) |
| Burned captions carry the words | Narration audio (`VOICE_WORKER_URL`) |
| — | Post-processing and lip-sync through the media worker |

`GET /v1/command/capabilities` reports which of these are live and names the
exact environment variable that would upgrade each one. The response never
pretends a missing provider is present.

## Adding your keys

Keys are stored server-side through the existing vault and never returned:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/vault/secrets \
  -H "X-API-Key: $BACKEND_API_KEY" -H "Content-Type: application/json" \
  -d '{"secrets":{"GROQ_API_KEY":"gsk_...","GROQ_DEFAULT_MODEL":"llama-3.3-70b-versatile"}}'
```

The command layer picks up any of these pairs, in order:

1. `AI_BASE_URL` + `AI_API_KEY` + `AI_DEFAULT_MODEL`
2. `GROQ_BASE_URL` + `GROQ_API_KEY` + `GROQ_DEFAULT_MODEL`
3. `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `OPENAI_DEFAULT_MODEL`

Only HTTPS endpoints are accepted.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/command/capabilities` | renderer status, configured providers, what is missing |
| POST | `/v1/command` | create a job (`render: false` for a plan only) |
| GET | `/v1/command/{id}` | status, progress, plan, full timeline |
| GET | `/v1/command/{id}/timeline` | scenes with exact offsets |
| GET | `/v1/command/{id}/video` | stream the MP4 (header key, or `?key=` for a `<video>` tag) |
| GET | `/v1/command` | recent jobs |

`image_paths` lets you supply your own stills per scene, but only files inside
`COMMAND_DATA_DIR` are accepted — the endpoint will not read arbitrary paths.

## Requirements

`ffmpeg` on the API host. The Dockerfile installs ffmpeg plus `fonts-dejavu-core`
(captions need a font). In a bare sandbox, `pip install imageio-ffmpeg` provides a
static binary and the tests use it automatically.

## Limits worth stating plainly

- **Narration needs the voice worker.** Without it the video is silent with
  burned captions; the API says so instead of shipping a silent file silently.
- **A render occupies the API process.** It runs in a background thread, so
  requests keep flowing, but very long renders want the media worker or a
  dedicated box rather than a small shared VM.
- **Stock footage needs a Pexels key.** Without one the visual track is colour
  cards.
- **Scene length is a planning assumption, not magic.** 8 seconds per scene suits
  documentary pacing; pass `scene_seconds` for anything else.

## Tests

`tests/test_command_center.py` covers duration parsing (including `1 ghanta`),
aspect detection, exact multi-hour timeline maths, chunk boundaries, captions,
auth, path traversal rejection, and one **real ffmpeg render** whose output is
probed for duration and resolution. The render test skips cleanly where ffmpeg is
absent rather than failing.
