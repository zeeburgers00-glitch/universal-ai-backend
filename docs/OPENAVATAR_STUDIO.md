# OpenAvatar Studio implementation

OpenAvatar Studio is a no-card-first job control plane added to the Universal AI Backend.
It is not an unlimited GPU host. It routes work to a small set of explicitly configured
workers and has no paid GPU provider or automatic paid fallback.

## Included capabilities

- FastAPI routes for asset upload, job creation/list/status, quota, model/provider registry,
  worker heartbeat, job claim, artifact upload, completion and failure.
- SQLite job/asset/worker/usage tables with atomic job claims and 180-second worker leases.
- Hugging Face ZeroGPU: manual Gradio Space worker for SadTalker portrait-to-talking-head
  generation; one job per button click.
- Kaggle: optional manual, one-job worker. Backend rejects commercial jobs routed to Kaggle.
- Lightning AI: optional manual, one-job worker; disabled unless both server-side opt-in
  flags are set. The worker also requires a local no-card/free-credit attestation.
- Local CPU worker for whisper.cpp transcription/subtitles and FFmpeg video/audio muxing.
- Strict worker-token authentication, file type and upload-size checks, safe fixed CLI
  arguments, model license registry, consent confirmation for face/video animation.

## No-card defaults

The defaults are deliberately restrictive:

| Setting | Default | Meaning |
|---|---:|---|
| OPENAVATAR_HF_ENABLED | true | Use the shared free ZeroGPU Space worker |
| OPENAVATAR_HF_DAILY_BUDGET_SECONDS | 270 | Conservative local budget against the documented 300-second free quota |
| OPENAVATAR_HF_MAX_JOB_SECONDS | 60 | Keep a single job inside the default ZeroGPU function duration |
| OPENAVATAR_KAGGLE_ENABLED | false | Kaggle worker must be enabled explicitly |
| OPENAVATAR_LIGHTNING_ENABLED | false | Lightning worker disabled |
| OPENAVATAR_LIGHTNING_NO_CARD_CONFIRMED | false | Explicit account-level no-card confirmation required |
| OPENAVATAR_DATA_DIR | /tmp/openavatar-studio | Ephemeral local default; use a persistent volume for real jobs |

The backend does not call a billing API, does not ask for card details, and does not
automatically switch to a paid GPU. A free provider can still change its quota, suspend
accounts, or become unavailable. Hugging Face is the authority for actual ZeroGPU usage;
the 270-second quota is only this backend's conservative local guard.

Lightning currently documents no-card account creation and conditional introductory
GPU credits/hours after phone verification. It is unavailable in some countries, and the
free allocation can change. Leave the adapter disabled unless the account's own console
clearly shows the selected GPU is free and no payment card is attached.

Kaggle use is limited to personal/non-commercial work under Kaggle's terms. The backend
enforces commercial_use=false for Kaggle jobs. Do not use Kaggle as a customer-facing
commercial worker.

## Install and run locally (Windows PowerShell)

Python 3.11+ is required. The main API uses only dependencies already declared by the
backend project; model engines are installed separately on each worker.

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    Copy-Item .env.example .env

Set the following values in the backend process environment (or add them to .env):

    BACKEND_API_KEY=<long random API secret>
    OPENAVATAR_WORKER_TOKEN=<a different random secret, at least 32 characters>
    OPENAVATAR_DATA_DIR=D:\openavatar-data
    OPENAVATAR_HF_DAILY_BUDGET_SECONDS=270
    OPENAVATAR_HF_MAX_JOB_SECONDS=60

Start the backend:

    uvicorn app.main:app --host 0.0.0.0 --port 8000

For an HF Space to reach a local backend, it needs a public HTTPS endpoint. A temporary
tunnel is suitable for testing only; it is not a reliable production hosting solution.
Never expose the API without BACKEND_API_KEY and OPENAVATAR_WORKER_TOKEN.

## Persistent storage warning

The default /tmp path is ephemeral. Vercel functions also have ephemeral, instance-local
filesystem semantics. Do not use this SQLite default for production job durability on
Vercel. Run the backend on a machine or service with a persistent mounted volume, or
replace the storage layer with an authenticated persistent database and object storage.
No hosting provider is provisioned by this change.

## API

All user-facing write/read endpoints require X-API-Key.

### Upload a portrait (raw bytes, not multipart)

    curl -X POST "https://YOUR_API/v1/openavatar/assets?kind=portrait" \
      -H "X-API-Key: YOUR_BACKEND_API_KEY" \
      -H "X-Filename: portrait.png" \
      -H "Content-Type: image/png" \
      --data-binary "@portrait.png"

Repeat with kind=audio and audio/wav (or another accepted audio MIME type).

### Create a talking-head job

    curl -X POST "https://YOUR_API/v1/openavatar/jobs" \
      -H "X-API-Key: YOUR_BACKEND_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "job_type": "talking_head",
        "provider": "huggingface_zerogpu",
        "image_asset_id": "PORTRAIT_ASSET_ID",
        "audio_asset_id": "AUDIO_ASSET_ID",
        "consent_confirmed": true,
        "commercial_use": false,
        "max_gpu_seconds": 60,
        "options": {"size": 256, "preprocess": "crop"}
      }'

Use the returned job_id with GET /v1/openavatar/jobs/{job_id}. Download the output from
GET /v1/openavatar/jobs/{job_id}/artifact after status becomes completed.

### Available job types

- talking_head: SadTalker; portrait image + audio; default route is Hugging Face ZeroGPU.
- lip_sync: MuseTalk adapter contract; source video + audio; requires a separately reviewed
  OPENAVATAR_MUSETALK_ADAPTER module on the selected worker.
- transcribe: whisper.cpp; audio → plain-text transcript; default route local_cpu.
- captions: whisper.cpp; audio → SRT subtitles; default route local_cpu.
- render: FFmpeg; video + audio → MP4; default route local_cpu.

Provider routing:
- talking_head with provider=auto selects Hugging Face ZeroGPU.
- voice, transcribe, captions, and render with provider=auto select local_cpu.
- lip_sync with provider=auto selects Kaggle only when explicitly enabled, otherwise
  Lightning only when both no-card flags are explicitly enabled. If neither optional
  GPU worker is enabled, the API returns 503 rather than queueing a job to the wrong Space.
- Provider/engine combinations are validated before a job is queued.

For a Kaggle experiment, set provider=kaggle and commercial_use=false. Enable the worker
server-side with OPENAVATAR_KAGGLE_ENABLED=true. For Lightning, both explicit server flags
must be true and the worker must confirm no-card/free-credit-only operation.

## Worker protocol

Workers use X-OpenAvatar-Worker-Token, not the public backend API key.

- POST /internal/openavatar/heartbeat
- POST /internal/openavatar/jobs/claim
- POST /internal/openavatar/jobs/{job_id}/heartbeat
- GET /internal/openavatar/assets/{asset_id}
- PUT /internal/openavatar/jobs/{job_id}/artifact
- POST /internal/openavatar/jobs/{job_id}/complete
- POST /internal/openavatar/jobs/{job_id}/fail

Job claims are atomic and leased for 180 seconds. Long-running workers renew their lease every 45 seconds. A worker must upload an artifact before marking a job completed.
Expired jobs fail closed and the reserved ZeroGPU budget is conservatively counted as used.
Workers process one job and exit; no hidden keepalive loop is included.

## Model installation

SadTalker is invoked through its upstream inference.py CLI. Set SADTALKER_ROOT to a
prepared checkout with dependencies and checkpoints. This repository does not download
or bundle pretrained weights.

For OpenVoice V2, install the upstream repository and write a reviewed adapter exposing:

    generate(text, reference_audio_path, output_path, options) -> output_path

Configure OPENAVATAR_OPENVOICE_ADAPTER=your_adapter_module:generate. The API requires a
voice consent confirmation and a reference audio asset. Its current native language list
does not establish Urdu support; test the intended language and the selected model.

For MuseTalk, install the upstream repository and write a reviewed adapter exposing:

    generate(video_path, audio_path, output_path, options) -> output_path

Configure OPENAVATAR_MUSETALK_ADAPTER=your_adapter_module:generate. Do not enable a model
until its exact checkpoint, dependency and dataset terms have been reviewed.

For CPU transcription, install whisper.cpp and set WHISPER_CPP_BIN and WHISPER_CPP_MODEL.
For muxing, install FFmpeg and optionally set FFMPEG_BIN.

## Security and privacy

- Use only faces, videos and voices you own or have permission to process.
- Keep both API secrets server-side. Never put them into browser JavaScript.
- Do not accept arbitrary shell commands, Python source, or model URLs from jobs.
- Worker token is shared by the configured worker pool; rotate it if any worker is lost.
- Input assets and output artifacts are stored locally; configure a persistent volume and
  implement retention/deletion policies before accepting other users' private media.
- The current API key model is a single shared backend key, not per-user tenant isolation.
- The backend is an orchestration layer; it is not a substitute for legal review of
  likeness, voice, model, checkpoint, dataset, stock media, or generated content rights.

## Official provider references

- Hugging Face ZeroGPU: https://huggingface.co/docs/hub/spaces-zerogpu
- Hugging Face Spaces as API endpoints: https://huggingface.co/docs/hub/spaces-api-endpoints
- Kaggle notebooks: https://www.kaggle.com/docs/notebooks
- Kaggle GPU usage: https://www.kaggle.com/docs/efficient-gpu-usage
- Kaggle terms: https://www.kaggle.com/terms
- Lightning AI Studio: https://lightning.ai/docs/platform/build/ai-studio
- Lightning pricing: https://lightning.ai/pricing
- SadTalker CLI: https://github.com/OpenTalker/SadTalker#3-quick-start
- MuseTalk: https://github.com/TMElyralab/MuseTalk
- Whisper.cpp: https://github.com/ggml-org/whisper.cpp
- FFmpeg licensing: https://ffmpeg.org/legal.html
