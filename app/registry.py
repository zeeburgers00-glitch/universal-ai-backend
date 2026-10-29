from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog" / "tools.json"


def _normalize_repo_url(raw_url: Any) -> str:
    url = str(raw_url or "").strip().lower().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4].rstrip("/")
    return url


def _build_search_blob(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False).casefold()


class Registry:
    """In-process catalog index. Persist registrations in a database for production."""

    def __init__(self, items: list[dict[str, Any]]):
        self.items = [dict(x) for x in items]
        self._search_blobs = [_build_search_blob(x) for x in self.items]

    @classmethod
    def from_file(cls, filename: str | Path = CATALOG_PATH) -> "Registry":
        path = Path(filename)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        default_catalog = path.resolve() == CATALOG_PATH.resolve()
        paths = (
            [
                CATALOG_PATH,
                CATALOG_PATH.with_name("extended.json"),
                CATALOG_PATH.with_name("commercial.json"),
                CATALOG_PATH.with_name("llmops.json"),
                CATALOG_PATH.with_name("voice_media.json"),
                CATALOG_PATH.with_name("mcp_ecosystem.json"),
                CATALOG_PATH.with_name("global_ai_directory.json"),
            ]
            if default_catalog
            else [path]
        )
        # Merge catalogs by upstream repository URL. Later catalogs can enrich license
        # and commercial-model notes while preserving the original stable ID for
        # backward compatibility with app clients.
        merged: dict[str, dict[str, Any]] = {}
        for catalog_path in paths:
            if not catalog_path.exists():
                continue
            loaded = json.loads(catalog_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, list):
                raise ValueError(f"Catalog root must be a JSON array: {catalog_path.name}")
            for raw_item in loaded:
                if not isinstance(raw_item, dict) or not raw_item.get("id"):
                    continue
                repo_url = _normalize_repo_url(raw_item.get("repository_url"))
                key = repo_url if repo_url else f"id:{raw_item['id']}"
                if key in merged:
                    stable_id = merged[key].get("id", raw_item["id"])
                    merged[key] = {**merged[key], **raw_item, "id": stable_id}
                else:
                    merged[key] = dict(raw_item)
        return cls(list(merged.values()))

    def list(
        self,
        q: str | None = None,
        category: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        capability: str | None = None,
        license_status: str | None = None,
        source_classification: str | None = None,
        min_stars: int | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        indices = range(len(self.items))
        if q:
            needle = q.casefold()
            indices = [i for i in indices if needle in self._search_blobs[i]]
        result = [self.items[i] for i in indices]
        if category:
            wanted_cat = category.casefold()
            result = [item for item in result if str(item.get("category", "")).casefold() == wanted_cat]
        if status:
            wanted_status = status.casefold()
            result = [item for item in result if str(item.get("status", "")).casefold() == wanted_status]
        if kind:
            wanted_kind = kind.casefold()
            result = [item for item in result if str(item.get("kind", "")).casefold() == wanted_kind]
        if capability:
            cap = capability.casefold()
            result = [item for item in result if any(cap == str(x).casefold() for x in item.get("capabilities", []))]
        if license_status:
            wanted_lic = license_status.casefold()
            result = [item for item in result if str(item.get("license_status", "unknown")).casefold() == wanted_lic]
        if source_classification:
            wanted_src = source_classification.casefold()
            result = [item for item in result if wanted_src in str(item.get("source_classification", "")).casefold()]
        if min_stars is not None:
            result = [item for item in result if int(item.get("stars_snapshot") or 0) >= min_stars]
        if language:
            wanted_lang = language.casefold()
            result = [item for item in result if str(item.get("primary_language") or "").casefold() == wanted_lang]
        return [dict(item) for item in result]

    def get(self, tool_id: str) -> dict[str, Any] | None:
        item = next((x for x in self.items if x.get("id") == tool_id), None)
        return dict(item) if item else None

    def categories(self) -> list[str]:
        return sorted({str(x.get("category", "uncategorized")) for x in self.items})

    def add(self, item: dict[str, Any]) -> dict[str, Any]:
        if self.get(item["id"]):
            raise ValueError("A tool with this id already exists")
        record = dict(item)
        self.items.append(record)
        self._search_blobs.append(_build_search_blob(record))
        # Serverless memory may be discarded. Use managed PostgreSQL/Supabase for persistence.
        return dict(record)
