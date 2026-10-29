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
        if not path.exists():
            return cls([])
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError("Catalog root must be a JSON array")
        return cls(loaded)

    def list(
        self,
        q: str | None = None,
        category: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        capability: str | None = None,
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
