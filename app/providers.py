import os
from typing import Any

import httpx


async def chat_with_openai_compatible(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 1024,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Proxy a chat request to an explicitly configured OpenAI-compatible endpoint.

    The endpoint comes from server configuration, not a client-supplied URL, to
    reduce server-side request forgery (SSRF) risk.
    """
    api_key = os.getenv("AI_API_KEY", "").strip()
    endpoint = (base_url or os.getenv("AI_BASE_URL", "")).strip().rstrip("/")
    if not api_key:
        raise ValueError("AI_API_KEY is not configured")
    if not endpoint:
        raise ValueError("AI_BASE_URL is not configured")
    if not endpoint.startswith(("https://", "http://")):
        raise ValueError("AI_BASE_URL must use http:// or https://")

    url = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
    payload: dict[str, Any] = {
        "model": model or os.getenv("AI_DEFAULT_MODEL", ""),
        "messages": messages,
        "temperature": temperature,
    }
    if not payload["model"]:
        raise ValueError("Set model in request or configure AI_DEFAULT_MODEL")
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    timeout = httpx.Timeout(90.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


def provider_status() -> dict[str, Any]:
    return {
        "providers": [
            {
                "id": "openai_compatible",
                "label": "OpenAI-compatible endpoint",
                "ready": bool(os.getenv("AI_API_KEY") and os.getenv("AI_BASE_URL")),
                "required_env": ["AI_BASE_URL", "AI_API_KEY"],
                "optional_env": ["AI_DEFAULT_MODEL"],
                "notes": "Can connect to a compatible hosted API or a separately reachable self-hosted endpoint.",
            },
            {
                "id": "ollama",
                "label": "Ollama / local models",
                "ready": False,
                "required_env": ["A reachable Ollama endpoint and adapter configuration"],
                "notes": "The Vercel function cannot access a model running only on your Windows PC; expose a properly secured remote service or run this backend locally.",
            },
        ]
    }
