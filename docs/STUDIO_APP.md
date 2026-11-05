# Universal AI Studio — the app built on this backend

`GET /app` (alias `GET /studio`) serves a single-page application that turns the
API-only control plane into a usable product. It is served by the same FastAPI
process, so every request is same-origin: no CORS setup, no proxy, no bundler,
no CDN, and no build step.

> **Honest scope:** the Studio is a control surface over real endpoints in this
> repository. It does not add capability that the backend does not have. Where a
> secret or worker is missing, the UI says so instead of faking a result.

## Why a single page instead of a new frontend project

The repo used to ship a separate Next.js frontend (`frontend/`, now removed), which
require `npm install`, a Node runtime and a separate deployment. The Studio is
deliberately different:

| Concern | Studio approach |
|---|---|
| Deployment | Zero extra services — ships inside the existing FastAPI app |
| Dependencies | None (no React, no CDN); works fully offline |
| Auth | The browser never holds provider keys; it only forwards `X-API-Key` |
| Preview safety | Relative URLs only — never calls `localhost` from the browser |
| Footprint | One Python module (`app/studio_ui.py`) + three routes |

## Architecture

```
browser ──GET /app──────────────► app/main.py ─► studio_ui.STUDIO_HTML
        ──fetch /v1/...  (same origin, relative paths)──► FastAPI routes
                                                          │
                              registry / providers / workers / manifests
```

`app/studio_ui.py` exports `STUDIO_HTML` (the whole app). `app/main.py` mounts
it at `/app` and `/studio` and advertises it in the `GET /` metadata as
`"studio": "/app"`.

## Features (all live against the API)

### 1. Overview — `GET /v1/catalog/stats`, `/v1/models/providers`, `/v1/runtime/capabilities`
- Four headline counters: catalog entries (**6,122**), categories (**89**),
  providers configured (**0 / 48** by default), workers ready (**0 / 12**).
- Horizontal bar chart of the largest catalog categories (mcp-servers, coding
  agents, image generation, …).
- A "what actually works right now" checklist that reports the truthful state of
  each subsystem instead of a green dashboard.

### 2. Catalog — `GET /v1/tools`, `GET /v1/tools/categories`
- Full-text search across every indexed entry.
- Filters: category (89 options), minimum stars, primary language.
- Card results with description, stars, language, license-status chip and a
  direct repository link. Debounced input, paginated "Load more".
- `⌘K` / `Ctrl+K` jumps straight to search.

### 3. Chat — `POST /v1/chat/completions`
- Provider picker built from all 48 adapters (a `✓` marks credentialed ones).
- Free-text model field plus provider env-var hints, so you can see which server
  variable a route needs.
- Multi-turn history; Enter sends, Shift+Enter newline.
- Errors from the backend (missing key, unconfigured provider) are shown verbatim.

### 4. Providers — `GET /v1/models/providers`
- Grid of all 48 adapters with ready / not-configured state, API mode, capability
  chips, and the exact `*_API_KEY` / `*_BASE_URL` environment variable names.

### 5. Agents — `GET /v1/agents`
- All 42 agent blueprints with mission, capabilities, risk-level chip and the
  human-approval rule attached to each.

### 6. Workflows — `GET /v1/workflows`
- All 28 workflow templates with required services, step count and an
  auto / approval badge.

### 7. Discovery — `GET /v1/discover/categories`, `GET /v1/discover/github`
- 30 built-in category presets plus live GitHub repository search with a star
  threshold.
- Failures are surfaced honestly ("discovery unavailable" + upstream reason and
  the `GITHUB_TOKEN` hint) rather than showing invented repositories.

### 8. Finance — `GET /v1/earning/fleet`, `GET /v1/finance/summary`
- Earning-fleet blueprint: 120 agent slots across 12 departments, budget and
  parallel limits, plus the verbatim execution policy ("blueprints are not
  running processes").
- Revenue-ledger panel that reports whether Supabase is actually connected, and
  degrades to a setup message when it is not.

### Cross-cutting
- API-key modal → stored only in `localStorage`, sent as `X-API-Key`.
- Live health indicator polling `/health` every 30 s.
- Dark theme, responsive down to mobile (sidebar becomes a scroll strip).
- Every user- or server-supplied string is HTML-escaped before insertion.

## What works with zero configuration

| Feature | Requires |
|---|---|
| Overview, Catalog, Providers, Agents, Workflows, Discovery presets | Nothing |
| Chat | `BACKEND_API_KEY` + one provider's key in the server `.env` |
| Discovery against GitHub | `GITHUB_TOKEN` (rate limits) + outbound network |
| Finance ledger | `SUPABASE_URL` + service-role key + ledger migration |

Because the protected routes are keyed server-side, a public deployment of `/app`
is read-only until an operator sets `BACKEND_API_KEY`.

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://127.0.0.1:8000/app
```

## Tests

`tests/test_studio_app.py` asserts that both routes serve HTML, that the root
metadata advertises `/app`, that the page contains no CDN or `localhost`
references, and that no secrets are embedded.

## Sensible next steps

1. **Persist the API key per operator** — swap the single shared key for real
   sessions (Supabase auth already exists in `studio/`).
2. **Streaming chat** — add SSE to `/v1/chat/completions` and consume it here.
3. **Save catalog searches** as named collections (needs a store; the registry is
   in-process today).
4. **Wire the worker panels** — once workers are deployed, `/v1/tasks/{service}/{task_id}`
   can drive live job progress in the Overview.
5. **Export** a catalog selection to CSV/JSON for procurement or licence review.
