# Production go-live checklist

This checklist separates the code that is committed from services that must run with your own accounts, hardware and secrets. Do not mark the project production-ready until the runtime checks below pass.

## 1. Pull the current code

```powershell
git clone https://github.com/zeeburgers00-glitch/universal-ai-backend.git
cd universal-ai-backend
git pull origin main
```

If you already cloned it, use `git pull origin main`. Confirm the commit in your checkout using `git rev-parse HEAD`.

## 2. Start the API locally first (Windows)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Set a unique `BACKEND_API_KEY` of at least 32 random characters, one model provider key/base URL, and the exact `CORS_ORIGINS` for your app. Keep this key server-side; do not put it in browser JavaScript. For production, use only HTTPS app origins in `CORS_ORIGINS`.

Generate a strong random secret in PowerShell when needed:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Check configuration without printing secret values, then start the API:

```powershell
python scripts/preflight.py --env-file .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal run:

```powershell
python scripts/smoke_test.py http://127.0.0.1:8000
```

## 3. Deploy the control plane to Vercel

1. In Vercel, open the existing `universal-ai-backend` project connected to this GitHub repository. Keep the project root at the repository root and the FastAPI entry point configured as `app.main:app` via the repository's Vercel/Python configuration.
2. Add server-side Environment Variables from `.env.example` as needed: at minimum `BACKEND_API_KEY`, exact `CORS_ORIGINS`, and one provider's credentials/model settings. Add worker URLs and matching worker secrets only after the workers are running behind private networking or HTTPS.
3. Redeploy the `main` commit. In the deployment details, compare its commit SHA against the latest commit on GitHub `main`. A READY deployment of an older SHA is not a deployment of the latest code.
4. Run a read-only smoke test after the matching commit is deployed:

```powershell
python scripts/smoke_test.py https://universal-ai-backend.vercel.app --json
```

A successful smoke test confirms the listed GET routes respond; it does not validate provider billing, GPU inference or real publishing. If Vercel refuses a deployment because of the project's current deployment quota, don't repeatedly trigger deployments. Wait for the quota to reset or resolve the account/project quota issue, then redeploy and verify the commit SHA.

## 4. Deploy worker services

Use a separate Linux host for Redis/Celery, GPU inference, media files and queue workers. Vercel is the lightweight control plane, not the persistent GPU machine.

```powershell
Copy-Item workers/.env.workers.example workers/.env.workers
notepad workers/.env.workers
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml config --quiet
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml up --build -d
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml ps
```

The commands above assume Docker Desktop/Compose is installed; GPU TTS additionally requires a compatible Linux GPU host, NVIDIA drivers and NVIDIA Container Toolkit. Configure new random, distinct secrets in `workers/.env.workers` before starting. Never commit this private env file.

The Compose file binds worker service ports to loopback. Expose the required services to Vercel through private networking or an authenticated HTTPS reverse proxy/tunnel; do not directly expose ports 8100–8600 to the public internet. Copy each worker's public/private HTTPS base URL and its matching API key into Vercel's Environment Variables. Then redeploy the control plane so updated Vercel variables take effect.

Run `python scripts/preflight.py --env-file .env --worker-env-file workers/.env.workers --strict-workers` only when all listed backend workers are intended to be configured. Use `--production` for production CORS/HTTPS checks.

## 5. Connect external providers and channels

- **LLM:** add a provider API key/model ID or a private, network-reachable OpenAI-compatible endpoint; verify one chat request from a trusted server using `POST /v1/chat/completions`.
- **YouTube:** create a Google Cloud project, enable the YouTube Data API, configure OAuth consent for the channel owner, create a refresh token, set the channel ID/connection ID and verify quota. First test with an unlisted/test asset and explicit human approval.
- **Telegram, Discord, Slack, WhatsApp:** configure each bot/app token, required permission scopes, approved connection ID and explicit target-ID allowlist. WhatsApp Cloud requires the correct phone-number ID, template and language where applicable.
- **ComfyUI/ASR:** host them separately, configure their private URLs and API credentials, and test a small reviewed workflow/audio fixture.
- **Windows JARVIS/REA:** install the Windows agent on the actual PC. Configure pairing and a private authenticated HTTPS connection. For REA, install a compatible Node.js version, install `rea-agents@6.8.0`, configure `REA_ENTRY_SCRIPT`, `REA_MCP_ENABLED=true`, a narrow `REA_ALLOWED_TARGET_ROOTS`, an explicit `REA_ALLOWED_URL_HOSTS`, and manually reviewed `REA_ALLOWED_TOOL_NAMES`. Leave the tool allowlist empty until the user reviews discovered tools. Runtime analysis is not a sandbox; analyze only authorized targets.

## 6. Security and persistence before real users

- Put authenticated user/tenant identity in front of action routes. The shared API key is a backend-to-backend starter gate, not end-user authentication.
- Store OAuth tokens and consent evidence in an encrypted, access-controlled persistent store; bind tasks, assets, approvals and logs to the owning tenant.
- Keep audit records for approvals, outbound messages, uploads and publishes; add retention/deletion policies and backups for Redis and asset storage.
- Limit provider spend, request rates, upload sizes, job concurrency and timeouts. Keep workers private; rotate secrets immediately if exposed.
- Review code/model/checkpoint licenses separately, including commercial-use rights. Catalog presence alone does not mean an integration or license is verified.

## 7. Final verification

Run both checks after changes:

```powershell
python -m compileall -q app workers tests scripts
python -m pytest -q
```

Then run the deployed smoke test and manually verify at least one successful provider response, one queued worker job, task polling/result retrieval, one approved channel test and one approved YouTube upload before claiming end-to-end readiness.

**Status semantics:** CI green = repository checks passed. Vercel READY = that deployment built. Smoke test green = listed read endpoints responded. Only successful real worker/provider integration tests establish those integrations are operational.
