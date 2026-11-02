# AI YouTube Studio Autopilot

Next.js App Router frontend for the AI YouTube Studio Autopilot product.

## Local development

1. Copy .env.example to .env.local and set the Supabase project URL, anon key, and Fastify API URL.
2. Configure Supabase Auth email OTP and set the allowed redirect URL to your local origin.
3. Run npm install, then npm run dev.
4. Open http://localhost:3000.

## Vercel

Set the project root directory to studio and framework preset to Next.js. Add these variables:
- NEXT_PUBLIC_SUPABASE_URL
- NEXT_PUBLIC_SUPABASE_ANON_KEY
- NEXT_PUBLIC_API_BASE_URL

Only the Supabase anon key may be public. Never add provider keys, the Google OAuth client secret, Supabase service-role key or token-encryption key to NEXT_PUBLIC variables.

## Backend

The Fastify API and BullMQ worker live under services/youtube-api and services/youtube-worker. Apply database/migrations/202611020001_youtube_studio.sql before connecting the app. Read docs/YOUTUBE_STUDIO_ARCHITECTURE.md for OAuth, provider and deployment setup.

The user interface calls authenticated API endpoints and reports the backend's actual job and channel state. It does not claim a video is generated or uploaded until the worker and YouTube API confirm success.
