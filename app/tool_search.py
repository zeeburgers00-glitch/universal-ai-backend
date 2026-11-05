"""BM25 search over everything this backend can do.

Two corpora, one ranker:

* **tools** — the 205 vetted GitHub repos in ``catalog/github_repos.json``
* **routes** — the live OpenAPI schema, so "how do I cut silence" finds the endpoint

BM25 (not embeddings) because it runs offline, needs no model, and is honest about
why it matched: the response carries the matched terms and the per-term score.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

from . import github_registry

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "the", "for", "to", "of", "in", "on", "and", "or", "with", "how",
    "do", "i", "is", "it", "my", "me", "can", "you", "what", "which", "that",
    "app", "tool", "tools", "api", "using", "use", "best", "some", "any",
}

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall((text or "").lower()) if token not in STOPWORDS and len(token) > 1]


def _document(tool: dict[str, Any]) -> str:
    """Everything searchable about one tool, weighted by repetition.

    BM25 counts term frequency, so repeating the fields that actually identify a
    tool (name, topics, categories, what it maps to) lifts signal above prose.
    """

    name = tool.get("full_name", "") or ""
    short = name.split("/")[-1]
    description = tool.get("description", "") or ""
    topics = " ".join(tool.get("topics", []) or [])
    categories = " ".join(tool.get("categories", []) or [])
    maps_to = (tool.get("maps_to", "") or "").replace("_", " ")
    parts = [
        name, short, short, short,
        categories, categories, categories,
        topics, topics,
        maps_to, maps_to,
        description,
        tool.get("language", "") or "",
    ]
    return " ".join(str(part) for part in parts if part)


class BM25:
    """Tiny BM25 implementation — no dependency, ~40 lines of maths."""

    def __init__(self, documents: list[list[str]]) -> None:
        self.documents = documents
        self.sizes = [len(document) for document in documents]
        self.average = (sum(self.sizes) / len(self.sizes)) if self.sizes else 0.0
        self.term_frequencies = [Counter(document) for document in documents]
        self.document_frequency: Counter[str] = Counter()
        for frequencies in self.term_frequencies:
            for term in frequencies:
                self.document_frequency[term] += 1
        self.total = len(documents)

    def idf(self, term: str) -> float:
        frequency = self.document_frequency.get(term, 0)
        return math.log(1 + (self.total - frequency + 0.5) / (frequency + 0.5))

    def score(self, query: list[str], index: int) -> tuple[float, list[str]]:
        total = 0.0
        matched: list[str] = []
        frequencies = self.term_frequencies[index]
        size = self.sizes[index] or 1
        for term in query:
            count = frequencies.get(term, 0)
            if not count:
                continue
            matched.append(term)
            numerator = count * (K1 + 1)
            denominator = count + K1 * (1 - B + B * (size / (self.average or 1)))
            total += self.idf(term) * (numerator / denominator)
        return total, matched

    def search(self, query: str, limit: int = 10, min_score: float = 0.0) -> list[dict[str, Any]]:
        terms = tokenize(query)
        if not terms:
            return []
        results = []
        unique_terms = list(dict.fromkeys(terms))
        for index in range(self.total):
            score, matched = self.score(terms, index)
            coverage = len(set(matched)) / (len(unique_terms) or 1)
            # Reward documents that match *more of the question*, not just one rare word.
            score *= 1 + coverage
            if score > min_score and matched:
                results.append({
                    "index": index,
                    "score": round(score, 4),
                    "matched": sorted(set(matched)),
                    "coverage": round(coverage, 2),
                })
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]


def _tools() -> list[dict[str, Any]]:
    try:
        return github_registry.load().get("repos", [])
    except github_registry.RegistryUnavailable:
        return []


def search_tools(query: str, limit: int = 10) -> dict[str, Any]:
    """Find repositories that could do the job the user described."""

    repos = _tools()
    if not repos:
        return {
            "query": query,
            "count": 0,
            "results": [],
            "hint": "catalog/github_repos.json missing — run scripts/fetch_github_repos.py",
        }

    ranker = BM25([tokenize(_document(repo)) for repo in repos])
    hits = ranker.search(query, limit=limit)
    results = []
    for hit in hits:
        repo = repos[hit["index"]]
        results.append({
            "full_name": repo.get("full_name"),
            "url": repo.get("url"),
            "description": (repo.get("description") or "")[:220],
            "stars": repo.get("stars"),
            "language": repo.get("language"),
            "license": repo.get("license"),
            "categories": repo.get("categories", []),
            "maps_to": repo.get("maps_to"),
            "integration": repo.get("integration", "reference-only"),
            "score": hit["score"],
            "matched": hit["matched"],
            "coverage": hit["coverage"],
        })
    return {"query": query, "count": len(results), "corpus": len(repos), "results": results}


def search_routes(query: str, openapi: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    """Find the endpoint that answers a question, from the live schema."""

    entries: list[tuple[str, str, str, str]] = []  # (label, method, path, text)
    for path, operations in openapi.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            label = operation.get("summary") or operation.get("operationId") or path
            text = " ".join([
                path.replace("/", " ").replace("_", " ").replace("-", " "),
                label,
                operation.get("description") or "",
                " ".join(tag for tag in operation.get("tags", []) or []),
            ])
            entries.append((label, method.upper(), path, text))

    if not entries:
        return {"query": query, "count": 0, "results": []}

    ranker = BM25([tokenize(entry[3]) for entry in entries])
    hits = ranker.search(query, limit=limit)
    results = []
    for hit in hits:
        label, method, path, _ = entries[hit["index"]]
        results.append({
            "method": method,
            "path": path,
            "summary": label[:160],
            "score": hit["score"],
            "matched": hit["matched"],
        })
    return {"query": query, "count": len(results), "corpus": len(entries), "results": results}


def capabilities() -> dict[str, Any]:
    """A plain-language map of what this backend can do, grouped by area."""

    from .main import app  # local import to avoid a cycle

    groups = {
        "video": [path for path in app.openapi()["paths"] if "/video/" in path or "/jobs" in path],
        "code": [path for path in app.openapi()["paths"] if "/code/" in path],
        "ai": [path for path in app.openapi()["paths"] if path.startswith("/v1/ai")],
        "ops": [
            path for path in app.openapi()["paths"]
            if any(key in path for key in ("/metrics", "/data/", "/audit", "/observability", "/sdk", "/tools"))
        ],
    }
    return {
        "groups": {name: {"routes": len(paths), "sample": sorted(paths)[:6]} for name, paths in groups.items()},
        "tools": {"corpus": len(_tools())},
        "total_routes": len(app.openapi()["paths"]),
    }
