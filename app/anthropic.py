"""Claude (Anthropic Messages API) — the brain when you bring a key.

Everything else in this repo speaks the OpenAI-compatible chat API. Anthropic does
not, so it gets its own small client instead of a fake adapter:

* ``x-api-key`` + ``anthropic-version`` headers, ``/v1/messages`` endpoint
* content blocks in the response (``text`` and ``tool_use``)
* native tool use, which is what lets JARVIS call the free tool belt

No key means no calls: ``available()`` is False and every entry point raises
``AnthropicError("unavailable: ANTHROPIC_API_KEY ...")``. Nothing here fabricates
an answer when the model is missing.

Env:
    ANTHROPIC_API_KEY       required for use (or save it via POST /v1/vault/secrets)
    ANTHROPIC_DEFAULT_MODEL model id, default ``claude-sonnet-4-5``
    ANTHROPIC_BASE_URL      override for a proxy, default ``https://api.anthropic.com``
    ANTHROPIC_MAX_TOKENS    default max_tokens for a reply (default 1024)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import httpx

from .vault import get_secret, get_secret_source

API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 1024


class AnthropicError(RuntimeError):
    """Anything that stopped a Claude call, with the honest reason attached."""

    def __init__(self, message: str, *, status: int = 502, unavailable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.unavailable = unavailable


def api_key() -> str:
    return (get_secret("ANTHROPIC_API_KEY") or "").strip()


def available() -> bool:
    return bool(api_key())


def base_url() -> str:
    return (os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").strip().rstrip("/")


def model() -> str:
    return (os.getenv("ANTHROPIC_DEFAULT_MODEL") or "").strip() or DEFAULT_MODEL


def _max_tokens(value: int | None) -> int:
    if value:
        return int(value)
    raw = (os.getenv("ANTHROPIC_MAX_TOKENS") or "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_MAX_TOKENS


def status() -> dict[str, Any]:
    """What the health endpoint and JARVIS report — never the key itself."""

    key = api_key()
    return {
        "provider": "anthropic",
        "configured": bool(key),
        "model": model(),
        "base_url": base_url(),
        "key_masked": f"{key[:6]}…{key[-4:]}" if len(key) > 10 else ("set" if key else ""),
        "key_source": get_secret_source("ANTHROPIC_API_KEY") if key else None,
        "sdk": "raw httpx (no anthropic package needed)",
    }


# --------------------------------------------------------------------------- #
# Transport — one function so tests can stub the network completely
# --------------------------------------------------------------------------- #

def _post(payload: dict[str, Any], *, timeout: float = 90.0) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise AnthropicError(
            "unavailable: ANTHROPIC_API_KEY is not set "
            "(export it, or POST /v1/vault/secrets with name=ANTHROPIC_API_KEY)",
            status=503,
            unavailable=True,
        )
    url = f"{base_url()}/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15)) as client:
            response = client.post(url, headers=headers, json=payload)
    except Exception as exc:  # DNS, timeout, blocked network
        raise AnthropicError(
            f"Claude call failed: {type(exc).__name__}: {exc}", status=502
        ) from exc

    elapsed = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = str((body.get("error") or {}).get("message") or body)[:300]
        except Exception:  # noqa: BLE001 - non-JSON error page
            detail = (response.text or "")[:300]
        raise AnthropicError(
            f"Claude HTTP {response.status_code}: {detail}", status=502
        )

    body = response.json()
    body.setdefault("_elapsed_ms", elapsed)
    return body


# --------------------------------------------------------------------------- #
# One call
# --------------------------------------------------------------------------- #

def _text_of(body: dict[str, Any]) -> str:
    parts = [
        str(block.get("text") or "")
        for block in (body.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part).strip()


def messages(
    system: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.4,
    model_id: str | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """One Messages API round trip. Returns text, tool calls, usage and model."""

    payload: dict[str, Any] = {
        "model": model_id or model(),
        "max_tokens": _max_tokens(max_tokens),
        "temperature": temperature,
        "system": system,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    body = _post(payload, timeout=timeout)
    calls = [
        {"id": block.get("id"), "name": block.get("name"), "input": block.get("input") or {}}
        for block in (body.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    return {
        "text": _text_of(body),
        "content": body.get("content") or [],
        "tool_calls": calls,
        "stop_reason": body.get("stop_reason"),
        "usage": body.get("usage") or {},
        "model": body.get("model") or payload["model"],
        "provider": "anthropic",
        "elapsed_ms": body.get("_elapsed_ms"),
    }


# --------------------------------------------------------------------------- #
# Tool-use loop: Claude picks a tool, we run it, Claude reads the result
# --------------------------------------------------------------------------- #

def tool_turn(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    max_rounds: int = 3,
    max_tokens: int | None = None,
    temperature: float = 0.3,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Let Claude call tools until it answers in words.

    ``run_tool(name, args)`` must return JSON-able data. Exceptions are captured and
    handed back to Claude as ``is_error`` results, so a missing binary upstream
    produces an honest apology instead of a crash.
    """

    conversation: list[dict[str, Any]] = [{"role": "user", "content": user}]
    executed: list[dict[str, Any]] = []
    last: dict[str, Any] | None = None

    for round_index in range(max(1, max_rounds)):
        answer = messages(
            system, conversation, tools=tools, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout,
        )
        last = answer
        calls = answer.get("tool_calls") or []
        if not calls:
            return {
                "text": answer["text"],
                "tool_runs": executed,
                "rounds": round_index + 1,
                "model": answer["model"],
                "usage": answer.get("usage") or {},
                "stopped": "answer",
            }

        conversation.append({"role": "assistant", "content": answer["content"]})
        results: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name") or "")
            args = call.get("input") or {}
            try:
                output = run_tool(name, args)
                is_error = bool(isinstance(output, dict) and output.get("ok") is False)
            except Exception as exc:  # noqa: BLE001 - the model gets the error text
                output = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                is_error = True
            executed.append({"tool": name, "args": args, "ok": not is_error,
                             "output": output})
            results.append({
                "type": "tool_result",
                "tool_use_id": call.get("id"),
                "content": json.dumps(output, ensure_ascii=False)[:6000],
                "is_error": is_error,
            })
        conversation.append({"role": "user", "content": results})

    return {
        "text": (last or {}).get("text") or "",
        "tool_runs": executed,
        "rounds": max_rounds,
        "model": (last or {}).get("model") or model(),
        "usage": (last or {}).get("usage") or {},
        "stopped": "max_rounds",
    }
