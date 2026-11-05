"""Read-mostly git helpers for the built-in editor.

Deliberately narrow: status, diff, log, and a single local commit. No push, no
force, no reset — an API that can rewrite history is an API that can delete the
user's work. Commit is in the approval-gated list (`/v1/git/commit`).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

MAX_DIFF_BYTES = 200_000


class GitError(RuntimeError):
    """Not a repository, or git refused the command."""


def repo_root() -> Path:
    override = os.getenv("UAI_GIT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def _run(*args: str, timeout: int = 20) -> str:
    root = repo_root()
    if not (root / ".git").exists():
        raise GitError(f"not a git repository: {root}")
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"},
        )
    except FileNotFoundError:
        raise GitError("git is not installed in this container")
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out")
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise GitError(message[0] if message else f"git {args[0]} failed")
    return completed.stdout


def status() -> dict[str, Any]:
    raw = _run("status", "--porcelain=v1", "--branch")
    branch = "unknown"
    ahead = behind = 0
    files: list[dict[str, Any]] = []

    for line in raw.splitlines():
        if line.startswith("##"):
            header = line[2:].strip()
            branch = header.split("...")[0].strip() or "detached"
            if "[" in header:
                meta = header.split("[", 1)[1].rstrip("]")
                for part in meta.split(","):
                    part = part.strip()
                    if part.startswith("ahead "):
                        ahead = int(part.split()[1])
                    elif part.startswith("behind "):
                        behind = int(part.split()[1])
            continue
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append({"code": code.strip() or "??", "path": path, "staged": code[0] not in " ?"})

    return {
        "root": str(repo_root()),
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(files),
        "file_count": len(files),
        "files": files[:200],
    }


def diff(path: str | None = None, staged: bool = False) -> dict[str, Any]:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", _safe_path(path)])
    text = _run(*args)
    truncated = len(text.encode("utf-8")) > MAX_DIFF_BYTES
    if truncated:
        text = text.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", "ignore")
    added = sum(1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in text.splitlines() if line.startswith("-") and not line.startswith("---"))
    return {
        "path": path,
        "staged": staged,
        "bytes": len(text.encode("utf-8")),
        "truncated": truncated,
        "added": added,
        "removed": removed,
        "diff": text,
    }


def log(limit: int = 10) -> dict[str, Any]:
    raw = _run("log", f"-{max(1, min(limit, 100))}", "--pretty=format:%h%x1f%an%x1f%ar%x1f%s")
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"sha": parts[0], "author": parts[1], "when": parts[2], "subject": parts[3]})
    return {"count": len(commits), "commits": commits}


def _safe_path(path: str) -> str:
    """Paths are passed after `--`, but a leading dash or an escape is still refused."""

    if not path or path.startswith("-"):
        raise GitError("invalid path")
    root = repo_root().resolve()
    candidate = (root / path).resolve()
    if root != candidate and root not in candidate.parents:
        raise GitError("path escapes the repository")
    return path


def commit(message: str, paths: list[str] | None = None, add_all: bool = False) -> dict[str, Any]:
    """Stage and commit locally. Never pushes."""

    message = (message or "").strip()
    if len(message) < 3:
        raise GitError("commit message is too short")

    staged: list[str] = []
    if add_all:
        _run("add", "-A")
        staged = ["*"]
    elif paths:
        safe = [_safe_path(path) for path in paths]
        _run("add", "--", *safe)
        staged = safe

    pending = status()["file_count"]
    if not pending:
        raise GitError("nothing to commit")

    _run("commit", "-m", message, timeout=60)
    head = log(limit=1)["commits"]
    return {
        "committed": True,
        "staged": staged,
        "sha": head[0]["sha"] if head else None,
        "subject": head[0]["subject"] if head else message,
        "pushed": False,
        "note": "local commit only — push is deliberately not exposed over HTTP",
    }
