# The free tool belt

`prompts/free_toolbelt.json` is the catalogue: 65 tools, what each one does, how to install
it, and the one command that proves it works. `app/toolbelt.py` is the part that runs them.

The design decision worth knowing: **the catalogue is bigger than the runner set on
purpose.** A tool that exists in the JSON but has no runner still shows up in `/v1/belt`
with the install command and a false `available` flag. Nothing silently disappears, and
nothing pretends to work.

## Honesty contract

| Situation | What the API returns |
|---|---|
| Tool ready and args valid | `{"ok": true, "tool": "ffmpeg", "result": {...}}` |
| Dependency missing | HTTP 503, `unavailable: pip install Pillow` (or the apt package) |
| Tool in catalogue, no runner yet | HTTP 503, `unavailable: <name> has no runner wired yet — <install>` |
| Bad arguments / unsafe path | HTTP 422 with the reason |
| Network tool, flag off | HTTP 503, `unavailable: network tools are off (set UAI_TOOLS_ALLOW_NETWORK=1)` |

`available` is **measured at call time**: a binary on `PATH` (or the bundled
`imageio-ffmpeg`), an importable module, a required env var, or a listening local service.
Results are cached for 30 seconds — `POST /v1/belt/refresh` clears it after you install
something.

Two tiers matter in reports:

- `available` — dependencies are present (may still have no runner)
- `ready` — dependencies present **and** a runner is wired, so it can actually do the work

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/belt` | whole belt, with `available`/`detail` per tool; filters `category`, `available`, `runnable` |
| GET | `/v1/belt/status` | summary counts + Claude status (`belt`, `claude`) |
| GET | `/v1/belt/search?q=` | BM25 + synonym search: "subtitles" → ffmpeg, "spreadsheet" → openpyxl |
| GET | `/v1/belt/{id}` | one tool + its catalogue entry |
| POST | `/v1/belt/{id}/run` | `{"args": {...}}` |
| POST | `/v1/belt/{id}/verify` | runs the catalogue's own `test` command and reports the exit code |
| GET | `/v1/belt/claude-schema` | JSON-Schema definitions Anthropic's tool use needs |
| POST | `/v1/belt/refresh` | drop the availability cache |

All of them need the usual `X-API-Key`.

## What is wired today

Measured on this checkout (your box will differ — that is the point):

| Tool | Runner does |
|---|---|
| `ffmpeg` | probe, trim, extract audio, thumbnails, chapters, silence cut, loudness, scale, gif |
| `imagemagick` | resize, crop, format convert (uses the `convert`/`magick` already on the box) |
| `git` | **read-only** status, log, diff, show, branch — `commit`/`push` are refused by design |
| `ripgrep` | code search inside the repo, capped output |
| `ast` | top-level symbols and imports of any Python file in the repo |
| `sqlite3` | read-only SQL against any SQLite file under `UAI_DATA_ROOT` |
| `pytest` | run a test path in the repo and return passed/failed counts |
| `pillow` | resize/save images — available as soon as `pip install Pillow` |
| `httpx` | GET/HEAD requests, only with `UAI_TOOLS_ALLOW_NETWORK=1` |
| `ollama` | one prompt against a local Ollama server, when something is listening |

The other 55 entries resolve their dependencies and report honestly. Install one and
`POST /v1/belt/refresh`; it appears as ready without a code change if a runner exists,
and still says "no runner wired yet" if it does not.

## Claude, the tool belt, and JARVIS

```
POST /v1/jarvis/chat {"message": "kaunsi branch par hain?"}
   │
   ├─ ANTHROPIC_API_KEY set? ── yes ─▶ Claude (Messages API)
   │                                     │ tool_use: run_git {op: branch}
   │                                     ▼
   │                                  toolbelt.run("git", ...) ──▶ real output
   │                                     │ tool_result back to Claude
   │                                     ▼
   │                                  final text + every tool run in "actions"
   │
   └─ no key ─▶ rules layer (28 intents) ─▶ still honest, still runs tools
```

Rules that are enforced in the prompt and in code:

1. Max 3 tool rounds per message, so one message cannot spiral into a bill.
2. A failing tool is returned to the model as `is_error` **with the real message**, so it
   says "pip install Pillow" instead of inventing a thumbnail.
3. `available` tools only are offered to the model — it cannot hallucinate a tool that is
   not on this machine.
4. Without a key, `/v1/jarvis/chat` reports `{"used_model": false}`; the reply never claims
   a model was used.

Direct, model-free tool calls also work, which is useful when you trust the command more
than the model:

```bash
curl -s -X POST localhost:8000/v1/jarvis/chat -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"tool ffmpeg op=probe path=video.mp4"}'
```

## Adding a runner

1. Write `def _run_xyz(args: dict) -> dict:` — validate inputs, raise `ToolError` for bad
   arguments, return JSON-able data. Never return `{"ok": true}` without real work.
2. Register it: `"xyz": Binding(modules=("xyzlib",), params={"path": "string"}, runner=_run_xyz)`.
3. Add a test that proves it on a generated file, plus one for the failure path.
4. If the tool exposes parameters the model should choose, they must be in `params` or
   Claude cannot fill them.

## Cost

Zero. Every wired tool is local and open source. The only paid thing in the stack is
Claude, and only if you add a key — see `docs/KAGGLE_HOSTING.md` for hosting on a free
Kaggle GPU box, and `docs/JARVIS_UPGRADE.md` for the local Ollama alternative.
