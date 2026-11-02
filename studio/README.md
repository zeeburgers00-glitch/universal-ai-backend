# Vivid AI Studio

HeyGen-inspired creator workspace frontend for the existing Universal AI Backend.

## Local development

```bash
cd studio
npm install
npm run dev
```

## Vercel

Create a separate Vercel project from this repository and set Root Directory to `studio`. Framework: Vite. Build command: `npm run build`; output directory: `dist`.

Optional environment variable: `VITE_API_BASE_URL` for the hosted FastAPI backend URL.

The current UI provides workspace navigation, project drafts, creation settings and backend health checks. Avatar, voice, translation and rendering modules are staged interfaces; they are not yet live model inference. Connect licensed model workers, persistent storage and queue endpoints before enabling real generation. Never place secrets in `VITE_*` variables or frontend source.
