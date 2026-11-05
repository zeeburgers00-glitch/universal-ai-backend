"""Vercel serverless entry point for the FastAPI backend.

Vercel's Python runtime looks for an ASGI/WSGI callable in the file it builds, so this
module simply re-exports the app after adjusting the two things a serverless sandbox
changes:

* the filesystem is read-only except ``/tmp`` — so the data root moves there;
* there is no long-lived process, so background job workers must not start. The queue
  still works: ``POST /v1/jobs/{id}/…`` remains usable via ``POST /v1/jobs/run-once``
  (a cron or a client tick), and that trade-off is documented in docs/JOB_QUEUE.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("UAI_DATA_ROOT", "/tmp/uai-data")
os.environ.setdefault("UAI_JOBS_DISABLE", "1")
os.environ.setdefault("UAI_SERVERLESS", "1")

from app.main import app  # noqa: E402  (import after the environment is set)

__all__ = ["app"]
