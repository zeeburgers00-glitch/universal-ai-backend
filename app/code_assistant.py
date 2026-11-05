"""Cursor-style code intelligence that runs with zero API keys.

Everything here is deterministic: an on-disk index, Python's own AST, regex symbol
extraction for other languages, and `git` for diffs. No model is called, so no key,
no quota, no per-request cost — the "unlimited and free" part is real because the
work is local computation.

What that buys you: repo index + symbol search, file outlines, safe patch generation
and application, heuristic review, test scaffolding, commit-message drafting, rules
files, and multi-step plans. What it does **not** do is invent code out of thin air;
that needs a model, and when one is configured the plan endpoint says so.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".next", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".turbo", "data",
    "coverage", ".idea", ".vscode", ".arena", ".cache",
}

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sh", ".sql", ".env",
    ".dockerfile", ".gitignore", ".example",
}

MAX_FILE_BYTES = 512 * 1024
MAX_INDEXED_FILES = 5000
SNIPPET_RADIUS = 2


class CodeAssistantError(ValueError):
    """Bad input from the caller (unknown path, binary file, unsafe path)."""


def data_dir() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    return root / "code"


def index_path() -> Path:
    return data_dir() / "index.json"


# --------------------------------------------------------------------------- #
# Path handling — everything must stay inside the repository
# --------------------------------------------------------------------------- #
def safe_path(relative: str) -> Path:
    if not relative or relative.strip() in {".", "/"}:
        raise CodeAssistantError("path is required")
    candidate = (REPO_ROOT / relative).resolve()
    if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
        raise CodeAssistantError("path escapes the repository")
    if not candidate.is_file():
        raise CodeAssistantError(f"not a file: {relative}")
    return candidate


def _is_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        chunk = path.open("rb").read(2048)
    except OSError:
        return False
    return b"\x00" not in chunk


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace(os.sep, "/")


def _walk_files(root: Path | None = None) -> Iterable[Path]:
    base = (root or REPO_ROOT).resolve()
    if base != REPO_ROOT and REPO_ROOT not in base.parents:
        raise CodeAssistantError("root escapes the repository")
    count = 0
    for path in sorted(base.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        if not _is_text(path):
            continue
        yield path
        count += 1
        if count >= MAX_INDEXED_FILES:
            return


# --------------------------------------------------------------------------- #
# Symbols
# --------------------------------------------------------------------------- #
PY_KEYWORDS = {"if", "for", "while", "with", "return", "try", "except", "else", "elif", "class", "def"}


def _python_symbols(source: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[dict[str, Any]] = []

    def visit(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                found.append({
                    "name": f"{prefix}{child.name}", "kind": "class",
                    "line": child.lineno, "doc": (ast.get_docstring(child) or "")[:200],
                })
                visit(child, prefix=f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in child.args.args if a.arg not in {"self", "cls"}]
                found.append({
                    "name": f"{prefix}{child.name}", "kind": "function" if not prefix else "method",
                    "line": child.lineno, "args": args,
                    "doc": (ast.get_docstring(child) or "")[:200],
                })
                visit(child, prefix=f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree)
    return found


GENERIC_SYMBOL = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|def|const|let|var)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def _generic_symbols(source: str) -> list[dict[str, Any]]:
    found = []
    for match in GENERIC_SYMBOL.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        found.append({"name": match.group(1), "kind": "symbol", "line": line})
    return found


def _symbols_for(path: Path, source: str) -> list[dict[str, Any]]:
    if path.suffix == ".py":
        return _python_symbols(source)
    if path.suffix in {".js", ".ts", ".tsx", ".jsx"}:
        return _generic_symbols(source)
    return []


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
def build_index(root: str | None = None) -> dict[str, Any]:
    started = time.time()
    base = safe_root(root)
    files: list[dict[str, Any]] = []
    symbol_count = 0
    for path in _walk_files(base):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        symbols = _symbols_for(path, source)
        symbol_count += len(symbols)
        files.append({
            "path": _rel(path),
            "language": path.suffix.lstrip(".") or "text",
            "lines": source.count("\n") + 1,
            "bytes": len(source.encode("utf-8")),
            "symbols": symbols,
        })

    payload = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": _rel(base) if base != REPO_ROOT else ".",
        "file_count": len(files),
        "symbol_count": symbol_count,
        "total_lines": sum(f["lines"] for f in files),
        "files": files,
    }
    path = index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        # Read-only filesystem: still return the index, just don't persist it.
        payload["persisted"] = False
    return {
        "file_count": payload["file_count"],
        "symbol_count": payload["symbol_count"],
        "total_lines": payload["total_lines"],
        "built_at": payload["built_at"],
        "build_ms": int((time.time() - started) * 1000),
        "languages": _language_breakdown(files),
    }


def safe_root(root: str | None) -> Path:
    if not root or root in {".", "./"}:
        return REPO_ROOT
    candidate = (REPO_ROOT / root).resolve()
    if REPO_ROOT not in candidate.parents and candidate != REPO_ROOT:
        raise CodeAssistantError("root escapes the repository")
    if not candidate.is_dir():
        raise CodeAssistantError(f"not a directory: {root}")
    return candidate


def _language_breakdown(files: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in files:
        counts[item["language"]] = counts.get(item["language"], 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: -pair[1]))


def load_index() -> dict[str, Any]:
    path = index_path()
    if not path.is_file():
        raise CodeAssistantError("no index yet — POST /v1/code/index first")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_index() -> dict[str, Any]:
    try:
        return load_index()
    except CodeAssistantError:
        build_index()
        return load_index()


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def search(query: str, kind: str | None = None, limit: int = 20, path_prefix: str | None = None) -> dict[str, Any]:
    needle = query.strip().lower()
    if len(needle) < 2:
        raise CodeAssistantError("query must be at least 2 characters")

    index = ensure_index()
    hits: list[dict[str, Any]] = []

    for entry in index["files"]:
        if path_prefix and not entry["path"].startswith(path_prefix):
            continue
        if kind and entry["language"] != kind:
            continue

        name_hit = needle in entry["path"].lower()
        symbol_hits = [s for s in entry["symbols"] if needle in str(s.get("name", "")).lower()]
        if not name_hit and not symbol_hits:
            # fall through to content scan so free-text queries still work
            pass

        try:
            source = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        content_hits = [i for i, line in enumerate(source.splitlines(), 1) if needle in line.lower()]
        if not (name_hit or symbol_hits or content_hits):
            continue

        score = (3 if name_hit else 0) + 2 * len(symbol_hits) + min(len(content_hits), 10)
        hits.append({
            "path": entry["path"],
            "language": entry["language"],
            "score": score,
            "symbols": symbol_hits[:5],
            "matches": len(content_hits),
            "snippets": _snippets(source, content_hits[:3]),
        })

    hits.sort(key=lambda hit: (-hit["score"], hit["path"]))
    return {"query": query, "total": len(hits), "returned": len(hits[:limit]), "hits": hits[:limit]}


def _snippets(source: str, lines: list[int]) -> list[dict[str, Any]]:
    all_lines = source.splitlines()
    snippets = []
    for line_no in lines:
        start = max(1, line_no - SNIPPET_RADIUS)
        end = min(len(all_lines), line_no + SNIPPET_RADIUS)
        snippets.append({
            "line": line_no,
            "text": "\n".join(f"{n:>5}: {all_lines[n - 1]}" for n in range(start, end + 1)),
        })
    return snippets


# --------------------------------------------------------------------------- #
# Outline
# --------------------------------------------------------------------------- #
def outline(relative: str) -> dict[str, Any]:
    path = safe_path(relative)
    source = path.read_text(encoding="utf-8", errors="replace")
    imports = [
        line.strip() for line in source.splitlines()
        if line.startswith(("import ", "from ")) or line.startswith("#include")
    ][:80]
    return {
        "path": _rel(path),
        "language": path.suffix.lstrip(".") or "text",
        "lines": source.count("\n") + 1,
        "bytes": len(source.encode("utf-8")),
        "imports": imports,
        "symbols": _symbols_for(path, source),
        "todo_count": len(re.findall(r"\b(TODO|FIXME|XXX|HACK)\b", source)),
    }


# --------------------------------------------------------------------------- #
# Patch: diff + apply
# --------------------------------------------------------------------------- #
def _read_text(path: Path) -> str:
    if not _is_text(path):
        raise CodeAssistantError("file is not text")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise CodeAssistantError("file is too large to edit safely")
    return path.read_text(encoding="utf-8")


def propose_edit(relative: str, find: str, replace: str) -> dict[str, Any]:
    path = safe_path(relative)
    source = _read_text(path)
    if not find:
        raise CodeAssistantError("find must not be empty")
    occurrences = source.count(find)
    if occurrences == 0:
        raise CodeAssistantError("find text was not found in the file")
    updated = source.replace(find, replace, 1)

    import difflib

    diff = list(difflib.unified_diff(
        source.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{_rel(path)}", tofile=f"b/{_rel(path)}",
    ))
    return {
        "path": _rel(path),
        "occurrences": occurrences,
        "will_change": occurrences >= 1,
        "diff": "".join(diff),
        "added_lines": sum(1 for line in diff if line.startswith("+") and not line.startswith("+++")),
        "removed_lines": sum(1 for line in diff if line.startswith("-") and not line.startswith("---")),
    }


def apply_edit(relative: str, find: str, replace: str, dry_run: bool = True) -> dict[str, Any]:
    preview = propose_edit(relative, find, replace)
    if dry_run:
        return {**preview, "applied": False, "reason": "dry_run"}

    path = safe_path(relative)
    source = _read_text(path)
    backup = path.with_suffix(path.suffix + ".bak")
    try:
        backup.write_text(source, encoding="utf-8")
        path.write_text(source.replace(find, replace, 1), encoding="utf-8")
    except OSError as exc:
        raise CodeAssistantError(f"could not write file: {exc}") from exc
    return {**preview, "applied": True, "backup": _rel(backup)}


# --------------------------------------------------------------------------- #
# Review (heuristics, no model)
# --------------------------------------------------------------------------- #
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*[\"'][^\"']{12,}[\"']"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
)


def review(paths: list[str] | None = None, limit: int = 400) -> dict[str, Any]:
    index = ensure_index()
    targets = index["files"]
    if paths:
        wanted = {p.strip() for p in paths}
        targets = [entry for entry in targets if entry["path"] in wanted]
    findings: list[dict[str, Any]] = []

    for entry in targets[:limit]:
        try:
            source = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = source.splitlines()

        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if len(line) > 160:
                findings.append(_finding(entry["path"], number, "long-line", "line longer than 160 chars", "low"))
            if re.search(r"\bexcept\s*:", stripped) or re.search(r"except\s+Exception\s*:\s*pass", stripped):
                findings.append(_finding(entry["path"], number, "bare-except", "catches everything silently", "medium"))
            if "eval(" in stripped or "os.system(" in stripped:
                findings.append(_finding(entry["path"], number, "dangerous-call", "eval/os.system with untrusted input", "high"))
            if "shell=True" in stripped and "subprocess" in stripped:
                findings.append(_finding(entry["path"], number, "shell-true", "shell=True risks command injection", "high"))
            if re.search(r"\bTODO\b|\bFIXME\b", stripped):
                findings.append(_finding(entry["path"], number, "todo", stripped[:120], "low"))
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(_finding(entry["path"], number, "possible-secret", "looks like a hard-coded credential", "high"))
                    break

        if entry["language"] == "py":
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                findings.append(_finding(entry["path"], exc.lineno or 1, "syntax-error", str(exc), "high"))
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        span = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno
                        if span > 80:
                            findings.append(_finding(entry["path"], node.lineno, "long-function",
                                                     f"{node.name}() spans {span} lines", "medium"))
                        if span > 3 and not ast.get_docstring(node) and not node.name.startswith("_"):
                            findings.append(_finding(entry["path"], node.lineno, "missing-docstring",
                                                     f"{node.name}() has no docstring", "low"))

    by_severity: dict[str, int] = {}
    for finding in findings:
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
    return {
        "files_reviewed": min(len(targets), limit),
        "total_findings": len(findings),
        "by_severity": by_severity,
        "findings": findings[:300],
        "mode": "heuristic",
        "note": "Static checks only — no model is called, so this is deterministic and free.",
    }


def _finding(path: str, line: int, rule: str, message: str, severity: str) -> dict[str, Any]:
    return {"path": path, "line": line, "rule": rule, "message": message, "severity": severity}


# --------------------------------------------------------------------------- #
# Test scaffolding
# --------------------------------------------------------------------------- #
def test_scaffold(relative: str, max_tests: int = 12) -> dict[str, Any]:
    path = safe_path(relative)
    source = path.read_text(encoding="utf-8", errors="replace")
    entry = {"path": _rel(path), "symbols": _symbols_for(path, source)}
    functions = [s for s in entry["symbols"] if s["kind"] in {"function", "method"} and s.get("args") is not None]

    module_name = _rel(path).replace("/", ".").removesuffix(".py")
    lines = [
        '"""Generated test scaffolding — fills in assertions is still your job."""',
        "",
        "from __future__ import annotations",
        "",
        "import pytest",
        "",
        f"import {module_name} as target",
        "",
    ]
    for symbol in functions[:max_tests]:
        name = symbol["name"].split(".")[-1]
        args = ", ".join(f"{arg}=None" for arg in symbol.get("args", []))
        lines += [
            f"def test_{name}_smoke():",
            f'    """{name}() should be reachable and behave."""',
            "    assert hasattr(target, " + repr(name) + ")",
            f"    # call it: target.{name}({args})",
            "",
        ]
    if not functions:
        lines += ["def test_module_imports():", "    assert target is not None", ""]

    return {
        "target": entry["path"],
        "suggested_test_file": f"tests/test_{path.stem}.py",
        "tests": len([s for s in functions[:max_tests]]),
        "content": "\n".join(lines),
    }


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #
def _git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodeAssistantError(f"git failed: {exc}") from exc
    if completed.returncode != 0:
        raise CodeAssistantError(completed.stderr.strip()[:300] or "git command failed")
    return completed.stdout


def commit_message() -> dict[str, Any]:
    stat = _git("diff", "--stat", "HEAD").strip()
    names = _git("diff", "--name-only", "HEAD").strip().splitlines()
    if not stat:
        return {"changed_files": 0, "suggestion": None, "note": "working tree is clean"}

    kinds = {"test": 0, "docs": 0, "code": 0}
    for name in names:
        if name.startswith("tests/") or "/test_" in name:
            kinds["test"] += 1
        elif name.endswith((".md", ".rst")) or name.startswith("docs/"):
            kinds["docs"] += 1
        else:
            kinds["code"] += 1

    if kinds["code"] and kinds["test"]:
        prefix = "feat"
    elif kinds["test"] and not kinds["code"]:
        prefix = "test"
    elif kinds["docs"] and not kinds["code"]:
        prefix = "docs"
    else:
        prefix = "chore"

    areas = sorted({name.split("/")[0] for name in names})[:3]
    counts = [line.split("|")[-1].strip() for line in stat.splitlines() if "|" in line]
    return {
        "changed_files": len(names),
        "files": names[:40],
        "suggestion": f"{prefix}: update {', '.join(areas) or 'project'}",
        "detail": counts[-1] if counts else "",
        "stat": stat,
    }


def rules() -> dict[str, Any]:
    """Read the rule files other AI editors use, so one repo configures them all."""

    candidates = [".cursorrules", ".cursor/rules", "AGENTS.md", "CLAUDE.md", ".aiexclude", ".github/copilot-instructions.md"]
    found: dict[str, str] = {}
    for name in candidates:
        path = REPO_ROOT / name
        if path.is_file():
            try:
                found[name] = path.read_text(encoding="utf-8", errors="replace")[:20_000]
            except OSError:
                continue
    return {"found": sorted(found), "count": len(found), "rules": found}


# --------------------------------------------------------------------------- #
# Plan (multi-step, deterministic)
# --------------------------------------------------------------------------- #
def plan(goal: str, max_steps: int = 6) -> dict[str, Any]:
    text = goal.strip()
    if len(text) < 3:
        raise CodeAssistantError("goal must be at least 3 characters")

    related = search(text, limit=8)["hits"] if text else []
    steps = [
        {"step": 1, "action": "locate", "detail": f"Find the code that owns this: {', '.join(h['path'] for h in related[:5]) or 'no direct match — start from the router in app/main.py'}"},
        {"step": 2, "action": "read", "detail": "Outline the target files (GET /v1/code/outline) before editing anything."},
        {"step": 3, "action": "patch", "detail": "Generate the change as a diff (POST /v1/code/diff) and review it."},
        {"step": 4, "action": "apply", "detail": "Apply with a backup (POST /v1/code/apply, dry_run=false)."},
        {"step": 5, "action": "prove", "detail": "Add tests (POST /v1/code/tests) and run the suite."},
        {"step": 6, "action": "review", "detail": "Run the static review (POST /v1/code/review) and draft the commit."},
    ][:max_steps]

    from . import ai_router

    has_model = bool(ai_router.chain())
    return {
        "goal": text,
        "steps": steps,
        "related_files": related,
        "model_available": has_model,
        "note": (
            "Plan is deterministic. With a model configured (local Ollama or a free-tier key) "
            "the same steps can be executed by the agent worker; without one you still get "
            "search, diff, apply, tests and review."
        ),
    }
