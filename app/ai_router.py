"""One place that knows every model provider you have a key for.

The command layer does not care which vendor answers. It asks this router for
text, the router tries the configured providers in order, and the first one that
responds wins. If a provider is rate-limited, out of credit or simply down, the
next one takes over instead of the whole pipeline failing.

All of the providers below speak the same OpenAI-compatible chat API, which is
why one code path covers them all. Secrets are read through app.vault, so a key
saved at runtime via POST /v1/vault/secrets works exactly like one in .env.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from .security import require_api_key
from .vault import get_secret, get_secret_source

router = APIRouter(prefix="/v1/ai", tags=["ai-router"])

DEFAULT_ORDER = (
    "groq", "gemini", "mistral", "zai", "openrouter",
    "huggingface", "opencode_zen", "hackerai", "custom",
)


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    key_env: str
    model_env: str
    default_model: str
    base: str | None = None
    base_env: str | None = None
    note: str = ""


PROVIDERS: dict[str, Provider] = {
    "groq": Provider("groq", "Groq", "GROQ_API_KEY", "GROQ_DEFAULT_MODEL",
                     "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
    "gemini": Provider("gemini", "Google Gemini", "GEMINI_API_KEY", "GEMINI_DEFAULT_MODEL",
                       "gemini-2.0-flash", "https://generativelanguage.googleapis.com/v1beta/openai",
                       note="Uses Google's OpenAI-compatible endpoint."),
    "mistral": Provider("mistral", "Mistral AI", "MISTRAL_API_KEY", "MISTRAL_DEFAULT_MODEL",
                        "mistral-large-latest", "https://api.mistral.ai/v1"),
    "zai": Provider("zai", "Z.ai (GLM)", "ZAI_API_KEY", "ZAI_DEFAULT_MODEL",
                    "glm-4.6", "https://api.z.ai/api/paas/v4"),
    "openrouter": Provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "OPENROUTER_DEFAULT_MODEL",
                           "meta-llama/llama-3.3-70b-instruct", "https://openrouter.ai/api/v1"),
    "huggingface": Provider("huggingface", "Hugging Face Router", "HUGGINGFACE_API_KEY", "HUGGINGFACE_DEFAULT_MODEL",
                            "meta-llama/Llama-3.3-70B-Instruct", "https://router.huggingface.co/v1"),
    "opencode_zen": Provider("opencode_zen", "OpenCode Zen", "OPENCODE_ZEN_API_KEY",
                             "OPENCODE_ZEN_DEFAULT_MODEL", "", "https://opencode.ai/zen/v1"),
    "hackerai": Provider("hackerai", "Hacker AI", "HACKER_AI_API_KEY", "HACKER_AI_DEFAULT_MODEL",
                         "", "https://api.hackerai.sh/v1"),
    "custom": Provider("custom", "Custom OpenAI-compatible", "AI_API_KEY", "AI_DEFAULT_MODEL",
                       "", base_env="AI_BASE_URL"),
}


@dataclass(frozen=True)
class Route:
    id: str
    label: str
    base: str
    key: str
    model: str
    key_env: str
    key_source: str


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}…{value[-4:]}"


def _base_url(spec: Provider) -> str:
    env_name = spec.base_env or ""
    from_env = (os.getenv(env_name) or "").strip() if env_name else ""
    return (from_env or spec.base or "").strip().rstrip("/")


def resolve(provider_id: str) -> Route | None:
    """A provider is usable only with a key, a model and an HTTPS base URL."""
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        return None
    key = (get_secret(spec.key_env) or "").strip()
    if not key:
        return None
    base = _base_url(spec)
    if not base.startswith("https://"):
        return None
    model = ((os.getenv(spec.model_env) or "").strip() or spec.default_model).strip()
    if not model:
        return None
    return Route(spec.id, spec.label, base, key, model, spec.key_env, get_secret_source(spec.key_env))


def order() -> list[str]:
    raw = (os.getenv("AI_PROVIDER_ORDER") or "").strip()
    if not raw:
        return list(DEFAULT_ORDER)
    wanted = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return [pid for pid in wanted if pid in PROVIDERS] + [pid for pid in DEFAULT_ORDER if pid not in wanted]


def chain() -> list[Route]:
    return [route for route in (resolve(pid) for pid in order()) if route is not None]


def _endpoint(route: Route) -> str:
    return route.base if route.base.endswith("/chat/completions") else f"{route.base}/chat/completions"


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.4,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Return the first successful answer, plus who produced it and what failed."""
    routes = chain()
    if not routes:
        raise RuntimeError(
            "No model provider is configured. Add a key (Groq, Gemini, Mistral, Z.AI, "
            "OpenRouter, Hugging Face…) in .env or via POST /v1/vault/secrets."
        )

    attempts: list[dict[str, str]] = []
    started = time.time()
    for route in routes:
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False) as client:
                response = client.post(
                    _endpoint(route),
                    headers={"Authorization": f"Bearer {route.key}", "Content-Type": "application/json"},
                    json={
                        "model": route.model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
            if response.status_code >= 400:
                attempts.append({"provider": route.id, "error": f"HTTP {response.status_code}"})
                continue
            payload = response.json()
            choices = payload.get("choices") or []
            text = str((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
            if not text:
                attempts.append({"provider": route.id, "error": "empty response"})
                continue
            return {
                "text": text,
                "provider": route.id,
                "model": route.model,
                "attempts": attempts,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:  # network, DNS, timeout, bad JSON
            attempts.append({"provider": route.id, "error": type(exc).__name__})
            continue

    summary = ", ".join(f"{a['provider']}: {a['error']}" for a in attempts)
    raise RuntimeError(f"Every configured model provider failed ({summary})")


def complete_json(system: str, user: str, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask for JSON and parse it, tolerating accidental markdown fences."""
    result = complete(system, user, **kwargs)
    text = result["text"].strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text.lstrip("`")
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return json.loads(text.strip()), result


def health(probe: bool = False) -> dict[str, Any]:
    """Report every provider: configured, masked key, base URL and live status."""
    items: list[dict[str, Any]] = []
    for pid in order():
        spec = PROVIDERS[pid]
        route = resolve(pid)
        key = (get_secret(spec.key_env) or "").strip()
        base = _base_url(spec)
        entry: dict[str, Any] = {
            "provider": pid,
            "label": spec.label,
            "key_env": spec.key_env,
            "key_source": get_secret_source(spec.key_env),
            "key_preview": mask(key),
            "base_url": base or None,
            "model": (route.model if route else ((os.getenv(spec.model_env) or "").strip() or spec.default_model) or None),
            "usable": route is not None,
            "note": spec.note or None,
            "live": None,
        }
        if key and not base:
            entry["problem"] = f"Missing base URL. Set {spec.base_env}."
        elif key and not base.startswith("https://"):
            entry["problem"] = "Base URL must use HTTPS."
        elif not key:
            entry["problem"] = f"No key. Set {spec.key_env}."
        elif not entry["model"]:
            entry["problem"] = f"Missing model. Set {spec.model_env}."
        items.append(entry)

    if probe:
        for entry in items:
            route = resolve(entry["provider"])
            if route is None:
                continue
            try:
                with httpx.Client(timeout=httpx.Timeout(12, connect=6), follow_redirects=False) as client:
                    response = client.get(
                        f"{route.base}/models",
                        headers={"Authorization": f"Bearer {route.key}"},
                    )
                if response.status_code == 200:
                    entry["live"] = "ok"
                elif response.status_code in (401, 403):
                    entry["live"] = "key rejected"
                elif response.status_code == 429:
                    entry["live"] = "rate limited"
                else:
                    entry["live"] = f"HTTP {response.status_code}"
            except Exception as exc:
                entry["live"] = type(exc).__name__

    usable = [item["provider"] for item in items if item["usable"]]
    return {
        "order": order(),
        "usable": usable,
        "usable_count": len(usable),
        "active_default": usable[0] if usable else None,
        "probed": probe,
        "providers": items,
    }


@router.get("/providers")
def list_providers(_: bool = Depends(require_api_key)) -> dict[str, Any]:
    return health(probe=False)


@router.get("/health")
def provider_health(probe: bool = False, _: bool = Depends(require_api_key)) -> dict[str, Any]:
    """`?probe=true` makes a real request to every configured provider."""
    return health(probe=probe)
