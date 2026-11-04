# Universal AI Empire — 3D Frontend

A private Next.js command centre built with React, Three.js, React Three Fiber and Drei. All 3D objects are procedural; no paid models, fonts or stock artwork are required.

## Local setup

Requires Node.js 20.9+.

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The application runs at http://localhost:3000.

## Required server-side environment variables

Set these only in the hosting provider's encrypted/server-side environment. Do not use `NEXT_PUBLIC_` for any of them.

- `BACKEND_API_URL`: the public Railway HTTPS origin (no trailing slash).
- `BACKEND_API_KEY`: backend shared API key.
- `DASHBOARD_PASSWORD`: unique strong password for the private dashboard.
- `DASHBOARD_SESSION_SECRET`: random secret with at least 32 characters.

The backend proxy is intentionally allow-listed to `campaigns/content-agency` routes and requires a signed, HTTP-only session cookie. The browser never receives the backend key. A manual approval record does not trigger email, DM, contact-form submission or publishing.

## Hosting

Vercel project root directory: `frontend`; framework: Next.js. This repository already contains several Vercel projects using a Hobby team. Vercel Hobby's official terms restrict commercial usage to personal, non-commercial projects. Do not deploy this business dashboard to that Hobby plan; switch to an eligible commercial Vercel plan only after the owner approves the cost, or choose another host whose free terms allow commercial use.

## Checks

```bash
npm run typecheck
npm run build
```

No lockfile is included in this initial scaffold. Use `npm install` to generate and commit one before a production release; do not use `npm install --force` to hide peer dependency conflicts.
