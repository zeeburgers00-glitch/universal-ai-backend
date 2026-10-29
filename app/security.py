import os
import secrets

from fastapi import Header, HTTPException


def require_api_key(x_api_key: str | None = Header(default=None)) -> bool:
    """Protect billable and write endpoints using a server-side shared secret."""
    expected = os.getenv("BACKEND_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Backend API key is not configured on the server",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return True
