# Publishing the GPU voice worker image to GHCR

## Why this file lives here and not in `.github/workflows/`

GitHub refuses pushes that create or modify files under `.github/workflows/`
unless the token doing the push has the **`workflows`** scope. The automation
token used on this branch does not have it, so the workflow ships one folder
away and you install it with two commands.

Nothing is broken by this — the file is a normal GitHub Actions workflow, it
just needs to be moved into place by someone with the right permission.

## Install it (30 seconds)

From a clone of this repo:

```bash
mkdir -p .github/workflows
cp deploy/ghcr/voice-worker-image.yml .github/workflows/
git add .github/workflows/voice-worker-image.yml
git commit -m "ci: publish the voice worker image to GHCR"
git push
```

Or paste the file through the GitHub web UI:
**Add file → Create new file →** `.github/workflows/voice-worker-image.yml`,
paste the contents, commit.

## What it does

`workers/voice_worker` is the only CUDA image in the repository
(`pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` + F5-TTS + MeloTTS). Building it
takes 10-20 minutes and several GB of downloads.

This workflow builds it on a free GitHub runner and pushes to GitHub Container
Registry:

```
ghcr.io/<your-owner>/universal-ai-voice-worker:latest
ghcr.io/<your-owner>/universal-ai-voice-worker:<commit-sha>
```

Then a billed GPU pod pulls the image instead of compiling PyTorch.

### Important: GitHub runners have no GPU

Free GitHub-hosted runners are CPU-only. That is fine for **building** — a
Docker build does not need a GPU — but it cannot **run** the worker. GPU
execution needs `../kaggle/` (free, session-limited) or `../runpod/` (paid).

The repository's tests assert exactly this, so the workflow can never quietly
start pretending it has GPU capacity.

## Use the published image on RunPod

On the pod:

```bash
cd /workspace/universal-ai-backend/deploy/runpod
echo 'VOICE_WORKER_IMAGE=ghcr.io/<your-owner>/universal-ai-voice-worker:latest' >> .env
docker compose up -d --no-build
```

If the package is private, authenticate first:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u <your-github-username> --password-stdin
```

Making the GHCR package public avoids that step for workers that only ever talk
to your own API.

## Triggers

- **Manual**: Actions → *Build GPU voice worker image* → Run workflow.
- **Automatic**: any push to `main` that touches `workers/voice_worker/**`.

The build is cached with `type=gha`, so repeat builds take a fraction of the
time.
