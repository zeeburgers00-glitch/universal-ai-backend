"""Scheduled GitHub AI-tool discovery; emits metadata-only candidates, never executes repo code."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

SEARCHES = {
    "ai-agents": "AI agent framework OR agent orchestration language:Python",
    "video-generation": "open source AI video generation model",
    "voice-audio": "open source text to speech voice cloning",
    "speech-captions": "Whisper speech recognition subtitles",
    "mcp-servers": "MCP server AI tools",
    "browser-computer-use": "browser computer use agent",
    "workflow-automation": "AI workflow automation framework",
    "youtube-creator": "YouTube automation video editing open source",
}


def main() -> None:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    candidates = {}
    with httpx.Client(timeout=httpx.Timeout(25.0, connect=8.0), headers=headers) as client:
        for category, query in SEARCHES.items():
            response = client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "updated", "order": "desc", "per_page": 12},
            )
            response.raise_for_status()
            for repo in response.json().get("items", []):
                full_name = repo.get("full_name")
                if not full_name:
                    continue
                license_info = repo.get("license") or {}
                candidates[full_name.lower()] = {
                    "id": full_name.lower().replace("/", "--"),
                    "name": repo.get("name"),
                    "full_name": full_name,
                    "description": repo.get("description"),
                    "repository_url": repo.get("html_url"),
                    "category": category,
                    "stars_snapshot": repo.get("stargazers_count", 0),
                    "forks_snapshot": repo.get("forks_count", 0),
                    "primary_language": repo.get("language"),
                    "license_spdx": license_info.get("spdx_id"),
                    "pushed_at": repo.get("pushed_at"),
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "status": "candidate_review",
                    "execution_status": "not_installed",
                    "security_review_required": True,
                }
    ordered = sorted(candidates.values(), key=lambda x: (x["stars_snapshot"], x["pushed_at"] or ""), reverse=True)
    path = Path("catalog/discovery_candidates.json")
    path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(ordered),
        "policy": "Metadata-only discovery. Candidate repositories are not cloned, installed, imported, or executed.",
        "candidates": ordered,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(ordered)} metadata-only candidates to {path}")


if __name__ == "__main__":
    main()
