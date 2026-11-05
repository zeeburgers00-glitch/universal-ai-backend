# OpenAvatar Studio module

This directory adds a no-card-first OpenAvatar worker system to the Universal AI Backend.

- Kaggle: optional one-job manual worker for personal/non-commercial testing only.
- Lightning AI: optional one-job manual worker, disabled by default and requiring an
  explicit no-card/free-credit attestation.
- Hugging Face ZeroGPU: separate Gradio Space worker under huggingface/.
- Shared worker client: worker_client.py.

The central API queue and quota accounting live in app/openavatar.py. No paid GPU
provider is implemented or used as a fallback.
