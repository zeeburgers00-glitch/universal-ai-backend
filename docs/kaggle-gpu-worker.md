# Kaggle GPU worker integration (ViMax / Universal AI Backend)

## Important operating model

Kaggle Notebooks are ephemeral compute sessions, not an always-on production GPU server. Use this worker for burst/batch inference and development. Keep the durable API, authentication, job queue, job state, and storage on Railway (or another always-on service). The Vercel frontend should call the Railway API, never Kaggle directly.

Kaggle's documented free GPU availability is quota- and capacity-limited. The current Kaggle docs describe a weekly GPU quota (commonly around 30 hours, subject to change), session runtime limits, and GPU availability queues. Check the account's live quota in Kaggle before each run.

## Recommended flow

1. Vercel submits a job to Railway.
2. Railway validates the user, stores the job, and places it in a queue.
3. A Kaggle Notebook started by the account polls an authenticated Railway worker endpoint for jobs.
4. The notebook runs the approved model on its attached GPU.
5. The notebook posts the result/status back to Railway.
6. Railway stores output in durable object storage and returns a result URL to Vercel.

Do not expose a Kaggle notebook's Jupyter server or an unauthenticated tunnel as a public production API. Do not put secrets in notebook source or public outputs.

## Kaggle setup

1. Open https://www.kaggle.com/code and create a private notebook.
2. In Notebook Settings, choose Accelerator: GPU. The actual GPU model is assigned by Kaggle and may vary.
3. Add credentials using Kaggle Secrets (not source code):
   - `BACKEND_URL`: the Railway API base URL.
   - `WORKER_TOKEN`: a dedicated, revocable worker token issued by the backend.
4. Install only the model/runtime dependencies needed by the selected workload.
5. Start the worker loop only after the backend implements the authenticated claim/complete endpoints below.

## Backend contract to implement

- `POST /internal/gpu-workers/heartbeat` — authenticate worker, report status and available GPU metadata.
- `POST /internal/gpu-jobs/claim` — atomically claim one queued job; return 204/empty when none are available.
- `POST /internal/gpu-jobs/{job_id}/complete` — submit result metadata and durable output location.
- `POST /internal/gpu-jobs/{job_id}/fail` — submit a bounded error summary.

Requirements:
- Require a dedicated bearer token; store only its hash; support rotation/revocation.
- Validate job type and payload schema; never execute arbitrary user-supplied code.
- Use leases/heartbeats and idempotency so a disconnected Kaggle session does not leave jobs stuck.
- Store large inputs/outputs in object storage; send signed, short-lived URLs through the queue.
- Enforce per-user limits, file-size limits, timeouts, and audit logs.
- Treat Kaggle as an optional worker pool. If no worker is online, queue the job or route to CPU/another configured provider.

## Workload fit

- Whisper transcription and subtitle generation: good GPU-worker candidates.
- PyTorch-compatible LLM inference: possible, depending on model size and assigned GPU memory.
- F5-TTS / voice cloning: possible only after checking model license, GPU memory, runtime dependencies, and consent requirements.
- FFmpeg: most routine editing is CPU/I/O-bound; use GPU only for supported encode/decode filters.
- Large video generation models: often exceed free notebook memory/runtime; benchmark before promising this capability.

## Official docs

- Kaggle Notebooks: https://www.kaggle.com/docs/notebooks
- Efficient GPU usage and quota guidance: https://www.kaggle.com/docs/efficient-gpu-usage

This document is an integration plan, not a claim that the Railway endpoints or Kaggle worker are already deployed.