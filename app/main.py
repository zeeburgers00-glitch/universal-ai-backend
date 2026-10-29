import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .github_discovery import search_github_repositories
from .providers import chat_with_openai_compatible, provider_status
from .registry import Registry
from .security import require_api_key

registry = Registry.from_file()


app = FastAPI(
    title="Universal AI Backend",
    description="API-only AI provider gateway, skill catalog, and live GitHub tool discovery.",
    version="0.2.0",
)

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


class ChatRequest(BaseModel):
    provider: str = Field(default="openai_compatible", min_length=1, max_length=80)
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


@app.get("/")
def root():
    return {
        "name": "Universal AI Backend",
        "version": "0.2.0",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "catalog": "/v1/tools",
        "discovery": "/v1/discover/github?q=voice+agent",
        "note": "API only; no frontend. Catalog entries are not automatically installed or executed.",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "universal-ai-backend", "version": "0.2.0"}


def _page(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    return {
        "total": len(items),
        "limit": safe_limit,
        "offset": safe_offset,
        "items": items[safe_offset:safe_offset + safe_limit],
    }


@app.get("/v1/tools")
def list_tools(
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    capability: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items = registry.list(q=q, category=category, status=status, kind=kind, capability=capability)
    return _page(items, limit, offset)


@app.get("/v1/skills")
def list_skills(
    q: str | None = None,
    category: str | None = None,
    capability: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Skills are catalog entries with capability metadata; discovery does not execute code."""
    items = registry.list(q=q, category=category, capability=capability)
    return _page(items, limit, offset)


@app.get("/v1/tools/categories")
def categories():
    return {"categories": registry.categories()}


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
    return provider_status()


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def chat(request: ChatRequest):
    if request.provider != "openai_compatible":
        raise HTTPException(
            status_code=400,
            detail="This release implements provider='openai_compatible'. Configure AI_BASE_URL and AI_API_KEY for your chosen compatible provider.",
        )
    for index, message in enumerate(request.messages):
        if not isinstance(message, dict) or not message.get("role"):
            raise HTTPException(status_code=422, detail=f"messages[{index}] must contain a role")
    try:
        return await chat_with_openai_compatible(
            model=request.model,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # Keep credentials, provider response bodies, and server stack traces private.
        raise HTTPException(status_code=502, detail=f"AI provider request failed: {type(exc).__name__}")


@app.get("/v1/discover/github")
async def discover_github(
    q: str = Query(min_length=2, max_length=180, description="Capability/tool query, e.g. browser automation"),
    per_page: int = Query(default=10, ge=1, le=30),
):
    try:
        return await search_github_repositories(q=q, per_page=per_page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub discovery failed: {type(exc).__name__}")
