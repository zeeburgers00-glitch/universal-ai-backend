"""Dependency audit: what we require, what we actually import, what we could drop.

`requirements.txt` drifts the moment a feature is removed. This module compares it
against a real AST scan of the source tree, so "free and minimal" stays provable
rather than a claim in a README.
"""

from __future__ import annotations

import ast
import re
from importlib import metadata
from pathlib import Path
from typing import Any

# Distribution name -> import name, where they differ.
IMPORT_ALIASES = {
    "pyyaml": "yaml",
    "python-dotenv": "dotenv",
    "python-multipart": "multipart",
    "imageio-ffmpeg": "imageio_ffmpeg",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "python-dateutil": "dateutil",
    "opencv-python-headless": "cv2",
    "opencv-python": "cv2",
}

# Importable but not distributed under the same name as the stdlib module.
STDLIB_GUESSES = {
    "sqlite3", "json", "os", "re", "time", "typing", "pathlib", "hashlib", "shutil",
    "subprocess", "threading", "tarfile", "io", "ast", "collections", "dataclasses",
    "datetime", "uuid", "math", "random", "logging", "base64", "csv", "textwrap",
    "functools", "itertools", "string", "tempfile", "traceback", "urllib", "socket",
    "asyncio", "contextlib", "enum", "glob", "inspect", "secrets", "statistics",
}

# Packages the *process* needs without any source file importing them: the ASGI
# server, FastAPI's multipart parser, the worker CLI.
RUNTIME_ONLY = {"uvicorn", "python-multipart", "celery", "gunicorn"}

# Optional extras that live outside the application package.
OPTIONAL_DIRS = {"deploy", "scripts", "workers", "videoengine"}

REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(\[[^\]]+\])?\s*(.*)$")
EXTRA_RE = re.compile(r"\[([^\]]+)\]")


class AuditError(RuntimeError):
    """Nothing to audit."""


def parse_requirements(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise AuditError(f"requirements file not found: {path}")

    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = REQUIREMENT_RE.match(line)
        if not match:
            continue
        name, extras, specifier = match.groups()
        entries.append({
            "name": name,
            "key": name.lower().replace("_", "-"),
            "extras": EXTRA_RE.findall(extras or ""),
            "specifier": specifier.strip(),
            "pinned": bool(re.search(r"==", specifier)),
            "bounded": bool(re.search(r"[<>~=]", specifier)),
        })
    return entries


def imported_modules(root: Path) -> dict[str, set[str]]:
    """Top-level module -> files that import it."""

    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if any(part in {".venv", "__pycache__", "build", "dist"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(str(path))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.setdefault(node.module.split(".")[0], set()).add(str(path))
    return found


def installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _relative(paths: set[str], root: Path) -> list[str]:
    result = []
    for entry in sorted(paths)[:8]:
        try:
            result.append(str(Path(entry).relative_to(root)))
        except ValueError:
            result.append(entry)
    return result


def audit(root: Path, requirements: Path) -> dict[str, Any]:
    required = parse_requirements(requirements)
    imports = imported_modules(root)

    used: list[dict[str, Any]] = []
    unused: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for entry in required:
        module = IMPORT_ALIASES.get(entry["key"], entry["key"].replace("-", "_"))
        users = imports.get(module, set())
        record = {
            "name": entry["name"],
            "module": module,
            "specifier": entry["specifier"],
            "installed": installed_version(entry["name"]),
            "pinned": entry["pinned"],
            "used_in": _relative(users, root),
            "usage_count": len(users),
            "runtime_only": entry["key"] in RUNTIME_ONLY,
        }
        if users or record["runtime_only"]:
            used.append(record)
        else:
            unused.append(record)

    required_modules = {
        IMPORT_ALIASES.get(entry["key"], entry["key"].replace("-", "_")) for entry in required
    }
    for module, users in imports.items():
        if module in STDLIB_GUESSES or module in required_modules:
            continue
        if module in {"app", "tests", "workers", "videoengine", "catalog", "scripts", "deploy", "studio", "tools"}:
            continue
        # Anything else is either stdlib or missing from requirements.
        if not installed_version(module) or module == "pytest":
            continue
        # Optional extras imported only from deploy/ or worker scripts are fine.
        only_optional = all(
            set(Path(entry).parts[:-1]) & OPTIONAL_DIRS for entry in users
        )
        if only_optional:
            continue
        missing.append({"module": module, "installed": installed_version(module), "used_in": _relative(users, root)})

    return {
        "requirements_file": str(requirements.name),
        "runtime_only": [entry["name"] for entry in used if entry["runtime_only"]],
        "declared": len(required),
        "used": used,
        "declared_but_not_imported": unused,
        "imported_but_not_declared": missing,
        "unpinned": [entry["name"] for entry in required if not entry["bounded"]],
        "python_files_scanned": len({path for users in imports.values() for path in users}),
        "top_imports": sorted(
            ({"module": module, "files": len(users)} for module, users in imports.items()),
            key=lambda item: -item["files"],
        )[:12],
    }


def verdict(report: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if report["declared_but_not_imported"]:
        names = ", ".join(entry["name"] for entry in report["declared_but_not_imported"])
        notes.append(f"Declared but never imported: {names}. Removing them makes installs faster.")
    if report["imported_but_not_declared"]:
        names = ", ".join(entry["module"] for entry in report["imported_but_not_declared"])
        notes.append(f"Imported but not declared: {names}.")
    if report["unpinned"]:
        notes.append(f"No version ceiling (risky on rebuild): {', '.join(report['unpinned'])}.")
    if not notes:
        notes.append("Requirements match the imports and every entry has a ceiling.")
    return notes
