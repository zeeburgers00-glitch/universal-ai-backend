# AutoTube AI Studio — Chat frontend

The only user-facing interface is a ChatGPT-style chat. Agent catalogues, production orchestration, provider adapters, tool discovery, Metricool integration and worker controls stay in the backend. The chat shows durable task activity events and final outputs.

## Vercel

- Project root directory: `autotube`
- Framework: Vite
- Static page: `index.html`
- Server-side API proxy: `api/chat.js`

Set these Vercel environment variables (server-side only; do not prefix them with `VITE_`):

- `BACKEND_API_URL`: public HTTPS URL of the FastAPI backend
- `BACKEND_API_KEY`: the same secret configured as `BACKEND_API_KEY` on FastAPI

The browser calls `/api/chat`; the proxy attaches the backend key server-side. The key must never be placed in HTML, localStorage, JavaScript bundles, or any `VITE_*` variable.

## Backend and worker

See [chat-first architecture](../docs/CHAT_FIRST_ARCHITECTURE.md). The backend needs Supabase, Redis/Celery, an AI provider key and the dedicated autopilot worker. The Vercel page can render before the backend is deployed, but it will report that the backend is not connected until `BACKEND_API_URL` and `BACKEND_API_KEY` are configured.

## Metricool / YouTube

Connect the existing YouTube channel inside Metricool using the channel Owner account. Configure Metricool API credentials only on backend hosts. Metricool's API requires an Advanced or Custom plan. Channel creation itself still requires the official YouTube user interface.
