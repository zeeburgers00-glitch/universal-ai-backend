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

from . import quota
from .security import require_api_key
from .vault import get_secret, get_secret_source

router = APIRouter(prefix="/v1/ai", tags=["ai-router"])

DEFAULT_ORDER = (
    "anthropic", "groq", "gemini", "mistral", "zai", "openrouter",
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
    local: bool = False          # runs on this machine: no key, no quota
    free_tier: bool = True       # provider serves some models without billing
    keys_env: str | None = None  # comma-separated keyring, rotated in order
    mode: str = "openai"         # wire protocol: "openai" chat/completions or "anthropic" messages


PROVIDERS: dict[str, Provider] = {
    # Claude speaks the Messages API, not chat/completions, so it has its own branch in
    # complete(). Bring a key and it wins; without a key it resolves to nothing.
    "anthropic": Provider("anthropic", "Anthropic Claude", "ANTHROPIC_API_KEY",
                          "ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-5",
                          "https://api.anthropic.com", mode="anthropic", free_tier=False,
                          note="Paid API. Native tool use — see app/anthropic.py and /v1/jarvis."),
    "groq": Provider("groq", "Groq", "GROQ_API_KEY", "GROQ_DEFAULT_MODEL",
                     "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
    "gemini": Provider("gemini", "Google Gemini", "GEMINI_API_KEY", "GEMINI_DEFAULT_MODEL",
                       # gemini-2.0-flash was shut down by Google in June 2026; 3.8 Flash is
                       # the current free-tier workhorse (see catalog/models.json).
                       "gemini-3.8-flash", "https://generativelanguage.googleapis.com/v1beta/openai",
                       note="Uses Google's OpenAI-compatible endpoint."),
    "mistral": Provider("mistral", "Mistral AI", "MISTRAL_API_KEY", "MISTRAL_DEFAULT_MODEL",
                        "mistral-large-latest", "https://api.mistral.ai/v1"),
    "zai": Provider("zai", "Z.ai (GLM)", "ZAI_API_KEY", "ZAI_DEFAULT_MODEL",
                    "glm-4.6", "https://api.z.ai/api/paas/v4"),
    "openrouter": Provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "OPENROUTER_DEFAULT_MODEL",
                           "meta-llama/llama-3.3-70b-instruct", "https://openrouter.ai/api/v1"),
    "huggingface": Provider("huggingface", "Hugging Face Router", "HF_API_KEY", "HF_DEFAULT_MODEL",
                            "meta-llama/Llama-3.3-70B-Instruct", "https://router.huggingface.co/v1"),
    "opencode_zen": Provider("opencode_zen", "OpenCode Zen", "OPENCODE_ZEN_API_KEY",
                             "OPENCODE_ZEN_DEFAULT_MODEL", "", base_env="OPENCODE_ZEN_BASE_URL",
                             note="Base URL unknown — set OPENCODE_ZEN_BASE_URL."),
    "hackerai": Provider("hackerai", "Hacker AI", "HACKERAI_API_KEY", "HACKERAI_DEFAULT_MODEL",
                         "", base_env="HACKERAI_BASE_URL",
                         note="Base URL unknown — set HACKERAI_BASE_URL."),
    "custom": Provider("custom", "Custom OpenAI-compatible", "AI_API_KEY", "AI_DEFAULT_MODEL",
                       "", base_env="AI_BASE_URL"),
    # --- free + unlimited: your own machine ---------------------------------
    "ollama": Provider("ollama", "Ollama (local)", "OLLAMA_API_KEY", "OLLAMA_DEFAULT_MODEL",
                       "llama3.1", "http://127.0.0.1:11434/v1", base_env="OLLAMA_BASE_URL", local=True, free_tier=True,
                       note="Local model server: no key, no daily limit, no data leaves the box."),
    "lmstudio": Provider("lmstudio", "LM Studio (local)", "LMSTUDIO_API_KEY", "LMSTUDIO_DEFAULT_MODEL",
                         "local-model", "http://127.0.0.1:1234/v1", base_env="LMSTUDIO_BASE_URL", local=True, free_tier=True,
                         note="Local OpenAI-compatible server."),
    "llamacpp": Provider("llamacpp", "llama.cpp server (local)", "LLAMACPP_API_KEY", "LLAMACPP_DEFAULT_MODEL",
                         "local-model", "http://127.0.0.1:8080/v1", base_env="LLAMACPP_BASE_URL", local=True, free_tier=True,
                         note="llama-server default port."),
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
    mode: str = "openai"


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


def _loopback_allowed(spec: Provider) -> bool:
    """http:// is only acceptable for a model server on this machine."""

    return spec.local or (os.getenv("AI_ALLOW_LOCAL_BASE") or "").strip().lower() in {"1", "true", "yes"}


def _keys(spec: Provider) -> list[str]:
    """Keyring: ``GROQ_API_KEYS=a,b,c`` rotates; ``GROQ_API_KEY`` is the single-key form."""

    raw = ""
    ring_env = spec.keys_env or (
        f"{spec.key_env[:-4]}_KEYS" if spec.key_env.endswith("_KEY") else None
    )
    if ring_env:
        raw = (os.getenv(ring_env) or "").strip()
    if not raw:
        raw = (get_secret(spec.key_env) or "").strip()
    keys = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
    if not keys and spec.local:
        keys = ["local"]  # local servers ignore the bearer token
    return keys


def resolve(provider_id: str) -> Route | None:
    """First usable route for a provider (kept for backwards compatibility)."""

    routes = resolve_all(provider_id)
    return routes[0] if routes else None


def resolve_all(provider_id: str) -> list[Route]:
    """Every usable route for a provider — one per key in the keyring."""

    spec = PROVIDERS.get(provider_id)
    if spec is None:
        return []
    keys = _keys(spec)
    if not keys:
        return []
    base = _base_url(spec)
    secure = base.startswith("https://")
    if not secure and not (_loopback_allowed(spec) and _is_loopback(base)):
        return []
    model = ((os.getenv(spec.model_env) or "").strip() or spec.default_model).strip()
    if not model:
        return []
    source = get_secret_source(spec.key_env) if not spec.local else "local"
    return [
        Route(spec.id, spec.label, base, key, model, spec.key_env, source, spec.mode)
        for key in keys
    ]


def _is_loopback(base: str) -> bool:
    return any(host in base for host in ("127.0.0.1", "localhost", "[::1]"))


def order() -> list[str]:
    raw = (os.getenv("AI_PROVIDER_ORDER") or "").strip()
    if not raw:
        return list(DEFAULT_ORDER)
    wanted = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return [pid for pid in wanted if pid in PROVIDERS] + [pid for pid in DEFAULT_ORDER if pid not in wanted]


def chain() -> list[Route]:
    """Routes in preference order, skipping providers whose free quota is spent.

    If every configured provider looks exhausted (local counters are estimates),
    the chain falls back to including them rather than refusing to work.
    """

    usable: list[Route] = []
    exhausted: list[Route] = []
    for pid in order():
        routes = resolve_all(pid)
        if not routes:
            continue
        if quota.available(pid):
            usable.extend(routes)
        else:
            exhausted.extend(routes)
    return usable or exhausted


def _probe(base: str, timeout: float = 0.8) -> bool:
    """Cheap TCP check: is a local model server actually listening?"""

    import socket
    from urllib.parse import urlparse

    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def free_status(probe: bool = False) -> dict[str, Any]:
    """Which providers are configured, how many keys, and how much free room is left."""

    rows = []
    for pid, spec in PROVIDERS.items():
        routes = resolve_all(pid)
        rows.append({
            "provider": pid,
            "label": spec.label,
            "configured": bool(routes),
            "keys": len(routes),
            "local": spec.local,
            "unlimited": quota.cap_for(pid) <= 0 and bool(routes),
            "daily_cap": quota.cap_for(pid),
            "remaining_today": quota.remaining(pid),
            "exhausted": not quota.available(pid),
            "model": routes[0].model if routes else None,
            "note": spec.note,
        })
        if probe and spec.local:
            rows[-1]["running"] = bool(routes) and _probe(routes[0].base)
    rows.sort(key=lambda row: (not row["configured"], row["daily_cap"] == 0, row["provider"]))
    return {
        "quota": quota.status(),
        "providers": rows,
        "unlimited_options": [row["provider"] for row in rows if row["unlimited"]],
        "local_running": [r["provider"] for r in rows if r.get("running")] if probe else None,
        "advice": (
            "For genuinely unlimited free usage run a local server (Ollama/LM Studio) and set "
            "AI_PROVIDER_ORDER=ollama,groq,gemini. Managed free tiers always have daily caps."
        ),
    }


def _endpoint(route: Route) -> str:
    if route.mode == "anthropic":
        return route.base if route.base.endswith("/messages") else (
            f"{route.base}/messages" if route.base.endswith("/v1") else f"{route.base}/v1/messages"
        )
    return route.base if route.base.endswith("/chat/completions") else f"{route.base}/chat/completions"


def _headers(route: Route) -> dict[str, str]:
    if route.mode == "anthropic":
        return {
            "x-api-key": route.key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    return {"Authorization": f"Bearer {route.key}", "Content-Type": "application/json"}


def _payload(route: Route, system: str, user: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    if route.mode == "anthropic":
        return {
            "model": route.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    return {
        "model": route.model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def _text_of(route: Route, payload: dict[str, Any]) -> str:
    if route.mode == "anthropic":
        blocks = payload.get("content") or []
        return "\n".join(
            str(block.get("text") or "") for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content") or "").strip()


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
            "No model provider is configured. Either run a local model server "
            "(ollama serve → AI_PROVIDER_ORDER=ollama) or add a key (Groq, Gemini, Mistral, Z.AI, "
            "OpenRouter, Hugging Face…) in .env or via POST /v1/vault/secrets."
        )

    attempts: list[dict[str, str]] = []
    started = time.time()
    for route in routes:
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False) as client:
                response = client.post(
                    _endpoint(route),
                    headers=_headers(route),
                    json=_payload(route, system, user, max_tokens, temperature),
                )
            if response.status_code >= 400:
                status = "429" if response.status_code == 429 else f"HTTP {response.status_code}"
                quota.record(route.id, status)
                attempts.append({"provider": route.id, "error": status})
                continue
            payload = response.json()
            text = _text_of(route, payload)
            if not text:
                quota.record(route.id, "empty")
                attempts.append({"provider": route.id, "error": "empty response"})
                continue
            quota.record(route.id, "ok")
            return {
                "text": text,
                "provider": route.id,
                "model": route.model,
                "attempts": attempts,
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:  # network, DNS, timeout, bad JSON
            quota.record(route.id, "error")
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
