import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .base44_integration import (
    Base44Client,
    base44_status,
    build_base44_backend_function_code,
    build_base44_frontend_sdk_code,
    build_base44_hub_page_code,
    connect_base44_app,
)
from .explorer_ui import EXPLORER_HTML
from .github_discovery import list_discovery_presets, search_github_repositories
from .providers import chat_with_provider, provider_status
from .registry import Registry
from .security import require_api_key
from .task_gateway import get_worker, post_worker, service_status

APP_ROOT = Path(__file__).resolve().parent.parent
CATALOG_ROOT = APP_ROOT / "catalog"
registry = Registry.from_file()


@lru_cache(maxsize=16)
def load_manifest(filename: str) -> Any:
    path = (CATALOG_ROOT / filename).resolve()
    if CATALOG_ROOT.resolve() not in path.parents:
        raise ValueError("Invalid catalog filename")
    if not path.exists():
        raise FileNotFoundError(filename)
    return json.loads(path.read_text(encoding="utf-8"))


app = FastAPI(
    title="Universal AI Backend",
    description="API-only control plane for AI models, agents, MCP servers, REA reverse-engineering inspection, media workers, creator workflows, channels, and paired JARVIS devices.",
    version="0.6.0",
)

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
origin_regex = (os.getenv("CORS_ORIGIN_REGEX") or "").strip() or None
# Production must specify exact web origins or a scoped origin regex; localhost defaults are for development only.
if not origins and not origin_regex and os.getenv("VERCEL") != "1":
    origins = ["http://localhost:3000", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


class ChatRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1, max_length=80)
    model: str = Field(default="", max_length=200)
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int | None = Field(default=1024, ge=1, le=32768)


class ToolRegistration(BaseModel):
    id: str = Field(min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    kind: str = Field(default="external", max_length=80)
    description: str = Field(default="", max_length=4000)
    repository_url: str | None = None
    docs_url: str | None = None
    license: str | None = None
    install_command: str | None = None
    integration_type: str = "manual"
    status: str = "catalog_only"
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    permissions: list[str] = Field(default_factory=list, max_length=50)
    risk_level: str = "unknown"


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class AgentRunRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=12000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")



class VoiceAssetUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/mp3", "audio/ogg", "audio/flac", "audio/x-wav"]
    content_base64: str = Field(min_length=40, max_length=4_000_000)
    speaker_consent_confirmed: bool = False
    speaker_consent_record_id: str = Field(min_length=8, max_length=300)
    consent_scope: str = Field(default="voice_cloning_and_tts", min_length=3, max_length=160)


class VoiceTTSRequest(BaseModel):
    engine: str = Field(default="melo-tts", min_length=2, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    text: str = Field(min_length=1, max_length=12000)
    language: str | None = Field(default=None, max_length=40)
    voice_profile_id: str | None = Field(default=None, max_length=200)
    reference_audio_asset_id: str | None = Field(default=None, max_length=300)
    reference_transcript: str | None = Field(default=None, max_length=5000)
    speaker_consent_confirmed: bool = False
    speaker_consent_record_id: str | None = Field(default=None, max_length=300)
    commercial_use: bool = True
    output_format: Literal["wav", "mp3", "ogg", "flac"] = "wav"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class VoiceCloneRequest(BaseModel):
    engine: str = Field(default="f5-tts", min_length=2, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    reference_audio_asset_id: str = Field(min_length=3, max_length=300)
    reference_transcript: str | None = Field(default=None, max_length=5000)
    speaker_consent_confirmed: bool = False
    speaker_consent_record_id: str | None = Field(default=None, max_length=300)
    commercial_use: bool = True
    voice_profile_name: str = Field(min_length=2, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class MediaJobRequest(BaseModel):
    task_type: Literal["image", "video", "audio", "music", "lip_sync", "captions", "render", "transcribe", "thumbnail"]
    inputs: dict[str, Any] = Field(default_factory=dict)
    commercial_use: bool = True
    user_approved: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class ChannelActionRequest(BaseModel):
    connection_id: str = Field(min_length=3, max_length=300)
    action: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    target_id: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=12000)
    title: str | None = Field(default=None, max_length=300)
    approved_template_name: str | None = Field(default=None, max_length=200)
    user_approved: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class YouTubePublishRequest(BaseModel):
    channel_connection_id: str = Field(min_length=3, max_length=300)
    video_asset_id: str = Field(min_length=3, max_length=300)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    publish_at: str | None = Field(default=None, max_length=40)
    self_declared_made_for_kids: bool | None = None
    user_approved: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class ReaToolCallRequest(BaseModel):
    paired_device_id: str = Field(min_length=3, max_length=300)
    tool_name: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/-]+$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    authorization_scope_confirmed: bool = False
    authorization_scope_note: str = Field(min_length=15, max_length=2000)


class Base44ConnectRequest(BaseModel):
    app_id: str = Field(min_length=6, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    backend_url: str | None = Field(default=None, max_length=300)
    install_frontend_files: bool = True


class DesktopActionRequest(BaseModel):
    paired_device_id: str = Field(min_length=3, max_length=300)
    action: Literal[
        "get_status", "capture_screen", "open_app", "open_url", "type_text", "click",
        "read_file", "write_file", "delete_file", "install_software", "run_approved_script",
        "send_message", "change_system_setting", "shutdown",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    user_approved: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class ReaInspectRequest(BaseModel):
    operation: Literal[
        "capabilities",
        "doctor",
        "inspect-desktop-application",
        "analyze-javascript-application",
        "inspect-model-artifact",
        "inspect-gpu-code-objects",
        "inspect-python-pyc",
        "inspect-sqlite-database",
        "inspect-pe-imports",
        "inspect-pe-certificates",
        "inspect-elf-notes",
        "inspect-go-binary",
        "inspect-rust-binary",
        "inspect-wasm-artifact",
    ] = "capabilities"
    target_path: str | None = Field(default=None, max_length=400)
    authorized_target_confirmed: bool = False
    user_approved: bool = False
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")



def _page(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    return {"total": len(items), "limit": safe_limit, "offset": safe_offset, "items": items[safe_offset:safe_offset + safe_limit]}


def _manifest_list(name: str) -> list[dict[str, Any]]:
    try:
        items = load_manifest(name)
    except (ValueError, FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail=f"Catalog manifest unavailable: {name}")
    if not isinstance(items, list):
        raise HTTPException(status_code=500, detail=f"Catalog manifest has invalid structure: {name}")
    return items


def _worker_response(status_code: int, content_type: str, content: bytes) -> Response:
    if "application/json" in content_type:
        try:
            parsed = json.loads(content.decode("utf-8")) if content else {}
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=502, detail="Worker returned invalid JSON")
        return JSONResponse(status_code=status_code, content=parsed)
    safe_type = content_type.split(";")[0].strip()[:100] or "application/octet-stream"
    return Response(content=content, status_code=status_code, media_type=safe_type)


@app.get("/")
def root():
    return {
        "name": "Universal AI Backend",
        "version": "0.6.0",
        "status": "ok",
        "explorer": "/explorer",
        "docs": "/docs",
        "health": "/health",
        "catalog": "/v1/tools",
        "catalog_stats": "/v1/catalog/stats",
        "rea_status": "/v1/rea/status",
        "rea_tools": "/v1/rea/tools",
        "rea_inspect": "/v1/rea/inspect",
        "rea_jobs": "/v1/rea/jobs",
        "base44_integration": "/v1/integrations/base44/status",
        "providers": "/v1/models/providers",
        "workflows": "/v1/workflows",
        "agents": "/v1/agents",
        "channels": "/v1/channels",
        "voice": "/v1/voice/providers",
        "discovery": "/v1/discover/github?q=voice+agent",
        "discovery_categories": "/v1/discover/categories",
        "note": "One repository/control plane. Heavy models, REA artifact inspection, and trusted Windows desktop actions execute on configured workers, not inside Vercel functions.",
    }


@app.get("/explorer", response_class=HTMLResponse)
def explorer():
    return HTMLResponse(content=EXPLORER_HTML)


@app.get("/health")
def health():
    return {"status": "ok", "service": "universal-ai-backend", "version": "0.6.0"}




@app.get("/v1/runtime/capabilities")
def runtime_capabilities():
    services = service_status()
    return {
        "control_plane": "vercel-fastapi",
        "control_plane_ready": True,
        "workers": services,
        "ready_workers": sum(1 for x in services if x["configured"]),
        "total_worker_types": len(services),
        "limitations": [
            "Vercel hosts the API/control plane; GPU inference, long-running jobs and Windows desktop control need configured worker services.",
            "A catalog entry is not an installed/running tool.",
            "Durable schedules, jobs, channel OAuth connections, and user/voice-consent records require persistent storage or a worker service.",
        ],
    }


@app.get("/v1/tools")
def list_tools(
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    capability: str | None = None,
    license_status: str | None = None,
    source_classification: str | None = None,
    min_stars: int | None = Query(default=None, ge=0),
    language: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items = registry.list(q=q, category=category, status=status, kind=kind, capability=capability,
                          license_status=license_status, source_classification=source_classification,
                          min_stars=min_stars, language=language)
    return _page(items, limit, offset)


@app.get("/v1/skills")
def list_skills(
    q: str | None = None, category: str | None = None, capability: str | None = None,
    license_status: str | None = None, source_classification: str | None = None,
    min_stars: int | None = Query(default=None, ge=0), language: str | None = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
):
    items = registry.list(q=q, category=category, capability=capability,
                          license_status=license_status, source_classification=source_classification,
                          min_stars=min_stars, language=language)
    return _page(items, limit, offset)


@app.get("/v1/tools/categories")
def categories():
    return {"categories": registry.categories()}


@app.get("/v1/catalog/stats")
def catalog_stats():
    category_counts: dict[str, int] = {}
    license_counts: dict[str, int] = {}
    classification_counts: dict[str, int] = {}
    for item in registry.items:
        category = str(item.get("category", "uncategorized"))
        license_status = str(item.get("license_status", "not_recorded"))
        classification = str(item.get("source_classification", "not_classified"))
        category_counts[category] = category_counts.get(category, 0) + 1
        license_counts[license_status] = license_counts.get(license_status, 0) + 1
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
    try:
        rea_manifest = load_manifest("rea_mcp_tools.json")
    except (ValueError, FileNotFoundError, json.JSONDecodeError):
        rea_manifest = {}
    manifest_counts = {
        "workflows": len(_manifest_list("workflows.json")),
        "agent_blueprints": len(_manifest_list("agents.json")),
        "channel_manifests": len(_manifest_list("channels.json")),
        "mcp_ecosystem_records": len(_manifest_list("mcp_ecosystem.json")),
        "rea_mcp_tools": len(rea_manifest.get("tools", [])),
        "rea_mcp_prompts": len(rea_manifest.get("prompts", [])),
        "rea_cli_commands": len(rea_manifest.get("cli_commands", [])),
    }
    return {
        "total_tools": len(registry.items),
        "categories": category_counts,
        "license_review_status": license_counts,
        "source_classification": classification_counts,
        "separate_manifests": manifest_counts,
        "note": "Counts are catalog metadata; they are not counts of installed or verified executable integrations.",
    }



@app.get("/v1/catalog/sources")
def catalog_sources():
    try:
        return load_manifest("sources.json")
    except (ValueError, FileNotFoundError, json.JSONDecodeError):
        return {"sources": [], "note": "Source registry is not configured"}


@app.get("/v1/tools/{tool_id}")
def get_tool(tool_id: str):
    item = registry.get(tool_id)
    if not item:
        raise HTTPException(status_code=404, detail="Tool not found")
    return item


@app.post("/v1/tools", dependencies=[Depends(require_api_key)])
def register_tool(item: ToolRegistration):
    """Register metadata only. Does not download, install, or execute repository code."""
    try:
        return registry.add(item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/v1/providers")
def providers():
    return {**provider_status(), "workers": service_status()}


@app.get("/v1/models/providers")
def model_provider_catalog():
    try:
        catalog = load_manifest("provider_capabilities.json")
    except (ValueError, FileNotFoundError, json.JSONDecodeError):
        catalog = []
    status = provider_status()
    states = {item["id"]: item for item in status.get("providers", [])}
    enriched = []
    for item in catalog:
        enriched.append({**item, "runtime_status": states.get(item.get("id"), {"ready": False})})
    return {"total": len(enriched), "items": enriched, "workers": service_status()}


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def chat(request: ChatRequest):
    for index, message in enumerate(request.messages):
        if not isinstance(message, dict) or not message.get("role"):
            raise HTTPException(status_code=422, detail=f"messages[{index}] must contain a role")
    try:
        provider_id = request.provider.lower().replace("_", "-")
        return await chat_with_provider(provider=provider_id, model=request.model, messages=request.messages,
                                        temperature=request.temperature, max_tokens=request.max_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI provider request failed: {type(exc).__name__}")


@app.get("/v1/workers/status")
def workers_status():
    return {"workers": service_status()}


@app.get("/v1/workflows")
def list_workflows(q: str | None = None, category: str | None = None):
    items = _manifest_list("workflows.json")
    if q:
        needle = q.casefold()
        items = [x for x in items if needle in json.dumps(x, ensure_ascii=False).casefold()]
    if category:
        items = [x for x in items if x.get("category", "").casefold() == category.casefold()]
    return {"total": len(items), "items": items}


@app.post("/v1/workflows/{workflow_id}/run", dependencies=[Depends(require_api_key)])
async def run_workflow(workflow_id: str, request: WorkflowRunRequest):
    workflow = next((x for x in _manifest_list("workflows.json") if x.get("id") == workflow_id), None)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    if workflow.get("requires_human_approval") and not request.user_approved:
        raise HTTPException(status_code=409, detail="This workflow has external or consequential actions. Review the plan and retry with user_approved=true.")
    task_id = request.idempotency_key or str(uuid4())
    payload = {
        "task_id": task_id, "workflow_id": workflow_id, "workflow": workflow,
        "inputs": request.inputs, "user_approved": request.user_approved, "dry_run": request.dry_run,
        "requested_at": "server-generated", "execution_mode": "async",
    }
    status_code, content_type, body = await post_worker("automation", "/v1/workflows/run", payload, timeout_seconds=25)
    result = _worker_response(status_code, content_type, body)
    return result


@app.get("/v1/agents")
def list_agents(q: str | None = None, risk_level: str | None = None):
    items = _manifest_list("agents.json")
    if q:
        needle = q.casefold()
        items = [x for x in items if needle in json.dumps(x, ensure_ascii=False).casefold()]
    if risk_level:
        items = [x for x in items if x.get("risk_level", "").casefold() == risk_level.casefold()]
    return {"total": len(items), "items": items}


@app.post("/v1/agents/{agent_id}/run", dependencies=[Depends(require_api_key)])
async def run_agent(agent_id: str, request: AgentRunRequest):
    agent = next((x for x in _manifest_list("agents.json") if x.get("id") == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent blueprint not found")
    if agent.get("risk_level") == "critical" and not request.user_approved:
        raise HTTPException(status_code=409, detail="Critical-risk agent action requires explicit user_approved=true.")
    payload = {
        "task_id": request.idempotency_key or str(uuid4()), "agent_id": agent_id, "agent": agent,
        "objective": request.objective, "inputs": request.inputs, "user_approved": request.user_approved,
        "dry_run": request.dry_run, "execution_mode": "async",
    }
    status_code, content_type, body = await post_worker("agents", "/v1/agents/run", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.get("/v1/voice/providers")
def voice_providers():
    items = _manifest_list("voice_media.json")
    items = [x for x in items if any(word in x.get("category", "") for word in ("voice", "speech", "audio", "speaker"))]
    worker = next((x for x in service_status() if x["id"] == "voice"), None)
    return {
        "total": len(items),
        "worker": worker,
        "items": items,
        "note": "Engine catalog metadata does not imply the model weights are installed. F5-TTS pretrained weights in the upstream README are CC-BY-NC; commercial deployments need a separately approved compatible model/license.",
    }


@app.post("/v1/voice/assets", status_code=201, dependencies=[Depends(require_api_key)])
async def upload_voice_reference(request: VoiceAssetUploadRequest):
    if not request.speaker_consent_confirmed:
        raise HTTPException(status_code=400, detail="Voice-reference uploads require explicit speaker authorization.")
    payload = request.model_dump()
    status_code, content_type, body = await post_worker("voice", "/v1/voice/assets", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/voice/tts", dependencies=[Depends(require_api_key)])
async def synthesize_voice(request: VoiceTTSRequest):
    engine = request.engine.lower()
    valid_engines = {"f5-tts", "openvoice", "gpt-sovits", "cosyvoice", "fish-speech", "xtts-v2",
                     "melo-tts", "kokoro", "styletts2", "piper", "chatterbox", "orpheus-tts",
                     "zonos", "spark-tts", "dia", "elevenlabs", "cartesia", "deepgram", "azure"}
    if engine not in valid_engines:
        raise HTTPException(status_code=400, detail="Unsupported voice engine. Query /v1/voice/providers for the catalog.")
    if (request.reference_audio_asset_id or request.voice_profile_id) and not (
        request.speaker_consent_confirmed and request.speaker_consent_record_id
    ):
        raise HTTPException(status_code=400, detail="Using a cloned/reference voice requires speaker_consent_confirmed and a speaker_consent_record_id.")
    if engine == "f5-tts" and request.commercial_use and os.getenv("F5_TTS_MODEL_LICENSE_CLASS", "").lower() != "commercial_approved":
        raise HTTPException(status_code=403, detail="F5-TTS's standard pretrained weights are not a commercial default. Set F5_TTS_MODEL_LICENSE_CLASS=commercial_approved only after supplying a model/checkpoint with compatible commercial rights.")
    payload = {**request.model_dump(), "task_id": request.idempotency_key or str(uuid4()), "execution_mode": "async"}
    status_code, content_type, body = await post_worker("voice", "/v1/voice/tts", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.get("/v1/voice/results/{task_id}", dependencies=[Depends(require_api_key)])
async def get_voice_result(task_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    status_code, content_type, body = await get_worker("voice", f"/v1/voice/results/{task_id}", timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/voice/clone", dependencies=[Depends(require_api_key)])
async def create_voice_clone(request: VoiceCloneRequest):
    if not request.speaker_consent_confirmed or not request.speaker_consent_record_id:
        raise HTTPException(status_code=400, detail="Voice cloning requires recorded speaker authorization and a consent record ID.")
    if request.engine.lower() == "f5-tts" and request.commercial_use and os.getenv("F5_TTS_MODEL_LICENSE_CLASS", "").lower() != "commercial_approved":
        raise HTTPException(status_code=403, detail="F5-TTS's standard pretrained weights are not a commercial default; configure a compatible licensed checkpoint first.")
    payload = {**request.model_dump(), "task_id": request.idempotency_key or str(uuid4()), "execution_mode": "async"}
    status_code, content_type, body = await post_worker("voice", "/v1/voice/clone", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/media/jobs", dependencies=[Depends(require_api_key)])
async def create_media_job(request: MediaJobRequest):
    payload = {**request.model_dump(), "task_id": request.idempotency_key or str(uuid4()), "execution_mode": "async"}
    status_code, content_type, body = await post_worker("media", "/v1/media/jobs", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.get("/v1/channels")
def list_channels(q: str | None = None):
    channels = _manifest_list("channels.json")
    if q:
        needle = q.casefold()
        channels = [x for x in channels if needle in json.dumps(x, ensure_ascii=False).casefold()]
    result = []
    for channel in channels:
        required = channel.get("environment_variables", [])
        configured_count = sum(1 for name in required if os.getenv(str(name), "").strip())
        result.append({**channel, "configured_env_count": configured_count,
                       "configured_env_total": len(required),
                       "environment_configured": bool(required) and configured_count == len(required)})
    return {"total": len(result), "items": result,
            "note": "OAuth connection state should live in a persistent encrypted connection store; env checks alone do not prove a channel account is connected."}


@app.post("/v1/channels/{channel_id}/actions", dependencies=[Depends(require_api_key)])
async def channel_action(channel_id: str, request: ChannelActionRequest):
    manifest = next((x for x in _manifest_list("channels.json") if x.get("id") == channel_id), None)
    if not manifest:
        raise HTTPException(status_code=404, detail="Channel connector is not in the registry")
    supported = set(manifest.get("supported_actions", []))
    if request.action not in supported:
        raise HTTPException(status_code=400, detail="Action is not declared as supported for this channel connector")
    if request.action in {"send_message", "send_template_message", "channel_post", "publish_post",
                          "publish_media", "upload_video", "publish_video", "create_status"} and not request.user_approved:
        raise HTTPException(status_code=409, detail="External messages and public posts require explicit user_approved=true")
    payload = {**request.model_dump(), "channel_id": channel_id,
               "task_id": request.idempotency_key or str(uuid4()), "execution_mode": "async"}
    status_code, content_type, body = await post_worker("channels", "/v1/channels/action", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/youtube/publish", dependencies=[Depends(require_api_key)])
async def publish_youtube_video(request: YouTubePublishRequest):
    if not request.user_approved:
        raise HTTPException(status_code=409, detail="YouTube upload/scheduling requires explicit user_approved=true.")
    payload = {**request.model_dump(), "task_id": request.idempotency_key or str(uuid4()), "execution_mode": "async"}
    status_code, content_type, body = await post_worker("youtube", "/v1/youtube/publish", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/desktop/actions", dependencies=[Depends(require_api_key)])
async def desktop_action(request: DesktopActionRequest):
    high_impact = {"write_file", "delete_file", "install_software", "run_approved_script",
                   "send_message", "change_system_setting", "shutdown"}
    if request.action in high_impact and not request.user_approved:
        raise HTTPException(status_code=409, detail="This desktop action requires explicit user_approved=true.")
    payload = {**request.model_dump(), "task_id": request.idempotency_key or str(uuid4()), "execution_mode": "async"}
    status_code, content_type, body = await post_worker("desktop", "/v1/desktop/actions", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/rea/jobs", status_code=202, dependencies=[Depends(require_api_key)])
async def create_rea_job(request: ReaToolCallRequest):
    if not request.user_approved:
        raise HTTPException(status_code=409, detail="Each REA MCP tool call requires explicit user_approved=true.")
    if not request.authorization_scope_confirmed or not request.authorization_scope_note.strip():
        raise HTTPException(status_code=400, detail="Confirm authorization for the target and describe the scope before running REA.")
    payload = request.model_dump()
    status_code, content_type, body = await post_worker("desktop", "/v1/rea/jobs", payload, timeout_seconds=25)
    if "application/json" not in content_type:
        raise HTTPException(status_code=502, detail="REA worker returned a non-JSON job response")
    try:
        result = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=502, detail="REA worker returned invalid JSON")
    if isinstance(result, dict) and result.get("task_id"):
        result["poll_url"] = f"/v1/tasks/desktop-rea/{result['task_id']}"
    return JSONResponse(status_code=status_code, content=result)


@app.get("/v1/integrations/base44/status")
def get_base44_integration_status():
    return base44_status()


@app.get("/v1/integrations/base44/sdk")
def get_base44_integration_sdk():
    return {
        "backend_function_name": "universalAiBackend",
        "backend_function_entry": build_base44_backend_function_code(),
        "frontend_sdk_path": "src/lib/universalAiBackend.js",
        "frontend_sdk_code": build_base44_frontend_sdk_code(),
        "hub_page_path": "src/pages/UniversalAiHub.jsx",
        "hub_page_code": build_base44_hub_page_code(),
    }


@app.get("/v1/integrations/base44/apps", dependencies=[Depends(require_api_key)])
async def list_base44_apps():
    client = Base44Client()
    apps = await client.list_apps(limit=50)
    return {"total": len(apps), "items": apps}


@app.post("/v1/integrations/base44/connect", dependencies=[Depends(require_api_key)])
async def connect_base44_endpoint(request: Base44ConnectRequest):
    return await connect_base44_app(
        request.app_id,
        backend_url=request.backend_url,
        install_frontend_files=request.install_frontend_files,
    )


@app.get("/v1/tasks/{service}/{task_id}", dependencies=[Depends(require_api_key)])
async def task_status(service: str, task_id: str):
    service_alias = {
        "voice": "voice", "media": "media", "automation": "automation",
        "agents": "agents", "desktop": "desktop", "desktop-rea": "desktop",
        "youtube": "youtube", "channels": "channels", "rea": "rea",
    }
    if service not in service_alias:
        raise HTTPException(status_code=404, detail="Unknown task service")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,180}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task identifier")
    worker_path = f"/v1/rea/tasks/{task_id}" if service == "desktop-rea" else f"/v1/tasks/{task_id}"
    status_code, content_type, body = await get_worker(service_alias[service], worker_path, timeout_seconds=15)
    return _worker_response(status_code, content_type, body)


@app.post("/v1/rea/inspect", dependencies=[Depends(require_api_key)])
async def inspect_with_rea(request: ReaInspectRequest):
    if not request.authorized_target_confirmed:
        raise HTTPException(
            status_code=400,
            detail="REA inspection requires authorized_target_confirmed=true confirming ownership or legal authorization to inspect the target.",
        )
    if not request.user_approved:
        raise HTTPException(status_code=409, detail="REA worker inspection requires explicit user_approved=true.")
    if request.operation not in {"capabilities", "doctor"} and not request.target_path:
        raise HTTPException(status_code=400, detail=f"target_path is required for REA operation {request.operation}")
    payload = {
        "task_id": request.idempotency_key or str(uuid4()),
        "operation": request.operation,
        "target_path": request.target_path,
        "authorized_target_confirmed": request.authorized_target_confirmed,
        "user_approved": request.user_approved,
        "dry_run": request.dry_run,
    }
    status_code, content_type, body = await post_worker("rea", "/v1/rea/inspect", payload, timeout_seconds=25)
    return _worker_response(status_code, content_type, body)



@app.get("/v1/rea/status")
def rea_status():
    try:
        manifest = load_manifest("rea_mcp_tools.json")
    except (ValueError, FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="REA MCP manifest unavailable")
    ai_highlights = [t for t in manifest.get("tools", []) if t.get("ai_workflow_highlight")]
    return {
        "id": manifest.get("id"),
        "name": manifest.get("name"),
        "package_name": manifest.get("package_name"),
        "mcp_registry_name": manifest.get("mcp_registry_name"),
        "version": manifest.get("version"),
        "repository_url": manifest.get("repository_url"),
        "website_url": manifest.get("website_url"),
        "license": manifest.get("license"),
        "setup_commands": manifest.get("setup_commands", {}),
        "counts": manifest.get("counts", {}),
        "family_counts": manifest.get("family_counts", {}),
        "ai_workflow_highlights": ai_highlights,
        "prompts": manifest.get("prompts", []),
        "discovery_evidence_runs": manifest.get("discovery_evidence_runs", []),
        "responsible_use_policy": manifest.get("responsible_use_policy"),
    }


@app.get("/v1/rea/tools")
def list_rea_tools(
    q: str | None = None,
    family: str | None = None,
    ai_only: bool = False,
    read_only: bool | None = None,
    destructive: bool | None = None,
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    try:
        manifest = load_manifest("rea_mcp_tools.json")
    except (ValueError, FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="REA MCP manifest unavailable")
    tools = list(manifest.get("tools", []))
    if q:
        needle = q.casefold()
        tools = [t for t in tools if needle in json.dumps(t, ensure_ascii=False).casefold()]
    if family:
        wanted_fam = family.casefold()
        tools = [t for t in tools if str(t.get("family", "")).casefold() == wanted_fam]
    if ai_only:
        tools = [t for t in tools if bool(t.get("ai_workflow_highlight"))]
    if read_only is not None:
        tools = [t for t in tools if bool(t.get("read_only")) is read_only]
    if destructive is not None:
        tools = [t for t in tools if bool(t.get("destructive")) is destructive]
    return {
        **_page(tools, limit, offset),
        "rea_version": manifest.get("version"),
        "families": manifest.get("family_counts", {}),
    }


@app.get("/v1/discover/categories")
def discover_categories():
    category_counts: dict[str, int] = {}
    for item in registry.items:
        cat = str(item.get("category", "uncategorized"))
        category_counts[cat] = category_counts.get(cat, 0) + 1
    presets = []
    for preset in list_discovery_presets():
        presets.append({
            **preset,
            "catalog_count": category_counts.get(preset["id"], 0),
            "discover_url": f"/v1/discover/github?category_preset={preset['id']}",
        })
    return {
        "total_presets": len(presets),
        "total_catalog_categories": len(category_counts),
        "presets": presets,
        "catalog_category_counts": dict(sorted(category_counts.items())),
    }


@app.get("/v1/discover/github")
async def discover_github(
    q: str = Query(default="", max_length=180, description="Capability/tool query, e.g. browser automation"),
    category_preset: str | None = Query(default=None, max_length=60, description="Optional built-in AI category preset from /v1/discover/categories"),
    per_page: int = Query(default=10, ge=1, le=30),
    page: int = Query(default=1, ge=1, le=10),
    license_filter: str | None = Query(default=None, pattern=r"^[A-Za-z0-9.+-]{1,40}$"),
    min_stars: int = Query(default=0, ge=0, le=100000000),
    sort: str = Query(default="stars", pattern=r"^(stars|forks|updated|help-wanted-issues)$"),
    order: str = Query(default="desc", pattern=r"^(asc|desc)$"),
):
    try:
        return await search_github_repositories(
            q=q, per_page=per_page, page=page, license_filter=license_filter,
            min_stars=min_stars, sort=sort, order=order, category_preset=category_preset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub discovery failed: {type(exc).__name__}")

