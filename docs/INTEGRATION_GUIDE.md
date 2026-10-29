
# Integration and deployment guide

## One repository, multiple runtimes

This project uses a single Git repository for the control plane and service code. Vercel serves `app.main:app`, while persistent queues, GPU models, large media files and Windows desktop actions run in worker services from `workers/`. Vercel Functions should not be used as long-running GPU model hosts; see https://vercel.com/docs/functions/limitations.

The API returns worker readiness at `GET /v1/runtime/capabilities`. A worker is ready only when its URL and shared worker secret are configured in Vercel. Even that check is configuration-only: check each worker's own `/health` and test a small job before production.

## Service map

| Runtime | Source directory | Purpose | State |
|---|---|---|---|
| Vercel control plane | `app/` | Catalog, provider routing, approval gates and worker gateway | Deploy this on Vercel |
| GPU voice | `workers/voice_worker/` | F5-TTS CLI, MeloTTS, reference assets and async TTS | Concrete adapter scaffold; needs GPU/model/rights verification |
| Media | `workers/media_worker/` | Asset upload, FFmpeg presets, ComfyUI workflow dispatch, ASR hook | FFmpeg path is implemented; ComfyUI and ASR need config |
| YouTube | `workers/youtube_worker/` | OAuth-backed official video upload | Needs owner's OAuth credentials, quota and authorized channel |
| Messaging channels | `workers/channel_worker/` | Telegram, Discord, Slack and WhatsApp templates | These four adapters are present; other catalog items remain manifests |
| Agent planner | `workers/agent_worker/` | Generate validated JSON action plans from an LLM | Planner only; it never executes arbitrary model-produced code |
| Workflow dispatcher | `workers/automation_worker/` | Plan workflows or dispatch explicitly declared allowlisted actions | Requires typed `inputs.actions` and approval for dispatch |
| Windows desktop | `workers/windows_agent/` | Run a restricted set of actions on a paired local PC | Must run on the user's Windows PC, not Vercel |

## Deploy workers on a Linux host

1. Create a private environment file from `workers/.env.workers.example`.
2. Set unique `REDIS_PASSWORD`, per-service worker API keys, and only the provider/OAuth secrets required by your intended features.
3. On a host with Docker Compose, install NVIDIA drivers and the NVIDIA Container Toolkit if you need the F5-TTS GPU runner.
4. Run:

```bash
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml up --build -d
docker compose --env-file workers/.env.workers -f workers/docker-compose.yml ps
```

5. Expose selected loopback-only worker ports through private networking or an HTTPS reverse proxy/tunnel. Do not expose raw ports 8100, 8200, 8300, 8400, 8500 or 8600 to the public internet.
6. Set Vercel variables `VOICE_WORKER_URL`, `MEDIA_WORKER_URL`, `YOUTUBE_WORKER_URL`, `CHANNEL_WORKER_URL`, `AGENT_WORKER_URL`, `AUTOMATION_WORKER_URL` and the matching `*_WORKER_API_KEY` secrets. The external URL must be HTTPS.
7. Set the Vercel `BACKEND_API_KEY`, model provider credentials and exact `CORS_ORIGINS`. Never put these secrets in frontend code or Git.
8. Check `/v1/runtime/capabilities`, `/v1/workers/status` and the worker health endpoint for every configured service. Then make one small test job.

The Compose file uses internal DNS for worker-to-worker calls. The Vercel control plane needs a secure HTTPS address for every worker it directly contacts. The local Windows agent is separate and needs its own secure connection.

## Voice and consent

- Upload a reference sample with `POST /v1/voice/assets`, using a Base64-encoded small audio file and a consent-record ID.
- Create a reference voice profile with `POST /v1/voice/clone`.
- Request audio with `POST /v1/voice/tts`, then poll `GET /v1/tasks/voice/{task_id}` and fetch `GET /v1/voice/results/{task_id}`.
- The GPU worker currently implements F5-TTS and MeloTTS. The other listed voice engines are catalog candidates until their specific adapter/runtime has been installed and tested.
- F5-TTS code and model weights have separate license terms. Upstream describes its standard pretrained weights as CC-BY-NC. For commercial publishing, supply a compatible model/checkpoint with independently verified commercial rights; do not set the commercial-approved flag merely to bypass the gate.
- The code records a consent ID and checks that ID matches the uploaded asset/profile. A production service must additionally keep reliable consent evidence, authenticate the account/speaker and support revocation/deletion.

## Media and YouTube

- Upload larger media directly to the secured media worker at `POST /v1/assets/upload`; don't push large videos through Vercel Functions.
- Media worker's built-in FFmpeg presets are standard render, short-vertical crop, compression, audio extraction/normalization, thumbnail capture and SRT subtitle burn-in.
- Generative image/video/audio requires a configured ComfyUI endpoint and reviewed API-format workflow JSON in the worker's persistent `/data/workflows` folder.
- Transcription is delegated to an explicitly configured `ASR_WORKER_URL`.
- YouTube publishing expects a media-worker asset ID, a configured OAuth refresh token and a matching channel connection ID. Only publish after a human approves the exact upload request. The implementation checks the channel ID returned by the OAuth token before upload.
- Verify YouTube quota and API terms on the official docs: https://developers.google.com/youtube/v3/docs/videos/insert.

## Agent planner and workflow dispatcher

- `POST /v1/agents/{agent_id}/run` creates a task that returns a validated JSON plan. Planning is not execution.
- `POST /v1/workflows/{workflow_id}/run` returns the registered workflow as a plan. To dispatch tasks, send an explicit `inputs.actions` array using one of the fixed action types: `voice_tts`, `voice_clone`, `media_job`, `youtube_publish`, `channel_action` or `desktop_action`.
- The dispatcher accepts no caller-supplied URLs or shell/code tool. YouTube posts, external messages, voice cloning and desktop actions require approval/consent again at their destination worker.
- Dispatch responses may contain downstream task IDs. A response saying `dispatched` means an action has been queued/sent, not that a GPU render or public upload has completed.
- Multi-account deployments should implement per-tenant authentication, encrypted OAuth stores and durable approval/audit records before external use. The starter uses server-side worker secrets and a single configured YouTube channel connection.

## Registering another tool

1. Search live GitHub metadata via `GET /v1/discover/github?q=...`.
2. Review the upstream code license, model/checkpoint license, dependencies, maintenance/security posture, required hardware and hosted-service terms.
3. Add a metadata entry to `catalog/tools.json` or a new documented manifest.
4. Implement a typed adapter or worker route, pinned dependencies, tests, permissions and timeouts.
5. Mark the entry executable only after testing its exact installation and runtime on a supported host. Do not auto-install or execute arbitrary GitHub repositories from the API process.

## Licensing distinctions

A project source license, model weights, training data, bundled voice/checkpoint assets and the vendor's hosted API are different rights. Source-available/fair-code and open-core terms are not necessarily OSI-approved open source. The catalog marks candidates `license_status=review_required` until an upstream legal review is recorded.
