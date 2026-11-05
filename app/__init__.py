"""Universal AI Backend application package."""

from app.config import load_local_env

# Load a developer's local .env before any submodule reads os.environ at import
# time (data roots, worker URLs, provider keys). Real env vars always win.
load_local_env()

__all__ = ["load_local_env"]
