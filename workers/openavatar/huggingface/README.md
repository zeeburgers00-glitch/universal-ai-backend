---
title: OpenAvatar Studio ZeroGPU Worker
emoji: 🎬
colorFrom: blue
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
---

# OpenAvatar Studio — Hugging Face ZeroGPU worker

This is a worker, not the full web application. The main OpenAvatar API remains in
the Universal AI Backend repository. A worker claims one queued job when a user clicks
the button, runs SadTalker in a ZeroGPU allocation, and uploads the result to the API.

## No-card setup

1. Create a free personal Hugging Face account, verify its email, and make sure it is
   eligible to host a ZeroGPU Space (the official documentation currently requires
   an account in good standing and at least 30 days old).
2. Create a new Gradio Space and choose ZeroGPU hardware.
3. Copy app.py and requirements.txt from this directory into the Space repository.
4. In Space Settings → Variables and secrets, add:
   - OPENAVATAR_API_URL: public HTTPS base URL of the OpenAvatar backend.
   - OPENAVATAR_WORKER_TOKEN: the same 32+ character worker token configured on the backend.
   - OPENAVATAR_WORKER_ID: a stable unique ID, e.g. hf-zero-1.
   - SADTALKER_ROOT: path to the prepared SadTalker checkout, e.g. /app/SadTalker.
5. Install SadTalker and its checkpoints using the upstream installation instructions.
   Do not assume the code license also covers every checkpoint or dependency.
6. Open the Space and click Process one queued job when you want to use the free GPU quota.

## Model installation

The Space requires a prepared SadTalker checkout with inference.py, its upstream
requirements and checkpoints. This repo intentionally does not bundle model weights.
Use the upstream release/checkpoint instructions and verify license terms for each file.
The worker invokes the upstream CLI with fixed arguments; it never executes a command
provided by an API user.

The worker is intentionally single-job and user-triggered. It does not run an infinite
background poller, create a tunnel, or provision a paid GPU. The backend defaults to a
local 270-second/day safety budget against the current 300-second/day free-account
ZeroGPU allowance; Hugging Face remains the authority on actual quota.

## Supported workload

- talking_head + sadtalker: portrait image + audio → MP4.
- MuseTalk, voice cloning and full video diffusion are not enabled in this Space worker
  by default. Add a separately reviewed adapter only after validating upstream code,
  checkpoint, dependency and dataset licenses.

## Official references

- ZeroGPU: https://huggingface.co/docs/hub/spaces-zerogpu
- Spaces as API endpoints: https://huggingface.co/docs/hub/spaces-api-endpoints
- SadTalker CLI: https://github.com/OpenTalker/SadTalker#3-quick-start
