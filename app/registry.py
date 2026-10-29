import json
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog" / "tools.json"


class Registry:
    """In-process catalog index. Persist registrations in a database for production."""

    def __init__(self, items: list[dict[str, Any]]):
        self.items = items

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
                repo_url = str(raw_item.get("repository_url") or "").lower().rstrip("/")
                key = repo_url.removesuffix(".git") if repo_url else f"id:{raw_item['id']}"
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
    ) -> list[dict[str, Any]]:
        result = self.items
        if q:
            needle = q.casefold()
            result = [
                item for item in result
                if needle in json.dumps(item, ensure_ascii=False).casefold()
            ]
        if category:
            result = [item for item in result if item.get("category", "").casefold() == category.casefold()]
        if status:
            result = [item for item in result if item.get("status", "").casefold() == status.casefold()]
        if kind:
            result = [item for item in result if item.get("kind", "").casefold() == kind.casefold()]
        if capability:
            cap = capability.casefold()
            result = [item for item in result if any(cap == str(x).casefold() for x in item.get("capabilities", []))]
        if license_status:
            wanted = license_status.casefold()
            result = [item for item in result if str(item.get("license_status", "unknown")).casefold() == wanted]
        if source_classification:
            wanted = source_classification.casefold()
            result = [item for item in result if wanted in str(item.get("source_classification", "")).casefold()]
        return [dict(item) for item in result]

    def get(self, tool_id: str) -> dict[str, Any] | None:
        item = next((x for x in self.items if x.get("id") == tool_id), None)
        return dict(item) if item else None

    def categories(self) -> list[str]:
        return sorted({str(x.get("category", "uncategorized")) for x in self.items})

    def add(self, item: dict[str, Any]) -> dict[str, Any]:
        if self.get(item["id"]):
            raise ValueError("A tool with this id already exists")
        self.items.append(dict(item))
        # Serverless memory may be discarded. Use managed PostgreSQL/Supabase for persistence.
        return dict(item)
