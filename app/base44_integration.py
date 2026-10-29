"""Base44 platform integration adapter for Universal AI Backend.

All Base44 personal access tokens and backend secrets are read strictly from
server-side environment variables and are never echoed in API responses or logs.
"""
from __future__ import annotations

import io
import json
import os
import re
import tarfile
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException

APP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}$")
FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")

SUPPORTED_BRIDGE_ACTIONS = [
    "health",
    "stats",
    "tools",
    "tool_detail",
    "register_tool",
    "rea_status",
    "rea_tools",
    "rea_inspect",
    "rea_job",
    "providers",
    "agents",
    "agent_run",
    "workflows",
    "workflow_run",
    "channels",
    "channel_action",
    "voice_models",
    "voice_tts",
    "media_job",
    "discover_categories",
    "discover_github",
    "chat",
    "task_status",
]


def get_base44_api_url() -> str:
    url = (os.getenv("BASE44_API_URL") or "https://app.base44.com").strip().rstrip("/")
    if not url.startswith("https://"):
        raise HTTPException(status_code=500, detail="BASE44_API_URL must use HTTPS")
    return url


def get_public_backend_url() -> str:
    explicit = (os.getenv("UNIVERSAL_AI_BACKEND_PUBLIC_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    return "https://universal-ai-backend.vercel.app"


def base44_status() -> dict[str, Any]:
    token = (os.getenv("BASE44_ACCESS_TOKEN") or "").strip()
    return {
        "integration": "base44",
        "configured": bool(token),
        "token_type": "personal_access_token_b44u" if token.startswith("b44u_") else ("configured" if token else "missing"),
        "base44_api_url": get_base44_api_url(),
        "default_backend_url": get_public_backend_url(),
        "backend_function_name": "universalAiBackend",
        "supported_actions": SUPPORTED_BRIDGE_ACTIONS,
    }


def _require_token(override_token: str | None = None) -> str:
    token = (override_token or os.getenv("BASE44_ACCESS_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="BASE44_ACCESS_TOKEN is not configured on the server.",
        )
    return token


def _validate_app_id(app_id: str) -> str:
    cleaned = app_id.strip()
    if not APP_ID_RE.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail="Invalid Base44 app_id format")
    return cleaned


class Base44Client:
    """Async client for Base44 Apps REST API and Sandbox Bridge."""

    def __init__(self, access_token: str | None = None, api_url: str | None = None) -> None:
        self._token = _require_token(access_token)
        self._api_url = (api_url or get_base44_api_url()).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "UniversalAIBackend/0.6",
            "Accept": "application/json",
            "X-Request-ID": str(uuid4()),
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        timeout_s: float = 45.0,
    ) -> Any:
        url = f"{self._api_url}/{path.lstrip('/')}"
        timeout = httpx.Timeout(timeout_s, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Unable to reach Base44 API ({type(exc).__name__})",
            ) from exc

        if response.status_code >= 400:
            detail_msg = f"Base44 API returned HTTP {response.status_code}"
            try:
                err_data = response.json()
                if isinstance(err_data, dict):
                    msg = err_data.get("message") or err_data.get("detail")
                    if isinstance(msg, str) and msg.strip():
                        detail_msg = f"Base44 API ({response.status_code}): {msg[:300]}"
            except ValueError:
                pass
            raise HTTPException(status_code=502 if response.status_code >= 500 else response.status_code, detail=detail_msg)

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Base44 API returned invalid JSON") from exc

    async def list_apps(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/api/apps",
            params={
                "sort": "-updated_date",
                "fields": "id,name,user_description,is_managed_source_code",
                "limit": max(1, min(limit, 100)),
            },
        )
        if isinstance(data, list):
            raw_apps = data
        elif isinstance(data, dict):
            raw_apps = data.get("apps") or data.get("items") or data.get("results") or []
        else:
            raw_apps = []
        apps: list[dict[str, Any]] = []
        for item in raw_apps:
            if isinstance(item, dict) and item.get("id"):
                apps.append(
                    {
                        "id": str(item["id"]),
                        "name": str(item.get("name") or item["id"]),
                        "description": str(item.get("user_description") or ""),
                        "is_managed_source_code": item.get("is_managed_source_code"),
                    }
                )
        return apps

    async def get_app(self, app_id: str) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        data = await self._request("GET", f"/api/apps/{aid}")
        return data if isinstance(data, dict) else {"id": aid}

    async def get_published_url(self, app_id: str) -> str | None:
        aid = _validate_app_id(app_id)
        try:
            data = await self._request("GET", f"/api/apps/platform/{aid}/published-url")
        except HTTPException:
            return None
        if isinstance(data, dict):
            val = data.get("url") or data.get("published_url") or data.get("publishedUrl")
            return str(val) if val else None
        if isinstance(data, str) and data.startswith("http"):
            return data
        return None

    async def list_secret_keys(self, app_id: str) -> list[str]:
        aid = _validate_app_id(app_id)
        data = await self._request("GET", f"/api/apps/{aid}/secrets")
        if isinstance(data, dict):
            return sorted(str(k) for k in data.keys())
        if isinstance(data, list):
            return sorted(
                str(item.get("name") or item.get("key") or item)
                for item in data
                if item
            )
        return []

    async def set_secrets(self, app_id: str, secrets_payload: dict[str, str]) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        clean = {k: v for k, v in secrets_payload.items() if k and isinstance(v, str) and v.strip()}
        data = await self._request("POST", f"/api/apps/{aid}/secrets", json_body=clean, timeout_s=60.0)
        return {"updated_keys": sorted(clean.keys()), "result": data}

    async def list_backend_functions(self, app_id: str) -> list[str]:
        aid = _validate_app_id(app_id)
        data = await self._request("GET", f"/api/apps/{aid}/backend-functions", timeout_s=30.0)
        if isinstance(data, dict) and isinstance(data.get("functions"), list):
            return [str(fn.get("name")) for fn in data["functions"] if isinstance(fn, dict) and fn.get("name")]
        return []

    async def deploy_backend_function(
        self,
        app_id: str,
        function_name: str,
        entry_code: str,
    ) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        if not FUNCTION_NAME_RE.fullmatch(function_name):
            raise HTTPException(status_code=400, detail="Invalid Base44 function name")
        payload = {
            "entry": "entry.ts",
            "files": [{"path": "entry.ts", "content": entry_code}],
            "automations": [],
        }
        data = await self._request(
            "PUT",
            f"/api/apps/{aid}/backend-functions/{function_name}",
            json_body=payload,
            timeout_s=90.0,
        )
        return data if isinstance(data, dict) else {"status": "deployed"}

    async def sandbox_call(
        self,
        app_id: str,
        tool: str,
        payload: dict[str, Any],
        timeout_s: float = 90.0,
    ) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        allowed_tools = {
            "list_directory",
            "read_file",
            "write_file",
            "edit_file",
            "grep",
            "run_command",
            "create_checkpoint",
        }
        if tool not in allowed_tools:
            raise HTTPException(status_code=400, detail=f"Unsupported sandbox tool {tool!r}")
        data = await self._request(
            "POST",
            f"/api/apps/{aid}/sandbox-bridge/{tool}",
            json_body=payload,
            timeout_s=timeout_s,
        )
        return data if isinstance(data, dict) else {}

    async def mcp_request(self, method: str, params: dict[str, Any] | None = None, timeout_s: float = 120.0) -> Any:
        url = f"{self._api_url}/mcp"
        headers = {
            **self._headers(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": method,
            "params": params or {},
        }
        timeout = httpx.Timeout(timeout_s, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            return {"error_status": resp.status_code, "body": resp.text[:400]}
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype or text.lstrip().startswith("event:") or "data: " in text:
            events = []
            for line in text.splitlines():
                if line.startswith("data: "):
                    raw = line[6:].strip()
                    if raw:
                        try:
                            events.append(json.loads(raw))
                        except ValueError:
                            events.append({"raw": raw[:300]})
            return events[-1] if events else {"raw": text[:400]}
        try:
            return resp.json()
        except ValueError:
            return {"raw": text[:400]}

    async def sync_universal_agent(self, app_id: str) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        existing_resp = await self._request("GET", f"/api/apps/{aid}/agent-configs", timeout_s=30.0)
        existing_items = existing_resp.get("items", []) if isinstance(existing_resp, dict) else []
        preserved: list[dict[str, Any]] = []
        for item in existing_items:
            if isinstance(item, dict) and item.get("name") and item.get("name") != "universal_ai_hub_agent":
                preserved.append(
                    {
                        "name": item["name"],
                        "description": item.get("description") or f"Agent {item['name']}",
                        "instructions": item.get("instructions") or "Assist the user.",
                        "tool_configs": item.get("tool_configs") or [],
                        "selected_skill_names": item.get("selected_skill_names") or [],
                        **(
                            {"memory_config": item["memory_config"]}
                            if isinstance(item.get("memory_config"), dict)
                            else {}
                        ),
                        **(
                            {"whatsapp_greeting": item["whatsapp_greeting"]}
                            if item.get("whatsapp_greeting") is not None
                            else {}
                        ),
                    }
                )
        universal_agent = {
            "name": "universal_ai_hub_agent",
            "description": "Universal AI & REA Assistant connected to 6,122+ global AI & MCP tools, 229 REA reverse-engineering MCP tools, 45 LLM providers, 38 specialist agents, 27 workflows, and live GitHub discovery.",
            "instructions": (
                "You are connected to the live Universal AI Backend v0.6 via the `universalAiBackend` backend function. "
                "Call `universalAiBackend` with `{ action, payload }` to search 6,122+ AI/MCP tools (`action: 'tools'`), "
                "get catalog statistics (`action: 'stats'`), explore 229 REA reverse-engineering MCP tools (`action: 'rea_tools'` / `'rea_status'`), "
                "check 45 LLM providers (`action: 'providers'`), list 38 specialist agent blueprints (`action: 'agents'`), "
                "list 27 workflows (`action: 'workflows'`), discover live GitHub AI repos (`action: 'discover_github'`), "
                "or run multi-provider chat (`action: 'chat'`). Always present clear, actionable answers with links."
            ),
            "tool_configs": [
                {
                    "function_name": "universalAiBackend",
                    "description": "Invoke Universal AI Backend v0.6 (stats, tools, rea_status, rea_tools, providers, agents, workflows, channels, voice_models, discover_categories, discover_github, chat)",
                }
            ],
            "selected_skill_names": [],
        }
        merged = preserved + [universal_agent]
        sync_res = await self._request("PUT", f"/api/apps/{aid}/agent-configs", json_body=merged, timeout_s=60.0)
        return {"existing_preserved": len(preserved), "sync_result": sync_res}

    async def inspect_ejected_source(self, app_id: str) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        url = f"{self._api_url}/api/apps/{aid}/eject"
        timeout = httpx.Timeout(90.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=self._headers())
        if resp.status_code >= 400:
            return {"status": "error", "http_status": resp.status_code, "detail": resp.text[:300]}
        raw_bytes = resp.content
        files_list: list[str] = []
        key_files: dict[str, str] = {}
        wanted_suffixes = (
            "package.json",
            "vite.config.js",
            "vite.config.ts",
            "src/App.jsx",
            "src/App.tsx",
            "src/Layout.jsx",
            "src/Layout.tsx",
            "src/pages.config.js",
            "src/pages.config.ts",
        )
        with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                norm = member.name.lstrip("./")
                files_list.append(norm)
                if any(norm == w or norm.endswith("/" + w) for w in wanted_suffixes):
                    extracted = tf.extractfile(member)
                    if extracted:
                        key_files[norm] = extracted.read().decode("utf-8", errors="replace")[:12000]
        return {
            "status": "ok",
            "archive_bytes": len(raw_bytes),
            "file_count": len(files_list),
            "files": sorted(files_list)[:200],
            "key_files": key_files,
        }

    async def export_ejected_files_bundle(self, app_id: str) -> dict[str, Any]:
        """Return text source files from `/eject` (excluding node_modules/dist/.env) so a builder can compile `dist.tar.gz`."""
        aid = _validate_app_id(app_id)
        url = f"{self._api_url}/api/apps/{aid}/eject"
        timeout = httpx.Timeout(90.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=self._headers())
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"Eject failed ({resp.status_code})")
        text_files: dict[str, str] = {}
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile() or member.size > 400_000:
                    continue
                norm = member.name.lstrip("./")
                if any(part in {"node_modules", "dist", ".git"} for part in norm.split("/")):
                    continue
                if os.path.basename(norm).startswith(".env"):
                    continue
                extracted = tf.extractfile(member)
                if extracted:
                    raw = extracted.read()
                    try:
                        text_files[norm] = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
        return {"app_id": aid, "file_count": len(text_files), "files": text_files}

    async def upload_site_dist(self, app_id: str, dist_tar_gz: bytes) -> dict[str, Any]:
        aid = _validate_app_id(app_id)
        url = f"{self._api_url}/api/apps/{aid}/deploy-dist"
        timeout = httpx.Timeout(180.0, connect=15.0)
        files = {"file": ("dist.tar.gz", dist_tar_gz, "application/gzip")}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(url, headers=self._headers(), files=files)
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502 if resp.status_code >= 500 else resp.status_code,
                detail=f"Base44 deploy-dist returned {resp.status_code}: {resp.text[:300]}",
            )
        try:
            return resp.json()
        except ValueError:
            return {"status": "uploaded", "http_status": resp.status_code}


def build_base44_backend_function_code(default_backend_url: str | None = None) -> str:
    """Return the Base44 Deno/Worker backend function (`entry.ts`) for `universalAiBackend`."""
    fallback_url = (default_backend_url or get_public_backend_url()).rstrip("/")
    return f'''import {{ createClientFromRequest }} from "npm:@base44/sdk";
import {{ secrets }} from "base44:runtime";

const DEFAULT_BACKEND_URL = "{fallback_url}";

const PUBLIC_READ_ACTIONS = new Set([
  "health",
  "stats",
  "tools",
  "tool_detail",
  "rea_status",
  "rea_tools",
  "providers",
  "agents",
  "workflows",
  "channels",
  "voice_models",
  "discover_categories",
  "discover_github",
]);

function buildQuery(params) {{
  const qs = new URLSearchParams();
  for (const [key, val] of Object.entries(params || {{}})) {{
    if (val !== undefined && val !== null && val !== "") {{
      qs.set(key, String(val));
    }}
  }}
  const rendered = qs.toString();
  return rendered ? `?${{rendered}}` : "";
}}

export default async function (req) {{
  if (req.method === "OPTIONS") {{
    return new Response(null, {{ status: 204 }});
  }}

  const base44 = createClientFromRequest(req);
  let body = {{}};
  try {{
    body = await req.json();
  }} catch {{
    body = {{}};
  }}

  const action = String(body.action || "stats").trim();
  const payload = body.payload && typeof body.payload === "object" ? body.payload : body;

  if (!PUBLIC_READ_ACTIONS.has(action)) {{
    try {{
      const user = await base44.auth.me();
      if (!user) {{
        return Response.json({{ error: "Authentication required for this backend action." }}, {{ status: 401 }});
      }}
    }} catch {{
      return Response.json({{ error: "Authentication required for this backend action." }}, {{ status: 401 }});
    }}
  }}

  const backendUrl = String(secrets.get("UNIVERSAL_AI_BACKEND_URL") || DEFAULT_BACKEND_URL).replace(/\\/+$/, "");
  const backendApiKey = String(secrets.get("UNIVERSAL_AI_BACKEND_API_KEY") || "");

  let method = "GET";
  let path = "/v1/catalog/stats";
  let jsonBody = undefined;
  let needsKey = false;

  switch (action) {{
    case "health":
      path = "/health";
      break;
    case "stats":
      path = "/v1/catalog/stats";
      break;
    case "tools":
      path = "/v1/tools" + buildQuery({{
        q: payload.q,
        category: payload.category,
        kind: payload.mcp_only ? "mcp_server" : payload.kind,
        capability: payload.capability,
        license_status: payload.license_status,
        source_classification: payload.source_classification,
        min_stars: payload.min_stars,
        language: payload.language,
        limit: payload.limit || 60,
        offset: payload.offset || 0,
      }});
      break;
    case "tool_detail":
      path = `/v1/tools/${{encodeURIComponent(String(payload.tool_id || "") )}}`;
      break;
    case "register_tool":
      method = "POST";
      path = "/v1/tools";
      jsonBody = payload.tool || payload;
      needsKey = true;
      break;
    case "rea_status":
      path = "/v1/rea/status";
      break;
    case "rea_tools":
      path = "/v1/rea/tools" + buildQuery({{
        q: payload.q,
        family: payload.family,
        limit: payload.limit || 100,
      }});
      break;
    case "rea_inspect":
      method = "POST";
      path = "/v1/rea/inspect";
      jsonBody = payload;
      needsKey = true;
      break;
    case "rea_job":
      method = "POST";
      path = "/v1/rea/jobs";
      jsonBody = payload;
      needsKey = true;
      break;
    case "providers":
      path = "/v1/models/providers";
      break;
    case "agents":
      path = "/v1/agents";
      break;
    case "agent_run":
      method = "POST";
      path = `/v1/agents/${{encodeURIComponent(String(payload.agent_id || "research-agent"))}}/run`;
      jsonBody = {{
        objective: payload.objective,
        inputs: payload.inputs || {{}},
        user_approved: Boolean(payload.user_approved),
        dry_run: Boolean(payload.dry_run),
      }};
      needsKey = true;
      break;
    case "workflows":
      path = "/v1/workflows";
      break;
    case "workflow_run":
      method = "POST";
      path = `/v1/workflows/${{encodeURIComponent(String(payload.workflow_id || "") )}}/run`;
      jsonBody = {{
        inputs: payload.inputs || {{}},
        user_approved: Boolean(payload.user_approved),
        dry_run: Boolean(payload.dry_run),
      }};
      needsKey = true;
      break;
    case "channels":
      path = "/v1/channels";
      break;
    case "channel_action":
      method = "POST";
      path = `/v1/channels/${{encodeURIComponent(String(payload.channel_id || "") )}}/actions`;
      jsonBody = payload;
      needsKey = true;
      break;
    case "voice_models":
      path = "/v1/voice/providers";
      break;
    case "voice_tts":
      method = "POST";
      path = "/v1/voice/tts";
      jsonBody = payload;
      needsKey = true;
      break;
    case "media_job":
      method = "POST";
      path = "/v1/media/jobs";
      jsonBody = payload;
      needsKey = true;
      break;
    case "discover_categories":
      path = "/v1/discover/categories";
      break;
    case "discover_github":
      path = "/v1/discover/github" + buildQuery({{
        category_preset: payload.category_preset || payload.preset,
        q: payload.q,
        min_stars: payload.min_stars,
        license_filter: payload.license_filter,
        sort: payload.sort || "stars",
        per_page: payload.per_page || 24,
      }});
      break;
    case "chat":
      method = "POST";
      path = "/v1/chat/completions";
      jsonBody = {{
        provider: payload.provider || "groq",
        model: payload.model || "",
        messages: payload.messages || [{{ role: "user", content: String(payload.prompt || "") }}],
        temperature: typeof payload.temperature === "number" ? payload.temperature : 0.7,
        max_tokens: payload.max_tokens || 1024,
      }};
      needsKey = true;
      break;
    case "task_status":
      path = `/v1/tasks/${{encodeURIComponent(String(payload.service || "rea"))}}/${{encodeURIComponent(String(payload.task_id || ""))}}`;
      needsKey = true;
      break;
    default:
      return Response.json(
        {{ error: `Unsupported action: ${{action}}` }},
        {{ status: 400 }},
      );
  }}

  const headers = {{
    "Accept": "application/json",
    "Content-Type": "application/json",
  }};
  if (needsKey && backendApiKey) {{
    headers["X-API-Key"] = backendApiKey;
  }}

  try {{
    const upstream = await fetch(`${{backendUrl}}${{path}}`, {{
      method,
      headers,
      body: jsonBody !== undefined ? JSON.stringify(jsonBody) : undefined,
    }});

    const data = await upstream.json().catch(() => ({{ status: upstream.status }}));

    // Seamless fallback to Base44 Core LLM if external provider key is not yet set on Vercel
    if (action === "chat" && upstream.status === 503 && base44?.asServiceRole?.integrations?.Core?.InvokeLLM) {{
      const msgs = Array.isArray(jsonBody?.messages) ? jsonBody.messages : [];
      const promptText = msgs.map((m) => `${{m.role || "user"}}: ${{m.content || ""}}`).join("\\n\\n");
      const llmReply = await base44.asServiceRole.integrations.Core.InvokeLLM({{ prompt: promptText }});
      return Response.json({{
        provider: "base44-core-fallback",
        backend_url: backendUrl,
        reply: typeof llmReply === "string" ? llmReply : JSON.stringify(llmReply),
        raw: llmReply,
      }});
    }}

    return Response.json(data, {{ status: upstream.status }});
  }} catch (err) {{
    return Response.json(
      {{ error: "Failed to reach Universal AI Backend", detail: String(err?.message || err) }},
      {{ status: 502 }},
    );
  }}
}}
'''


def build_base44_frontend_sdk_code() -> str:
    """Return `src/lib/universalAiBackend.js` for Base44 React/Vite apps."""
    return '''import { base44 } from "@/api/base44Client";

async function invokeBackend(action, payload = {}) {
  const response = await base44.functions.invoke("universalAiBackend", {
    action,
    payload,
  });
  return response?.data ?? response;
}

export const universalAiBackend = {
  invoke: invokeBackend,
  health: () => invokeBackend("health"),
  getStats: () => invokeBackend("stats"),
  searchTools: (params = {}) => invokeBackend("tools", params),
  getTool: (toolId) => invokeBackend("tool_detail", { tool_id: toolId }),
  registerTool: (tool) => invokeBackend("register_tool", { tool }),
  getReaStatus: () => invokeBackend("rea_status"),
  searchReaTools: (params = {}) => invokeBackend("rea_tools", params),
  runReaInspect: (params) => invokeBackend("rea_inspect", params),
  listProviders: () => invokeBackend("providers"),
  listAgents: () => invokeBackend("agents"),
  runAgentPlan: (agentId, objective, inputs = {}, options = {}) =>
    invokeBackend("agent_run", { agent_id: agentId, objective, inputs, ...options }),
  listWorkflows: () => invokeBackend("workflows"),
  runWorkflow: (workflowId, inputs = {}, options = {}) =>
    invokeBackend("workflow_run", { workflow_id: workflowId, inputs, ...options }),
  listChannels: () => invokeBackend("channels"),
  listVoiceModels: () => invokeBackend("voice_models"),
  listDiscoveryCategories: () => invokeBackend("discover_categories"),
  discoverGithub: (params = {}) => invokeBackend("discover_github", params),
  chat: ({ provider = "groq", model = "", messages = [], prompt = "", temperature = 0.7, max_tokens = 1024 } = {}) =>
    invokeBackend("chat", {
      provider,
      model,
      messages: messages.length ? messages : [{ role: "user", content: prompt }],
      temperature,
      max_tokens,
    }),
  getTaskStatus: (service, taskId) =>
    invokeBackend("task_status", { service, task_id: taskId }),
};

export default universalAiBackend;
'''


def build_base44_hub_page_code() -> str:
    """Return a self-contained React page (`src/pages/UniversalAiHub.jsx`) for Base44 apps."""
    return '''import React, { useEffect, useState } from "react";
import { universalAiBackend } from "@/lib/universalAiBackend";

export default function UniversalAiHub() {
  const [tab, setTab] = useState("tools");
  const [stats, setStats] = useState(null);
  const [reaStatus, setReaStatus] = useState(null);
  const [providers, setProviders] = useState(null);
  const [agents, setAgents] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [presets, setPresets] = useState([]);
  const [tools, setTools] = useState([]);
  const [toolsTotal, setToolsTotal] = useState(0);
  const [reaTools, setReaTools] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [mcpOnly, setMcpOnly] = useState(false);
  const [reaQuery, setReaQuery] = useState("");
  const [reaFamily, setReaFamily] = useState("");
  const [selectedPreset, setSelectedPreset] = useState("mcp-servers");
  const [githubItems, setGithubItems] = useState([]);
  const [chatPrompt, setChatPrompt] = useState("");
  const [chatProvider, setChatProvider] = useState("groq");
  const [chatReply, setChatReply] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function boot() {
      try {
        const [st, rs, pr, ag, wf, dc, tl] = await Promise.all([
          universalAiBackend.getStats(),
          universalAiBackend.getReaStatus(),
          universalAiBackend.listProviders(),
          universalAiBackend.listAgents(),
          universalAiBackend.listWorkflows(),
          universalAiBackend.listDiscoveryCategories(),
          universalAiBackend.searchTools({ limit: 48 }),
        ]);
        if (!mounted) return;
        setStats(st);
        setReaStatus(rs);
        setProviders(pr);
        setAgents(ag?.items || []);
        setWorkflows(wf?.items || []);
        setPresets(Array.isArray(dc?.presets) ? dc.presets : []);
        setTools(tl?.items || []);
        setToolsTotal(tl?.total || 0);
      } catch (err) {
        if (mounted) setError(String(err?.message || err));
      } finally {
        if (mounted) setLoading(false);
      }
    }
    boot();
    return () => {
      mounted = false;
    };
  }, []);

  async function runToolSearch(e) {
    if (e) e.preventDefault();
    setLoading(true);
    try {
      const res = await universalAiBackend.searchTools({
        q: query,
        category,
        mcp_only: mcpOnly ? true : undefined,
        limit: 60,
      });
      setTools(res?.items || []);
      setToolsTotal(res?.total || 0);
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function runReaSearch(e) {
    if (e) e.preventDefault();
    const res = await universalAiBackend.searchReaTools({
      q: reaQuery,
      family: reaFamily,
      limit: 90,
    });
    setReaTools(res?.items || []);
  }

  useEffect(() => {
    if (tab === "rea" && reaTools.length === 0) {
      runReaSearch();
    }
  }, [tab]);

  async function runLiveGithubSearch() {
    setLoading(true);
    try {
      const res = await universalAiBackend.discoverGithub({
        preset: selectedPreset,
        min_stars: 50,
        per_page: 24,
      });
      setGithubItems(res?.items || []);
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function handleChatSend(e) {
    e.preventDefault();
    if (!chatPrompt.trim()) return;
    setChatReply("Thinking...");
    try {
      const res = await universalAiBackend.chat({
        provider: chatProvider,
        prompt: chatPrompt,
      });
      const content =
        res?.reply ||
        res?.data?.choices?.[0]?.message?.content ||
        res?.data?.content?.[0]?.text ||
        JSON.stringify(res, null, 2);
      setChatReply(content);
    } catch (err) {
      setChatReply(`Error: ${err?.message || err}`);
    }
  }

  const categories = Object.entries(stats?.categories || {});
  const reaFamilies = Object.entries(reaStatus?.family_counts || {});

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs font-medium mb-2">
              Connected to Universal AI Backend v0.6
            </div>
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight">
              Universal AI & REA Control Hub
            </h1>
            <p className="text-slate-400 text-sm mt-1">
              6,120+ Global AI & MCP Tools, 229 REA Reverse-Engineering MCP Tools, 45 LLM Providers, Agents & Live Discovery
            </p>
          </div>
        </div>

        {error && (
          <div className="rounded-xl bg-red-950/60 border border-red-800 p-4 text-sm text-red-200">
            {error}
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          {[
            ["AI & MCP Tools", stats?.total_tools ?? "..."],
            ["Categories", categories.length || "..."],
            ["MCP Ecosystem", stats?.separate_manifests?.mcp_ecosystem_records ?? "..."],
            ["REA MCP Tools", stats?.separate_manifests?.rea_mcp_tools ?? "..."],
            ["LLM Providers", providers?.total ?? "..."],
            ["Agents & Workflows", `${agents.length} / ${workflows.length}`],
          ].map(([label, val]) => (
            <div key={label} className="rounded-xl bg-slate-900 border border-slate-800 p-4">
              <div className="text-xs text-slate-400">{label}</div>
              <div className="text-xl font-bold text-indigo-400 mt-1">{val}</div>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          {[
            ["tools", "Global AI & MCP Catalog"],
            ["rea", "REA Reverse-Engineering (229)"],
            ["providers", "45 LLM Providers"],
            ["agents", "Agents & Workflows"],
            ["discover", "Live GitHub AI Discovery"],
            ["chat", "AI Chat Gateway"],
          ].map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
                tab === id
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-900 text-slate-300 border border-slate-800 hover:border-indigo-500"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "tools" && (
          <div className="space-y-4">
            <form onSubmit={runToolSearch} className="flex flex-wrap gap-3 bg-slate-900 p-4 rounded-xl border border-slate-800">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search 6,120+ AI tools, MCP servers, coding agents, TTS, RAG..."
                className="flex-1 min-w-[240px] bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
              />
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">All Categories ({categories.length})</option>
                {categories.map(([cat, count]) => (
                  <option key={cat} value={cat}>
                    {cat} ({count})
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-sm text-slate-300 px-2">
                <input
                  type="checkbox"
                  checked={mcpOnly}
                  onChange={(e) => setMcpOnly(e.target.checked)}
                />
                MCP Only
              </label>
              <button
                type="submit"
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-semibold"
              >
                Search ({toolsTotal})
              </button>
            </form>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {tools.map((tool) => (
                <div key={tool.id} className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex flex-col justify-between gap-3">
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="font-semibold text-sm text-white">{tool.name}</h3>
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 whitespace-nowrap">
                        {tool.category}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-2 line-clamp-3">
                      {tool.description || "Cataloged AI / MCP tool"}
                    </p>
                  </div>
                  <div className="flex items-center justify-between text-xs pt-2 border-t border-slate-800/80">
                    <span className="text-slate-500">{tool.stars ? `★ ${tool.stars}` : tool.kind}</span>
                    {tool.repository_url && (
                      <a
                        href={tool.repository_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-cyan-400 hover:underline"
                      >
                        Open Tool ↗
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "rea" && (
          <div className="space-y-4">
            <form onSubmit={runReaSearch} className="flex flex-wrap gap-3 bg-slate-900 p-4 rounded-xl border border-slate-800">
              <input
                value={reaQuery}
                onChange={(e) => setReaQuery(e.target.value)}
                placeholder="Search 229 REA MCP tools (webmcp, safetensors, gguf, electron, apk...)"
                className="flex-1 min-w-[240px] bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
              />
              <select
                value={reaFamily}
                onChange={(e) => setReaFamily(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">All 25 REA Families</option>
                {reaFamilies.map(([fam, cnt]) => (
                  <option key={fam} value={fam}>
                    {fam} ({cnt})
                  </option>
                ))}
              </select>
              <button
                type="submit"
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-semibold"
              >
                Filter REA Tools
              </button>
            </form>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {reaTools.map((rt) => (
                <div key={rt.name} className="rounded-xl bg-slate-900 border border-slate-800 p-4 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <code className="text-xs font-bold text-emerald-300">{rt.name}</code>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-800 text-cyan-300">
                      {rt.family}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{rt.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "providers" && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(providers?.providers || {}).map(([name, info]) => (
              <div key={name} className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex items-center justify-between">
                <div>
                  <div className="font-semibold text-sm">{name}</div>
                  <div className="text-xs text-slate-400">
                    {info.transport} · {info.default_model || "custom model"}
                  </div>
                </div>
                <span
                  className={`text-xs px-2.5 py-1 rounded-full ${
                    info.configured
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-amber-500/15 text-amber-300"
                  }`}
                >
                  {info.configured ? "Ready" : "Set Key"}
                </span>
              </div>
            ))}
          </div>
        )}

        {tab === "agents" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {agents.map((ag) => (
              <div key={ag.id} className="rounded-xl bg-slate-900 border border-slate-800 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-sm">{ag.name}</h3>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300">
                    {ag.risk_level}
                  </span>
                </div>
                <p className="text-xs text-slate-400">{ag.mission}</p>
              </div>
            ))}
          </div>
        )}

        {tab === "discover" && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-3 bg-slate-900 p-4 rounded-xl border border-slate-800">
              <select
                value={selectedPreset}
                onChange={(e) => setSelectedPreset(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
              >
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.id} ({p.catalog_count} indexed)
                  </option>
                ))}
              </select>
              <button
                onClick={runLiveGithubSearch}
                className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-semibold"
              >
                Discover Live on GitHub
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {githubItems.map((repo) => (
                <div key={repo.full_name} className="rounded-xl bg-slate-900 border border-slate-800 p-4 space-y-2">
                  <div className="font-semibold text-sm">{repo.full_name}</div>
                  <p className="text-xs text-slate-400">{repo.description}</p>
                  <div className="flex items-center justify-between text-xs pt-2">
                    <span className="text-amber-300">★ {repo.stars}</span>
                    <a href={repo.url} target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">
                      GitHub ↗
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "chat" && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <form onSubmit={handleChatSend} className="space-y-3">
              <div className="flex flex-wrap gap-3">
                <select
                  value={chatProvider}
                  onChange={(e) => setChatProvider(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
                >
                  {Object.keys(providers?.providers || { groq: {}, openai: {}, gemini: {} }).map((p) => (
                    <option key={p} value={p}>
                      Provider: {p}
                    </option>
                  ))}
                </select>
                <input
                  value={chatPrompt}
                  onChange={(e) => setChatPrompt(e.target.value)}
                  placeholder="Ask Universal AI Backend..."
                  className="flex-1 min-w-[240px] bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg text-sm font-semibold"
                >
                  Send
                </button>
              </div>
            </form>
            {chatReply && (
              <pre className="whitespace-pre-wrap text-sm bg-slate-950 border border-slate-800 rounded-xl p-4 text-slate-200">
                {chatReply}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
'''


async def connect_base44_app(
    app_id: str,
    *,
    backend_url: str | None = None,
    backend_api_key: str | None = None,
    install_frontend_files: bool = True,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Configure secrets, deploy `universalAiBackend` function, and optionally sync SDK/UI files."""
    client = Base44Client(access_token=access_token)
    target_url = (backend_url or get_public_backend_url()).strip().rstrip("/")
    shared_key = (backend_api_key or os.getenv("BACKEND_API_KEY") or "").strip()
    if not shared_key:
        raise HTTPException(
            status_code=503,
            detail="BACKEND_API_KEY must be set before connecting a Base44 app.",
        )

    app_info = await client.get_app(app_id)
    published_url = await client.get_published_url(app_id)

    secrets_result = await client.set_secrets(
        app_id,
        {
            "UNIVERSAL_AI_BACKEND_URL": target_url,
            "UNIVERSAL_AI_BACKEND_API_KEY": shared_key,
        },
    )

    fn_code = build_base44_backend_function_code(default_backend_url=target_url)
    fn_result = await client.deploy_backend_function(app_id, "universalAiBackend", fn_code)

    sandbox_summary: dict[str, Any] = {"attempted": install_frontend_files, "synced_files": []}
    if install_frontend_files:
        try:
            sdk_res = await client.sandbox_call(
                app_id,
                "write_file",
                {
                    "path": "src/lib/universalAiBackend.js",
                    "content": build_base44_frontend_sdk_code(),
                    "overwrite": True,
                },
            )
            sandbox_summary["synced_files"].append(sdk_res.get("path", "src/lib/universalAiBackend.js"))

            hub_res = await client.sandbox_call(
                app_id,
                "write_file",
                {
                    "path": "src/pages/UniversalAiHub.jsx",
                    "content": build_base44_hub_page_code(),
                    "overwrite": True,
                },
            )
            sandbox_summary["synced_files"].append(hub_res.get("path", "src/pages/UniversalAiHub.jsx"))

            cp = await client.sandbox_call(
                app_id,
                "create_checkpoint",
                {"name": "Connect Universal AI Backend v0.6 (SDK + UniversalAiHub)"},
            )
            sandbox_summary["checkpoint"] = cp
            sandbox_summary["status"] = "synced"
        except HTTPException as exc:
            sandbox_summary["status"] = "skipped_or_missing_sandbox_scope"
            sandbox_summary["note"] = exc.detail

    return {
        "status": "connected",
        "app_id": app_id,
        "app_name": app_info.get("name", app_id),
        "published_url": published_url,
        "backend_url": target_url,
        "secrets_configured": secrets_result["updated_keys"],
        "backend_function": {
            "name": "universalAiBackend",
            "status": fn_result.get("status", "deployed"),
        },
        "sandbox": sandbox_summary,
    }


async def bootstrap_all_base44_apps(target_app_id: str | None = None) -> dict[str, Any]:
    """Connect all (or one specified) Base44 apps using server-side env credentials."""
    client = Base44Client()
    apps = await client.list_apps(limit=50)
    if target_app_id:
        apps = [a for a in apps if a["id"] == target_app_id.strip()]
    results: list[dict[str, Any]] = []
    target_url = get_public_backend_url()
    for item in apps:
        aid = item["id"]
        try:
            connected = await connect_base44_app(
                aid,
                backend_url=target_url,
                install_frontend_files=True,
            )
            # Also inspect & wire src/pages.config.js if sandbox is accessible
            if connected.get("sandbox", {}).get("status") == "synced":
                try:
                    ls_src = await client.sandbox_call(
                        aid,
                        "list_directory",
                        {"path": "src", "recursive": False},
                        timeout_s=30.0,
                    )
                    connected["sandbox"]["src_entries"] = [
                        e.get("name") for e in (ls_src.get("entries") or [])
                    ]
                    # Also sync function file into sandbox tree for full parity with builder
                    await client.sandbox_call(
                        aid,
                        "write_file",
                        {
                            "path": "base44/functions/universalAiBackend/entry.ts",
                            "content": build_base44_backend_function_code(default_backend_url=target_url),
                            "overwrite": True,
                        },
                        timeout_s=30.0,
                    )
                    rd = await client.sandbox_call(
                        aid,
                        "read_file",
                        {"paths": ["src/pages.config.js"]},
                        timeout_s=30.0,
                    )
                    files = rd.get("files") or []
                    if files and not files[0].get("error") and files[0].get("content"):
                        cfg_text = str(files[0]["content"])
                        if "UniversalAiHub" not in cfg_text and "export const PAGES = {" in cfg_text:
                            new_cfg = (
                                "import UniversalAiHub from './pages/UniversalAiHub';\n"
                                + cfg_text.replace(
                                    "export const PAGES = {",
                                    'export const PAGES = {\n    "UniversalAiHub": UniversalAiHub,',
                                    1,
                                )
                            )
                            await client.sandbox_call(
                                aid,
                                "write_file",
                                {"path": "src/pages.config.js", "content": new_cfg, "overwrite": True},
                                timeout_s=30.0,
                            )
                            connected["sandbox"]["pages_config"] = "UniversalAiHub_registered"
                            cp2 = await client.sandbox_call(
                                aid,
                                "create_checkpoint",
                                {"name": "Register UniversalAiHub route in pages.config.js"},
                                timeout_s=30.0,
                            )
                            connected["sandbox"]["route_checkpoint"] = cp2
                        elif "UniversalAiHub" in cfg_text:
                            connected["sandbox"]["pages_config"] = "already_registered"
                except HTTPException as sub_exc:
                    connected["sandbox"]["pages_config_note"] = sub_exc.detail
            results.append(connected)
        except HTTPException as exc:
            results.append({"app_id": aid, "app_name": item.get("name"), "status": "error", "detail": exc.detail})
    return {
        "status": "completed",
        "backend_url": target_url,
        "total_apps_found": len(apps),
        "apps": results,
    }


async def run_base44_auto_provision(
    mode: str = "inspect_and_agents",
    app_id: str | None = None,
    dist_url: str | None = None,
) -> dict[str, Any]:
    """End-to-end Base44 provisioning helper (agents, MCP edit, eject, deploy-dist)."""
    client = Base44Client()

    if mode == "inspect_and_agents":
        mcp_init = await client.mcp_request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "universal-ai-backend", "version": "0.6.0"},
            },
            timeout_s=30.0,
        )
        mcp_tools = await client.mcp_request("tools/list", {}, timeout_s=30.0)
        apps = await client.list_apps(limit=20)
        if app_id:
            apps = [a for a in apps if a["id"] == app_id]
        app_reports = []
        for item in apps:
            aid = item["id"]
            report: dict[str, Any] = {"id": aid, "name": item["name"]}
            try:
                report["agent_sync"] = await client.sync_universal_agent(aid)
            except Exception as exc:
                report["agent_sync_error"] = str(getattr(exc, "detail", exc))
            try:
                eject_info = await client.inspect_ejected_source(aid)
                report["eject"] = {
                    "status": eject_info.get("status"),
                    "http_status": eject_info.get("http_status"),
                    "archive_bytes": eject_info.get("archive_bytes"),
                    "file_count": eject_info.get("file_count"),
                    "files": eject_info.get("files"),
                    "key_files": eject_info.get("key_files"),
                }
            except Exception as exc:
                report["eject_error"] = str(getattr(exc, "detail", exc))
            app_reports.append(report)
        return {
            "mode": mode,
            "mcp_init": mcp_init,
            "mcp_tools": mcp_tools,
            "apps": app_reports,
        }

    if mode == "export_source":
        if not app_id:
            raise HTTPException(status_code=400, detail="app_id required for export_source")
        return await client.export_ejected_files_bundle(app_id)

    if mode == "mcp_edit":
        if not app_id:
            raise HTTPException(status_code=400, detail="app_id required for mcp_edit")
        prompt = (
            'The backend function "universalAiBackend" is already deployed with secrets configured — '
            "do NOT modify or recreate any backend function. Create a new page `UniversalAiHub` and add a prominent "
            '"Universal AI Hub" link in the main navigation/sidebar so users can open it with one click. '
            'In `UniversalAiHub`, use `base44.functions.invoke("universalAiBackend", { action, payload })` (reading `res.data`) '
            "with tabs for: (1) Global AI & MCP Catalog (`action: 'stats'` and `action: 'tools'` with search `q`, `category`, `mcp_only`), "
            "(2) REA 229 Reverse-Engineering MCP Tools (`action: 'rea_status'` and `action: 'rea_tools'` with `q` and `family`), "
            "(3) 45 LLM Providers & 38 Agents & 27 Workflows (`action: 'providers'`, `'agents'`, `'workflows'`), "
            "(4) Live GitHub AI Discovery (`action: 'discover_categories'` and `action: 'discover_github'`), and "
            "(5) Live AI Chat (`action: 'chat'` with `provider` and `prompt`)."
        )
        res = await client.mcp_request(
            "tools/call",
            {
                "name": "edit_base44_app",
                "arguments": {"app_id": app_id, "appId": app_id, "prompt": prompt, "instructions": prompt},
            },
            timeout_s=240.0,
        )
        return {"mode": mode, "app_id": app_id, "mcp_result": res}

    if mode == "deploy_github_dist":
        if not app_id or not dist_url:
            raise HTTPException(status_code=400, detail="app_id and dist_url required")
        if not dist_url.startswith("https://github.com/zeeburgers00-glitch/universal-ai-backend/") and not dist_url.startswith("https://objects.githubusercontent.com/"):
            raise HTTPException(status_code=400, detail="dist_url must come from zeeburgers00-glitch/universal-ai-backend")
        timeout = httpx.Timeout(90.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as dl_client:
            dl_resp = await dl_client.get(dist_url)
            dl_resp.raise_for_status()
            dist_bytes = dl_resp.content
        deploy_res = await client.upload_site_dist(app_id, dist_bytes)
        pub_url = await client.get_published_url(app_id)
        return {
            "mode": mode,
            "app_id": app_id,
            "uploaded_bytes": len(dist_bytes),
            "deploy_result": deploy_res,
            "published_url": pub_url,
        }

    raise HTTPException(status_code=400, detail=f"Unsupported mode {mode!r}")


