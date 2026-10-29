"""Optional, approval-gated local MCP bridge for REA (Reverse Engineer Anything).

REA runs as a child Node.js process using its default stdio transport. This
module intentionally does not use REA's unauthenticated plain-HTTP mode.
"""
import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any


MAX_MCP_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TOOL_ARGUMENT_BYTES = 128 * 1024


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

    # Pass platform essentials and REA/provider-specific configuration only.
    # Backend API keys and unrelated app secrets are not inherited by the REA process.
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
    # The bridge itself controls these settings.
    env["REA_MCP_ENABLED"] = "true"
    return node, entry, env, _parse_timeout()


def _allowed_tool_names() -> set[str]:
    raw = os.getenv("REA_ALLOWED_TOOL_NAMES", "")
    return {value.strip() for value in raw.split(",") if value.strip()}


async def _write_message(process: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise ReaBridgeError("REA MCP stdin is unavailable.")
    encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(encoded) > MAX_MCP_MESSAGE_BYTES:
        raise ReaBridgeError("MCP request exceeds the local bridge size limit.")
    process.stdin.write(encoded)
    await process.stdin.drain()


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
            # MCP notifications/protocol messages are ignored until our request ID returns.
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


async def _close_process(process: asyncio.subprocess.Process) -> None:
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


async def _open_session() -> tuple[asyncio.subprocess.Process, float]:
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
        await _write_message(process, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "universal-ai-backend-rea-bridge", "version": "0.1.0"},
            },
        })
        await _read_response(process, 1, deadline)
        await _write_message(process, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        return process, deadline
    except Exception:
        await _close_process(process)
        raise


async def list_rea_tools() -> dict[str, Any]:
    process, deadline = await _open_session()
    try:
        result = await _tool_list_result(process, deadline)
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise ReaBridgeError("REA returned an invalid tool catalog.")
        sanitized = []
        for item in tools:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            sanitized.append({
                "name": item["name"][:200],
                "title": str(item.get("title") or "")[:300],
                "description": str(item.get("description") or "")[:2500],
                "inputSchema": item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {},
                "annotations": item.get("annotations") if isinstance(item.get("annotations"), dict) else {},
                "enabled_by_local_allowlist": item["name"] in _allowed_tool_names(),
            })
        return {
            "status": "ready",
            "server": "rea-agents",
            "tool_count": len(sanitized),
            "allowlisted_count": sum(1 for item in sanitized if item["enabled_by_local_allowlist"]),
            "tools": sanitized,
            "note": "A listed tool is not automatically permitted. Only local allowlisted names can be called, and every call still requires explicit approval.",
        }
    finally:
        await _close_process(process)


async def _tool_list_result(process: asyncio.subprocess.Process, deadline: float) -> dict[str, Any]:
    await _write_message(process, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    })
    return await _read_response(process, 2, deadline)


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
        raise ReaBridgeError("Tool is not on REA_ALLOWED_TOOL_NAMES. Review /v1/rea/tools and configure the exact tool name locally.")

    process, deadline = await _open_session()
    try:
        catalog = await _tool_list_result(process, deadline)
        tools = catalog.get("tools", [])
        if not any(isinstance(item, dict) and item.get("name") == tool_name for item in tools):
            raise ReaBridgeError("The requested tool name is not exposed by the installed REA version.")
        await _write_message(process, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        result = await _read_response(process, 3, deadline)
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
        if output_size > 4 * 1024 * 1024:
            raise ReaBridgeError("REA result exceeds the 4 MB API response limit.")
        return safe_result
    finally:
        await _close_process(process)
