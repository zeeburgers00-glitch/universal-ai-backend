# Media worker

This worker provides:
- authenticated streaming asset uploads with server-generated asset IDs and metadata;
- async media jobs via Celery/Redis;
- fixed, allowlisted FFmpeg presets for vertical short rendering, standard rendering, compression, audio extraction/normalization, thumbnails, and SRT subtitle burn-in;
- ComfyUI dispatch through reviewed server-side workflow JSON files under `/data/workflows`, with template tokens `{{PROMPT}}`, `{{NEGATIVE_PROMPT}}`, and `{{SEED}}`;
- a separate ASR worker hook for transcription.

## Configuration

Set `MEDIA_WORKER_API_KEY`, a private `CELERY_BROKER_URL`, and optionally `COMFYUI_BASE_URL`, `COMFYUI_API_KEY`, `COMFYUI_JOB_TIMEOUT_SECONDS`, `ASR_WORKER_URL`, and `ASR_WORKER_API_KEY`. In Vercel, set `MEDIA_WORKER_URL` and `MEDIA_WORKER_API_KEY` to the secure HTTPS endpoint for this worker.

Upload large media directly to this worker from a trusted server or signed upload flow. Do not send multi-gigabyte files through a Vercel Function. The worker uses a persistent mounted volume; protect the volume, uploaded assets and workflow templates.

## ComfyUI workflow templates

Place reviewed API-format workflow JSON files in `/data/workflows/{workflow_id}.json`. Put the exact string `{{PROMPT}}` into the positive text node, `{{NEGATIVE_PROMPT}}` into the negative text node, and `{{SEED}}` in a seed field. The caller may supply only a workflow ID, text prompt, negative prompt and seed; it cannot supply an arbitrary ComfyUI base URL or workflow graph. Review templates/models/custom nodes before making them callable.

This worker does not bundle model weights or every custom node. Image/video/music models still require a GPU-capable ComfyUI host and individual model license review.
