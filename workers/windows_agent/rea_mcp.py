"""Optional approval-gated local MCP bridge for REA (Reverse Engineer Anything).

REA runs as a persistent child Node.js process over its default stdio transport.
This bridge intentionally does not expose REA's unauthenticated plain-HTTP mode.
"""
import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MAX_MCP_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TOOL_ARGUMENT_BYTES = 128 * 1024
MAX_TOOL_RESULT_BYTES = 4 * 1024 * 1024

_PROCESS: asyncio.subprocess.Process | None = None
_PROCESS_LOCK = asyncio.Lock()
_TOOLS_CACHE: list[dict[str, Any]] | None = None
_NEXT_REQUEST_ID = 0


class ReaBridgeError(RuntimeError):
    """A sanitized error from the local REA bridge."""


def _parse_timeout() -> float:
    raw = os.getenv("REA_MCP_CALL_TIMEOUT_SECONDS", "180").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 180.0
    return min(max(value, 10.0), 600.0)


def _configuration() -> tuple[str, Path, dict[str, str], float]:
    if os.getenv("REA_MCP_ENABLED", "").lower() != "true":
        raise ReaBridgeError("REA integration is disabled on this device. Set REA_MCP_ENABLED=true after installing and reviewing REA.")
    node = os.getenv("REA_NODE_EXECUTABLE", "").strip() or shutil.which("node") or ""
    entry_raw = os.getenv("REA_ENTRY_SCRIPT", "").strip()
    if not node:
        raise ReaBridgeError("Node.js was not found. Configure REA_NODE_EXECUTABLE or add Node.js to PATH.")
    if not entry_raw:
        raise ReaBridgeError("REA_ENTRY_SCRIPT is not configured. Point it to the installed rea-agents/scripts/rea.mjs file.")
    entry = Path(entry_raw).expanduser().resolve()
    if entry.name.lower() != "rea.mjs" or not entry.is_file():
        raise ReaBridgeError("REA_ENTRY_SCRIPT must point to an existing rea-agents scripts/rea.mjs file.")
    if not os.path.isabs(node):
        resolved_node = shutil.which(node)
        if not resolved_node:
            raise ReaBridgeError("Configured Node.js executable could not be resolved.")
        node = resolved_node

    # Keep only platform essentials and REA/provider settings. Backend and AI
    # credentials must never be inherited by the local reverse-engineering process.
    env: dict[str, str] = {}
    exact = {
        "PATH", "SystemRoot", "WINDIR", "USERPROFILE", "HOME", "APPDATA",
        "LOCALAPPDATA", "TEMP", "TMP", "PROGRAMDATA", "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "JAVA_HOME",
    }
    for key in exact:
        value = os.getenv(key)
        if value:
            env[key] = value
    for key, value in os.environ.items():
        if key.startswith(("REA_", "GHIDRA_", "HOPPER_", "IDA_", "KUNA_", "JEB_", "FRIDA_")):
            env[key] = value
    env["REA_MCP_ENABLED"] = "true"
    return node, entry, env, _parse_timeout()


def _allowed_tool_names() -> set[str]:
    raw = os.getenv("REA_ALLOWED_TOOL_NAMES", "")
    return {value.strip() for value in raw.split(",") if value.strip()}


def _allowed_target_roots() -> list[Path]:
    raw = os.getenv("REA_ALLOWED_TARGET_ROOTS", "")
    roots: list[Path] = []
    for value in raw.split(os.pathsep):
        item = value.strip().strip('"')
        if item:
            roots.append(Path(item).expanduser().resolve())
    # Also accept semicolon-separated paths when an operator copies a list
    # from Windows documentation; on Windows os.pathsep is already a semicolon.
    return roots


def _allowed_url_hosts() -> set[str]:
    return {
        value.strip().lower()
        for value in os.getenv("REA_ALLOWED_URL_HOSTS", "").split(",")
        if value.strip()
    }


def _inside_root(target: Path, roots: list[Path]) -> bool:
    resolved = target.resolve()
    for root in roots:
        try:
            if os.path.commonpath([str(resolved), str(root)]) == str(root):
                return True
        except ValueError:
            continue
    return False


def _validate_argument_scope(value: Any, key: str = "") -> None:
    """Enforce local roots for file-like fields and host allowlists for URLs."""
    if isinstance(value, dict):
        for child_key, child in value.items():
            _validate_argument_scope(child, str(child_key))
        return
    if isinstance(value, list):
        for child in value:
            _validate_argument_scope(child, key)
        return
    if not isinstance(value, str):
        return

    field = key.casefold()
    is_url_field = "url" in field or field in {"uri", "website", "webpage"}
    if is_url_field:
        if not value.strip():
            return
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ReaBridgeError(f"URL field {key!r} must be an explicit HTTP(S) URL.")
        if parsed.hostname.lower() not in _allowed_url_hosts():
            raise ReaBridgeError(f"URL host {parsed.hostname!r} is not in local REA_ALLOWED_URL_HOSTS.")
        return

    path_field = any(token in field for token in (
        "path", "file", "directory", "dir", "artifact", "bundle", "apk",
        "firmware", "binary", "source", "destination", "project", "asset", "root",
    ))
    looks_like_path = (
        value.startswith(("./", ".\\", "../", "..\\", "/", "\\\\"))
        or bool(re.match(r"^[A-Za-z]:[\\/]", value))
        or "\\\\" in value
        or value.endswith((".exe", ".dll", ".apk", ".ipa", ".asar", ".bin", ".elf", ".pck", ".wasm", ".gguf", ".safetensors"))
    )
    if not path_field and not looks_like_path:
        return
    if not value.strip():
        return
    # Relative paths are anchored to the configured target root only when
    # exactly one root exists; they are never resolved against arbitrary cwd.
    roots = _allowed_target_roots()
    if not roots:
        raise ReaBridgeError("File/artifact analysis is disabled until REA_ALLOWED_TARGET_ROOTS is configured locally.")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        if len(roots) != 1:
            raise ReaBridgeError("Relative target paths require exactly one REA_ALLOWED_TARGET_ROOTS entry.")
        candidate = roots[0] / candidate
    target = candidate.resolve()
    if not _inside_root(target, roots):
        raise ReaBridgeError("A file/artifact path falls outside the locally configured REA_ALLOWED_TARGET_ROOTS.")
    if not target.exists():
        raise ReaBridgeError("A file/artifact path does not exist under the allowed target roots.")


async def _write_message(process: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise ReaBridgeError("REA MCP stdin is unavailable.")
    encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(encoded) > MAX_MCP_MESSAGE_BYTES:
        raise ReaBridgeError("MCP request exceeds the local bridge size limit.")
    process.stdin.write(encoded)
    await process.stdin.drain()


def _next_id() -> int:
    global _NEXT_REQUEST_ID
    _NEXT_REQUEST_ID += 1
    return _NEXT_REQUEST_ID


async def _read_response(
    process: asyncio.subprocess.Process,
    request_id: int,
    deadline: float,
) -> dict[str, Any]:
    if process.stdout is None:
        raise ReaBridgeError("REA MCP stdout is unavailable.")
    for _ in range(500):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReaBridgeError("REA MCP request timed out.")
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise ReaBridgeError("REA MCP request timed out.") from exc
        except (ValueError, asyncio.LimitOverrunError) as exc:
            raise ReaBridgeError("REA returned an oversized or invalid MCP frame.") from exc
        if not line:
            raise ReaBridgeError("REA MCP process exited before returning a response.")
        if len(line) > MAX_MCP_MESSAGE_BYTES:
            raise ReaBridgeError("REA MCP response exceeds the local bridge size limit.")
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(message, dict) or message.get("id") != request_id:
            continue
        if "error" in message:
            error = message.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise ReaBridgeError(f"REA MCP returned a protocol error (code {code}).")
        result = message.get("result")
        if not isinstance(result, dict):
            raise ReaBridgeError("REA MCP returned an invalid result object.")
        return result
    raise ReaBridgeError("REA MCP emitted too many protocol messages without a matching response.")


async def _close_process(process: asyncio.subprocess.Process | None) -> None:
    if process is None:
        return
    if process.stdin is not None:
        try:
            process.stdin.close()
            await process.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def _reset_session() -> None:
    global _PROCESS, _TOOLS_CACHE
    process = _PROCESS
    _PROCESS = None
    _TOOLS_CACHE = None
    if process is not None:
        await _close_process(process)


async def _ensure_session() -> tuple[asyncio.subprocess.Process, float]:
    global _PROCESS, _TOOLS_CACHE
    if _PROCESS is not None and _PROCESS.returncode is None:
        return _PROCESS, _parse_timeout()
    await _reset_session()
    node, entry, env, timeout = _configuration()
    try:
        process = await asyncio.create_subprocess_exec(
            node,
            str(entry),
            "mcp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(entry.parent.parent),
            env=env,
            limit=MAX_MCP_MESSAGE_BYTES,
        )
    except (OSError, ValueError) as exc:
        raise ReaBridgeError(f"Could not start the local REA MCP process ({type(exc).__name__}).") from exc
    deadline = time.monotonic() + timeout
    try:
        request_id = _next_id()
        await _write_message(process, {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "universal-ai-backend-rea-bridge", "version": "0.1.0"},
            },
        })
        await _read_response(process, request_id, deadline)
        await _write_message(process, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        _PROCESS = process
        _TOOLS_CACHE = None
        return process, timeout
    except Exception:
        await _close_process(process)
        raise


async def _get_tools(process: asyncio.subprocess.Process, timeout: float, refresh: bool = False) -> list[dict[str, Any]]:
    global _TOOLS_CACHE
    if _TOOLS_CACHE is not None and not refresh:
        return _TOOLS_CACHE
    request_id = _next_id()
    await _write_message(process, {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": {}})
    result = await _read_response(process, request_id, time.monotonic() + timeout)
    tools = result.get("tools", [])
    if not isinstance(tools, list):
        raise ReaBridgeError("REA returned an invalid tool catalog.")
    _TOOLS_CACHE = [item for item in tools if isinstance(item, dict) and isinstance(item.get("name"), str)]
    return _TOOLS_CACHE


async def list_rea_tools() -> dict[str, Any]:
    async with _PROCESS_LOCK:
        try:
            process, timeout = await _ensure_session()
            tools = await _get_tools(process, timeout, refresh=True)
            allowlisted = _allowed_tool_names()
            sanitized = [{
                "name": item["name"][:200],
                "title": str(item.get("title") or "")[:300],
                "description": str(item.get("description") or "")[:2500],
                "inputSchema": item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {},
                "annotations": item.get("annotations") if isinstance(item.get("annotations"), dict) else {},
                "enabled_by_local_allowlist": item["name"] in allowlisted,
            } for item in tools]
            response = {
                "status": "ready",
                "server": "rea-agents",
                "tool_count": len(sanitized),
                "allowlisted_count": sum(1 for item in sanitized if item["enabled_by_local_allowlist"]),
                "tools": sanitized,
                "note": "Listed does not mean permitted. Only locally allowlisted tool names can be called, and every call still requires explicit user approval.",
            }
            if len(json.dumps(response, ensure_ascii=False, default=str).encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
                # Return a searchable compact catalog instead of failing when input schemas are very large.
                response["tools"] = [{k: v for k, v in item.items() if k != "inputSchema"} for item in sanitized]
                response["schemas_omitted"] = True
            return response
        except Exception:
            await _reset_session()
            raise


async def call_rea_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", tool_name):
        raise ReaBridgeError("Invalid REA tool name.")
    if not isinstance(arguments, dict):
        raise ReaBridgeError("REA tool arguments must be a JSON object.")
    try:
        encoded_args = json.dumps(arguments, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReaBridgeError("REA arguments must be JSON-serializable.") from exc
    if len(encoded_args) > MAX_TOOL_ARGUMENT_BYTES:
        raise ReaBridgeError("REA tool arguments exceed the 128 KB limit.")
    allowed = _allowed_tool_names()
    if not allowed or tool_name not in allowed:
        raise ReaBridgeError("Tool is not on REA_ALLOWED_TOOL_NAMES. Review /v1/rea/tools and configure the exact name locally.")
    _validate_argument_scope(arguments)

    async with _PROCESS_LOCK:
        try:
            process, timeout = await _ensure_session()
            tools = await _get_tools(process, timeout)
            if not any(item.get("name") == tool_name for item in tools):
                raise ReaBridgeError("The requested tool name is not exposed by the installed REA version.")
            request_id = _next_id()
            await _write_message(process, {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            })
            result = await _read_response(process, request_id, time.monotonic() + timeout)
            if result.get("isError") is True:
                raise ReaBridgeError("REA reported that the analysis tool failed; inspect the local REA logs.")
            safe_result = {
                "status": "completed",
                "tool_name": tool_name,
                "content": result.get("content", []),
                "structuredContent": result.get("structuredContent"),
                "isError": False,
            }
            output_size = len(json.dumps(safe_result, ensure_ascii=False, default=str).encode("utf-8"))
            if output_size > MAX_TOOL_RESULT_BYTES:
                raise ReaBridgeError("REA result exceeds the 4 MB API response limit.")
            return safe_result
        except Exception:
            # Timeouts and protocol errors can leave a pending response in the
            # stream. Reset the shared process rather than misattribute a later frame.
            await _reset_session()
            raise


async def close_rea_session() -> None:
    async with _PROCESS_LOCK:
        await _reset_session()
