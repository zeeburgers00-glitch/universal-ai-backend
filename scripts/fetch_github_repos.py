"""Build catalog/github_repos.json from live GitHub API data.

Every number in the output (stars, license, language, last push) comes from the
GitHub API at build time. Nothing is hand-typed, so the catalog cannot drift into
invented popularity numbers.

Usage:
    python scripts/fetch_github_repos.py            # writes catalog/github_repos.json
    python scripts/fetch_github_repos.py --dry-run  # print only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from urllib.parse import quote_plus
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "catalog" / "github_repos.json"

# Repos the owner asked to track explicitly.
PINNED = (
    ("CopilotKit/OpenDots", "agents"),
    ("cedroid/groq-bot", "rag-bots"),
)

# category -> (search query, max results)
SEARCHES: dict[str, tuple[str, int]] = {
    "agents": ("ai agent framework stars:>1000", 22),
    "agent-ui": ("llm chat ui stars:>1000", 12),
    "mcp": ("mcp server stars:>300", 22),
    "rag-bots": ("rag chatbot stars:>300", 16),
    "whatsapp": ("whatsapp bot stars:>200", 12),
    "voice": ("realtime voice agent stars:>300", 14),
    "tts": ("text to speech stars:>800", 10),
    "video": ("video generation stars:>800", 16),
    "youtube": ("youtube automation upload stars:>150", 10),
    "workflow": ("workflow automation stars:>2000", 10),
    "inference": ("llm inference server stars:>1500", 12),
    "observability": ("llm observability tracing stars:>300", 10),
    "image-gen": ("image generation stars:>3000", 14),
    "comfyui": ("comfyui stars:>300", 12),
    "transcribe": ("whisper speech recognition stars:>1000", 12),
    "embeddings": ("vector search embeddings rag stars:>1000", 12),
    "scraping": ("web scraping crawler stars:>4000", 8),
    "coding-agents": ("coding agent cli stars:>1000", 10),
    "eval": ("llm evaluation framework stars:>500", 8),
}

# Which of our pieces a category maps onto. Reference only -- these repos are
# not vendored and their code does not run inside this backend.
CATEGORY_MAP = {
    "agents": ("agent_worker", "patterns to borrow: planner/executor split, human-in-the-loop approvals"),
    "agent-ui": ("studio / frontend", "chat UI + tool-renderer ideas for the studio console"),
    "mcp": ("rea_worker / tools catalog", "MCP servers become entries in the 229-tool REA surface"),
    "rag-bots": ("automation_worker", "retrieval + auto-reply pipelines"),
    "whatsapp": ("channel_worker", "channel connectors (manifest_only today)"),
    "voice": ("voice_worker", "realtime speech patterns on top of the TTS worker"),
    "tts": ("voice_worker", "voice engines/providers"),
    "video": ("media_worker / videoengine", "render pipelines, ffmpeg recipes"),
    "youtube": ("youtube_worker", "publish scheduling + metadata"),
    "workflow": ("automation_worker", "workflow graph execution"),
    "inference": ("deploy/modal + ai_router", "self-hosted model serving"),
    "observability": ("control plane", "tracing/cost telemetry"),
    "image-gen": ("media_worker", "image generation backends (ComfyUI-adjacent)"),
    "transcribe": ("media_worker / voice_worker", "speech-to-text engines"),
    "embeddings": ("vault / rea_worker", "vector stores for retrieval"),
    "scraping": ("rea_worker", "browser/research tools"),
    "coding-agents": ("agent_worker", "autonomous coding loops"),
    "eval": ("tests / control plane", "quality gates for generated output"),
    "comfyui": ("media_worker", "COMFYUI_BASE_URL generation graphs + node packs"),
}


def gh_json(args: list[str]) -> dict:
    """Run `gh api` without inheriting stdin (an open stdin makes gh hang)."""
    out = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=True,
    )
    return json.loads(out.stdout) if out.stdout.strip() else {}


def repo_meta(full_name: str) -> dict | None:
    try:
        repo = gh_json(["api", f"repos/{full_name}"])
    except subprocess.CalledProcessError:
        return None
    return {
        "full_name": repo["full_name"],
        "url": repo["html_url"],
        "description": (repo.get("description") or "").strip(),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "language": repo.get("language"),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "archived": bool(repo.get("archived")),
        "pushed_at": repo.get("pushed_at"),
        "topics": repo.get("topics") or [],
    }


def search(query: str, limit: int) -> list[dict]:
    """Search with retry: GitHub allows only 30 search calls per minute."""

    encoded = quote_plus(query)
    for attempt in range(3):
        try:
            data = gh_json(["api", f"search/repositories?q={encoded}&sort=stars&per_page={limit}"])
            return data.get("items", [])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
            print(f"  ! search failed ({attempt + 1}/3): {query}")
            time.sleep(10 * (attempt + 1))
    return []


def main(dry_run: bool = False) -> None:
    entries: dict[str, dict] = {}

    def add(meta: dict, category: str) -> None:
        existing = entries.get(meta["full_name"])
        if existing:
            if category not in existing["categories"]:
                existing["categories"].append(category)
            return
        if meta.get("archived"):
            return
        entries[meta["full_name"]] = {**meta, "categories": [category]}

    print("pinned repos")
    for full_name, category in PINNED:
        meta = repo_meta(full_name)
        if meta:
            add(meta, category)
            print(f"  + {full_name} ({meta['stars']} stars)")
        else:
            print(f"  ! missing: {full_name}")

    for category, (query, limit) in SEARCHES.items():
        print(f"search: {category}")
        time.sleep(2.2)  # stay under the 30-requests/minute search quota
        for item in search(query, limit):
            add(
                {
                    "full_name": item["full_name"],
                    "url": item["html_url"],
                    "description": (item.get("description") or "").strip(),
                    "stars": item.get("stargazers_count", 0),
                    "forks": item.get("forks_count", 0),
                    "language": item.get("language"),
                    "license": (item.get("license") or {}).get("spdx_id"),
                    "archived": bool(item.get("archived")),
                    "pushed_at": item.get("pushed_at"),
                    "topics": item.get("topics") or [],
                },
                category,
            )

    repos = sorted(entries.values(), key=lambda r: (-r["stars"], r["full_name"]))
    for repo in repos:
        target, note = next(
            (CATEGORY_MAP[c] for c in repo["categories"] if c in CATEGORY_MAP),
            ("catalog", "reference"),
        )
        repo["maps_to"] = target
        repo["integration"] = "reference-only"
        repo["note"] = note

    payload = {
        "generated_by": "scripts/fetch_github_repos.py",
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "GitHub REST API (search + repos endpoints)",
        "disclaimer": (
            "Stars/licence/language are a snapshot from the API. These repositories are "
            "NOT vendored or executed by this backend; they are a vetted reading/integration "
            "shortlist. 'integration' is 'reference-only' until code is actually wired in."
        ),
        "total": len(repos),
        "by_category": {
            category: [r["full_name"] for r in repos if category in r["categories"]]
            for category, _ in SEARCHES.items()
        },
        "repos": repos,
    }

    if dry_run:
        print(json.dumps(payload["by_category"], indent=2))
        print(f"total: {len(repos)}")
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(repos)} repos")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
