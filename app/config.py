"""Environment loading for the control plane.

The project ships ``.env.example``.  Docker Compose injects keys via
``env_file``/``environment``, and hosted platforms (Vercel, Modal, RunPod)
inject them as real environment variables.  But a plain local run --

    uvicorn app.main:app --reload

-- previously ignored a filled-in ``.env`` completely, because nothing ever
called ``load_dotenv``.  That made a correctly configured machine look broken:
``/v1/models/providers`` reported zero ready providers even though the keys
were sitting in ``.env``.

``load_env_file`` fixes that.  Real environment variables always win
(``override=False``) so a container's injected secrets are never clobbered by a
stale file on disk.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Repository root -- this file lives at ``<repo>/app/config.py``.
REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: str | os.PathLike[str] | None = None, override: bool = False) -> list[str]:
    """Load a dotenv file if it exists and return the keys it contributed.

    Missing files are not an error: production deployments simply have no
    ``.env`` on disk.  A missing ``python-dotenv`` install is also tolerated so
    the app still imports with a minimal dependency set.
    """

    candidate = Path(path) if path is not None else REPO_ROOT / ".env"
    if not candidate.is_file():
        return []

    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover - python-dotenv is a declared dep
        return []

    loaded: list[str] = []
    for key, value in dotenv_values(candidate).items():
        # `KEY=` yields "" -- treat blanks as "not set" so an empty line cannot
        # shadow a real value further down the chain.
        if not key or not value:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


def load_local_env() -> list[str]:
    """Load the repository ``.env`` (if present). Called on package import."""

    return load_env_file(REPO_ROOT / ".env", override=False)
