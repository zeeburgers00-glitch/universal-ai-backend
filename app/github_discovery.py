from __future__ import annotations

import os
import re
from typing import Any

import httpx


LICENSE_FILTER_RE = re.compile(r"^[A-Za-z0-9.+-]{1,40}$")
SORT_OPTIONS = {"stars", "forks", "updated", "help-wanted-issues"}

AI_DISCOVERY_CATEGORIES: dict[str, dict[str, Any]] = {
    "mcp-servers": {
        "label": "MCP Servers & Protocol Tooling",
        "github_query": "mcp-server OR model-context-protocol",
        "default_min_stars": 50,
    },
    "ai-agents": {
        "label": "Autonomous & Multi-Agent Systems",
        "github_query": "ai-agents OR multi-agent OR autonomous-agent",
        "default_min_stars": 150,
    },
    "coding-agents": {
        "label": "AI Coding Assistants & App Builders",
        "github_query": "coding-agent OR ai-coding OR code-assistant",
        "default_min_stars": 150,
    },
    "reverse-engineering-ai": {
        "label": "Reverse Engineering & Binary Analysis MCP/AI Tools",
        "github_query": "reverse-engineering mcp OR ghidra mcp OR binary-analysis ai",
        "default_min_stars": 20,
    },
    "llm-runtime": {
        "label": "LLM Inference Engines & Local Runtimes",
        "github_query": "vllm OR ollama OR llama-cpp OR llm-inference OR model-serving",
        "default_min_stars": 150,
    },
    "rag-knowledge": {
        "label": "RAG, GraphRAG & Knowledge Retrieval",
        "github_query": "retrieval-augmented-generation OR rag-pipeline OR graphrag",
        "default_min_stars": 150,
    },
    "vector-databases": {
        "label": "Vector Databases & Semantic Search",
        "github_query": "vector-database OR vector-search OR semantic-search",
        "default_min_stars": 150,
    },
    "browser-computer-use": {
        "label": "Browser Agents & Computer-Use Automation",
        "github_query": "browser-use OR browser-agent OR computer-use OR web-agent",
        "default_min_stars": 100,
    },
    "audio-voice": {
        "label": "Voice Cloning, TTS, STT & Voice Agents",
        "github_query": "text-to-speech OR voice-cloning OR speech-to-text OR voice-agent",
        "default_min_stars": 150,
    },
    "image-generation": {
        "label": "Image Generation, Diffusion & Visual Design",
        "github_query": "stable-diffusion OR comfyui OR text-to-image OR image-generation",
        "default_min_stars": 200,
    },
    "video-generation": {
        "label": "Video Generation, Lip-Sync & Avatars",
        "github_query": "video-generation OR text-to-video OR talking-head OR lip-sync",
        "default_min_stars": 150,
    },
    "music-audio-ai": {
        "label": "Music & Audio Synthesis AI",
        "github_query": "music-generation OR audio-generation OR singing-voice",
        "default_min_stars": 100,
    },
    "fine-tuning-training": {
        "label": "LLM Fine-Tuning, RLHF & Post-Training",
        "github_query": "fine-tuning OR qlora OR rlhf OR llm-training",
        "default_min_stars": 200,
    },
    "llmops-evals": {
        "label": "LLMOps, Tracing, Gateways & Evaluations",
        "github_query": "llmops OR llm-evaluation OR llm-observability",
        "default_min_stars": 100,
    },
    "ai-safety-security": {
        "label": "AI Guardrails, Red-Teaming & Prompt Security",
        "github_query": "ai-security OR llm-security OR prompt-injection OR guardrails",
        "default_min_stars": 80,
    },
    "chat-ui-workspaces": {
        "label": "AI Chat Interfaces & Workspaces",
        "github_query": "chatgpt-ui OR llm-ui OR open-webui OR ai-chat",
        "default_min_stars": 200,
    },
    "workflow-automation": {
        "label": "AI Workflow Builders & Orchestration",
        "github_query": "ai-workflow OR no-code-ai OR llm-workflow",
        "default_min_stars": 100,
    },
    "ai-search-research": {
        "label": "Deep Research & AI Web Search Engines",
        "github_query": "deep-research OR ai-search OR research-agent",
        "default_min_stars": 100,
    },
    "computer-vision": {
        "label": "Computer Vision, Detection & Segmentation",
        "github_query": "object-detection OR image-segmentation OR vision-transformer",
        "default_min_stars": 300,
    },
    "robotics-embodied-ai": {
        "label": "Robotics, Embodied AI & VLA Models",
        "github_query": "robotics-ai OR embodied-ai OR lerobot OR vision-language-action",
        "default_min_stars": 100,
    },
    "3d-world-models": {
        "label": "3D Generation, Gaussian Splatting & World Models",
        "github_query": "text-to-3d OR 3d-generation OR gaussian-splatting",
        "default_min_stars": 150,
    },
    "document-ai-ocr": {
        "label": "Document Parsing, PDF Extraction & OCR",
        "github_query": "pdf-to-markdown OR document-ai OR document-parsing",
        "default_min_stars": 150,
    },
    "data-analytics-ai": {
        "label": "Text-to-SQL & AI Data Analytics",
        "github_query": "text-to-sql OR data-agent OR pandas-ai",
        "default_min_stars": 100,
    },
    "scientific-medical-ai": {
        "label": "Biomedical, Protein & Scientific AI",
        "github_query": "protein-folding OR biomedical-ai OR medical-llm",
        "default_min_stars": 100,
    },
    "multimodal-models": {
        "label": "Vision-Language & Multimodal Foundation Models",
        "github_query": "vision-language-model OR multimodal-llm",
        "default_min_stars": 200,
    },
    "local-edge-ai": {
        "label": "Mobile, WebGPU & On-Device Edge AI",
        "github_query": "mlx OR coreml OR executorch OR onnxruntime OR webllm",
        "default_min_stars": 150,
    },
    "education-learning-ai": {
        "label": "Education, Tutoring & Theorem-Proving AI",
        "github_query": "ai-tutor OR education-ai OR theorem-proving",
        "default_min_stars": 80,
    },
    "legal-compliance-ai": {
        "label": "LegalTech, Contract Review & Compliance AI",
        "github_query": "legal-ai OR contract-analysis OR law-llm",
        "default_min_stars": 50,
    },
    "finance-fintech-ai": {
        "label": "Finance, Quant & Fintech AI",
        "github_query": "financial-llm OR finrobot OR quant-ai",
        "default_min_stars": 100,
    },
    "gaming-interactive-ai": {
        "label": "Gaming, NPC Agents & Engine AI",
        "github_query": "npc-ai OR unity-ai OR godot-ai",
        "default_min_stars": 100,
    },
}


def list_discovery_presets() -> list[dict[str, Any]]:
    return [
        {"id": key, **meta}
        for key, meta in sorted(AI_DISCOVERY_CATEGORIES.items())
    ]


async def search_github_repositories(
    q: str = "",
    per_page: int = 10,
    license_filter: str | None = None,
    min_stars: int = 0,
    sort: str = "stars",
    order: str = "desc",
    page: int = 1,
    category_preset: str | None = None,
) -> dict[str, Any]:
    """Search public GitHub repositories live; results are candidates, not verified plugins."""
    preset_meta = None
    if category_preset:
        preset_meta = AI_DISCOVERY_CATEGORIES.get(category_preset.strip().lower())
        if not preset_meta:
            raise ValueError(f"Unknown category_preset: {category_preset}")

    query = q.strip()
    if preset_meta:
        query = f"{query} {preset_meta['github_query']}".strip() if query else str(preset_meta["github_query"])
        if min_stars == 0:
            min_stars = int(preset_meta.get("default_min_stars", 0))

    if len(query) < 2:
        raise ValueError("q must contain at least 2 characters (or supply a valid category_preset)")
    if len(query) > 180:
        raise ValueError("q is too long")
    if license_filter and not LICENSE_FILTER_RE.fullmatch(license_filter):
        raise ValueError("license_filter may contain only letters, numbers, dot, plus, and hyphen")
    if sort not in SORT_OPTIONS:
        raise ValueError(f"sort must be one of: {', '.join(sorted(SORT_OPTIONS))}")
    if order not in {"asc", "desc"}:
        raise ValueError("order must be asc or desc")
    if min_stars < 0:
        raise ValueError("min_stars cannot be negative")
    if page < 1 or page > 10:
        raise ValueError("page must be between 1 and 10")

    count = max(1, min(per_page, 30))
    github_query = query if (" OR " in query or ":" in query) else f"{query} in:name,description,topics"
    if license_filter:
        github_query += f" license:{license_filter.lower()}"
    if min_stars:
        github_query += f" stars:>={min_stars}"

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Universal-AI-Backend",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {"q": github_query, "sort": sort, "order": order, "per_page": count, "page": page}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False) as client:
        response = await client.get("https://api.github.com/search/repositories", params=params, headers=headers)
        if response.status_code == 403:
            raise RuntimeError("GitHub API rate limit or permission limit reached; configure GITHUB_TOKEN")
        response.raise_for_status()
        payload = response.json()

    items = []
    for repo in payload.get("items", []):
        license_data = repo.get("license") or {}
        license_name = license_data.get("spdx_id") or "UNKNOWN — check upstream LICENSE"
        items.append({
            "id": str(repo.get("full_name", "")).lower().replace("/", "--"),
            "name": repo.get("name"),
            "full_name": repo.get("full_name"),
            "category": category_preset.lower() if category_preset else "discovered",
            "description": repo.get("description"),
            "repository_url": repo.get("html_url"),
            "default_branch": repo.get("default_branch"),
            "language": repo.get("language"),
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "topics": repo.get("topics", []),
            "license": license_name,
            "license_status": "github_metadata_only_requires_manual_review",
            "archived": repo.get("archived", False),
            "updated_at": repo.get("updated_at"),
            "status": "discovered_unreviewed",
            "warning": "GitHub discovery only. A reported SPDX license is not a legal review; inspect current LICENSE, dependencies, model/data terms, security, and hosted-service boundaries before integration.",
        })
    return {
        "query": query,
        "category_preset": category_preset.lower() if category_preset else None,
        "github_query": github_query,
        "total_count": payload.get("total_count", 0),
        "returned": len(items),
        "page": page,
        "per_page": count,
        "items": items,
        "source": "GitHub Search API",
        "warning": "Discovery results are metadata only. The backend does not download, install, or execute these repositories.",
    }
