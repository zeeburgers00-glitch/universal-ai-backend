# AutoTube AI multi-service deployment

1. Vercel: deploy `autotube/` as a separate project; set Root Directory to `autotube`.
2. Railway or Render: deploy existing FastAPI app from repository root using railway.toml or render.yaml.
3. RunPod: deploy isolated GPU worker containers for FFmpeg, Whisper, TTS and optional generative video. API queues jobs and stores state; workers use private Supabase Storage for media.
4. Supabase: Postgres for users, OAuth metadata, channels, brand kits, research topics, video jobs, agent tasks, schedules, upload attempts and audit events. Storage buckets must be private.

Security: encrypt Google refresh tokens server-side; keep RunPod and Supabase service-role credentials only on backend/worker hosts; enable RLS on exposed tables; use resumable YouTube uploads, idempotency keys, bounded retries and audit logs. Daily publishing must require explicit opt-in and be paused by default.

First deploy checklist:
- Deploy API on Railway/Render and verify /health.
- Create Supabase project in the owner's chosen organization and configure database/storage.
- Configure Google Cloud OAuth consent, YouTube Data API v3 and redirect URI.
- Deploy RunPod worker and verify GPU/FFmpeg/Whisper/TTS health checks.
- Create Vercel project with root directory autotube.
- Test OAuth callback, private media uploads, job state transitions and YouTube resumable upload in a private test channel before enabling autopublish.
