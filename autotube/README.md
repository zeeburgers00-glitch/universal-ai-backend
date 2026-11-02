# AutoTube AI Studio

Frontend for the Universal AI Backend YouTube automation workspace.

## Vercel
Create a separate Vercel project linked to this repository and set Root Directory to `autotube`. The frontend is a static HTML app. Set `VITE_API_BASE_URL` to the public HTTPS origin of the Railway/Render FastAPI service when backend routes are ready.

## Services
- Frontend: Vercel (this directory)
- Backend: Railway or Render using the existing FastAPI app at repository root
- GPU: RunPod worker endpoints for FFmpeg, Whisper/faster-whisper, TTS and optional generative video
- Data: Supabase Postgres and private Storage buckets

## Secrets
Set credentials only on trusted backend/worker hosts: BACKEND_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, TOKEN_ENCRYPTION_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID, AI_API_KEY, PEXELS_API_KEY, CORS_ORIGINS. Never put private secrets in frontend environment variables.

## Honest integration state
This is the initial frontend shell. UI setup states do not mean integrations are live. OAuth routes, Supabase project credentials, RunPod worker and API deployment must be configured and tested separately. YouTube Data API has no general channel-creation endpoint; first-time channel creation needs the official YouTube UI. Some branding changes may also require YouTube Studio. Autopublish must remain disabled until the channel owner explicitly enables it.