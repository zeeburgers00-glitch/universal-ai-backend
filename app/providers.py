import os
from typing import Any

import httpx


PROVIDERS: dict[str, dict[str, Any]] = {
    "openai-compatible": {
        "label": "Custom OpenAI-compatible endpoint", "base_env": "AI_BASE_URL", "key_env": "AI_API_KEY",
        "model_env": "AI_DEFAULT_MODEL", "default_base": None, "requires_key": True, "mode": "openai-compatible",
    },
    "groq": {
        "label": "Groq", "base_env": "GROQ_BASE_URL", "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_DEFAULT_MODEL", "default_base": "https://api.groq.com/openai/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "openrouter": {
        "label": "OpenRouter", "base_env": "OPENROUTER_BASE_URL", "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_DEFAULT_MODEL", "default_base": "https://openrouter.ai/api/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "together": {
        "label": "Together AI", "base_env": "TOGETHER_BASE_URL", "key_env": "TOGETHER_API_KEY",
        "model_env": "TOGETHER_DEFAULT_MODEL", "default_base": "https://api.together.xyz/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "deepseek": {
        "label": "DeepSeek API", "base_env": "DEEPSEEK_BASE_URL", "key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_DEFAULT_MODEL", "default_base": "https://api.deepseek.com/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "fireworks": {
        "label": "Fireworks AI", "base_env": "FIREWORKS_BASE_URL", "key_env": "FIREWORKS_API_KEY",
        "model_env": "FIREWORKS_DEFAULT_MODEL", "default_base": "https://api.fireworks.ai/inference/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "cerebras": {
        "label": "Cerebras Inference", "base_env": "CEREBRAS_BASE_URL", "key_env": "CEREBRAS_API_KEY",
        "model_env": "CEREBRAS_DEFAULT_MODEL", "default_base": "https://api.cerebras.ai/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "mistral": {
        "label": "Mistral API", "base_env": "MISTRAL_BASE_URL", "key_env": "MISTRAL_API_KEY",
        "model_env": "MISTRAL_DEFAULT_MODEL", "default_base": "https://api.mistral.ai/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "gemini": {
        "label": "Google Gemini API", "base_env": "GEMINI_BASE_URL", "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_DEFAULT_MODEL", "default_base": "https://generativelanguage.googleapis.com/v1beta/openai/", "requires_key": True, "mode": "openai-compatible",
    },
    "siliconflow": {
        "label": "SiliconFlow", "base_env": "SILICONFLOW_BASE_URL", "key_env": "SILICONFLOW_API_KEY",
        "model_env": "SILICONFLOW_DEFAULT_MODEL", "default_base": "https://api.siliconflow.cn/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "sambanova": {
        "label": "SambaNova Cloud", "base_env": "SAMBANOVA_BASE_URL", "key_env": "SAMBANOVA_API_KEY",
        "model_env": "SAMBANOVA_DEFAULT_MODEL", "default_base": "https://api.sambanova.ai/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "nebius": {
        "label": "Nebius AI Studio", "base_env": "NEBIUS_BASE_URL", "key_env": "NEBIUS_API_KEY",
        "model_env": "NEBIUS_DEFAULT_MODEL", "default_base": "https://api.studio.nebius.com/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "novita": {
        "label": "Novita AI", "base_env": "NOVITA_BASE_URL", "key_env": "NOVITA_API_KEY",
        "model_env": "NOVITA_DEFAULT_MODEL", "default_base": "https://api.novita.ai/v3/openai", "requires_key": True, "mode": "openai-compatible",
    },
    "hyperbolic": {
        "label": "Hyperbolic", "base_env": "HYPERBOLIC_BASE_URL", "key_env": "HYPERBOLIC_API_KEY",
        "model_env": "HYPERBOLIC_DEFAULT_MODEL", "default_base": "https://api.hyperbolic.xyz/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "dashscope": {
        "label": "Alibaba DashScope / Qwen API", "base_env": "DASHSCOPE_BASE_URL", "key_env": "DASHSCOPE_API_KEY",
        "model_env": "DASHSCOPE_DEFAULT_MODEL", "default_base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "requires_key": True, "mode": "openai-compatible",
    },
    "huggingface": {
        "label": "Hugging Face Inference Endpoint", "base_env": "HUGGINGFACE_BASE_URL", "key_env": "HUGGINGFACE_API_KEY",
        "model_env": "HUGGINGFACE_DEFAULT_MODEL", "default_base": None, "requires_key": True, "mode": "openai-compatible",
    },
    "ollama": {
        "label": "Ollama server", "base_env": "OLLAMA_BASE_URL", "key_env": "OLLAMA_API_KEY",
        "model_env": "OLLAMA_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "vllm": {
        "label": "vLLM server", "base_env": "VLLM_BASE_URL", "key_env": "VLLM_API_KEY",
        "model_env": "VLLM_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "sglang": {
        "label": "SGLang server", "base_env": "SGLANG_BASE_URL", "key_env": "SGLANG_API_KEY",
        "model_env": "SGLANG_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "localai": {
        "label": "LocalAI server", "base_env": "LOCALAI_BASE_URL", "key_env": "LOCALAI_API_KEY",
        "model_env": "LOCALAI_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "llama-cpp": {
        "label": "llama.cpp server", "base_env": "LLAMA_CPP_BASE_URL", "key_env": "LLAMA_CPP_API_KEY",
        "model_env": "LLAMA_CPP_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "lmstudio": {
        "label": "LM Studio server", "base_env": "LMSTUDIO_BASE_URL", "key_env": "LMSTUDIO_API_KEY",
        "model_env": "LMSTUDIO_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "litellm": {
        "label": "LiteLLM gateway", "base_env": "LITELLM_BASE_URL", "key_env": "LITELLM_API_KEY",
        "model_env": "LITELLM_DEFAULT_MODEL", "default_base": None, "requires_key": False, "mode": "openai-compatible",
    },
    "anthropic": {
        "label": "Anthropic Messages API", "base_env": "ANTHROPIC_BASE_URL", "key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_DEFAULT_MODEL", "default_base": "https://api.anthropic.com", "requires_key": True, "mode": "anthropic",
    },
}


def _config(provider: str) -> tuple[dict[str, Any], str, str, str]:
    key = provider.lower().strip()
    spec = PROVIDERS.get(key)
    if not spec:
        raise ValueError(f"Unknown provider {key!r}. Supported provider IDs: {', '.join(sorted(PROVIDERS))}")
    base_url = (os.getenv(spec["base_env"], "").strip() or spec["default_base"] or "").rstrip("/")
    api_key = os.getenv(spec["key_env"], "").strip()
    model = os.getenv(spec["model_env"], "").strip()
    if not base_url:
        raise ValueError(f"{spec['base_env']} is not configured")
    if spec["requires_key"] and not api_key:
        raise ValueError(f"{spec['key_env']} is not configured")
    if not base_url.startswith(("https://", "http://")):
        raise ValueError(f"{spec['base_env']} must be an http(s) URL")
    return spec, base_url, api_key, model


def provider_status() -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for provider_id, spec in PROVIDERS.items():
        base_url = os.getenv(spec["base_env"], "").strip() or (spec["default_base"] or "")
        api_key = os.getenv(spec["key_env"], "").strip()
        ready = bool(base_url and (api_key or not spec["requires_key"]))
        providers.append({
            "id": provider_id,
            "label": spec["label"],
            "mode": spec["mode"],
            "ready": ready,
            "base_url_env": spec["base_env"],
            "api_key_env": spec["key_env"],
            "default_model_env": spec["model_env"],
            "default_base_available": bool(spec["default_base"]),
            "note": "No credentials, base URL values, or secret values are returned.",
        })
    return {
        "providers": providers,
        "ready_count": sum(1 for x in providers if x["ready"]),
        "total": len(providers),
    }


async def chat_with_provider(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 1024,
) -> dict[str, Any]:
    spec, base_url, api_key, configured_model = _config(provider)
    model_name = (model or configured_model).strip()
    if not model_name:
        raise ValueError(f"Set model in request or configure {spec['model_env']}")

    if spec["mode"] == "anthropic":
        return await _chat_anthropic(base_url, api_key, model_name, messages, temperature, max_tokens)

    url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if provider.lower() == "openrouter":
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_SITE_URL", "https://localhost")
        headers["X-Title"] = os.getenv("OPENROUTER_APP_NAME", "Universal AI Backend")

    timeout = httpx.Timeout(90.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data


async def _chat_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
) -> dict[str, Any]:
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            raise ValueError("Anthropic adapter in this release supports text-only message content")
        content_text = str(content)
        if role == "system":
            system_parts.append(content_text)
        elif role in {"user", "assistant"}:
            anthropic_messages.append({"role": role, "content": content_text})
        else:
            raise ValueError(f"Anthropic adapter does not support message role {role!r} in this release")
    if not anthropic_messages:
        raise ValueError("Anthropic request requires at least one user/assistant message")
    payload: dict[str, Any] = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens or 1024,
        "temperature": temperature,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    timeout = httpx.Timeout(90.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(
            f"{base_url}/v1/messages",
            json=payload,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
    text_content = "".join(str(block.get("text", "")) for block in data.get("content", []) if block.get("type") == "text")
    return {
        "id": data.get("id"),
        "object": "chat.completion",
        "created": None,
        "model": data.get("model", model),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text_content},
            "finish_reason": data.get("stop_reason"),
        }],
        "usage": data.get("usage"),
        "provider": "anthropic",
    }


async def chat_with_openai_compatible(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 1024,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper for the custom OpenAI-compatible provider."""
    if base_url:
        # Explicit base URLs are only available to trusted server code; public request
        # bodies never control this parameter.
        api_key = os.getenv("AI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("AI_API_KEY is not configured")
        endpoint = base_url.strip().rstrip("/")
        url = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
        payload: dict[str, Any] = {"model": model or os.getenv("AI_DEFAULT_MODEL", ""), "messages": messages, "temperature": temperature}
        if not payload["model"]:
            raise ValueError("Set model in request or configure AI_DEFAULT_MODEL")
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0), follow_redirects=False) as client:
            response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
            response.raise_for_status()
            return response.json()
    return await chat_with_provider("openai-compatible", model, messages, temperature, max_tokens)
