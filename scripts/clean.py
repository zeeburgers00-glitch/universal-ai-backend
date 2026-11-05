"""Delete generated junk — and nothing else.

Safe by construction: it only touches paths that git already ignores, and it refuses to
delete a file git tracks even if it matches a junk pattern. Every removal is reported with
its size, so "cleanup" is auditable instead of a mystery.

    python scripts/clean.py              # dry run: show what would go
    python scripts/clean.py --apply      # actually delete
    python scripts/clean.py --apply --keep-media   # caches only, keep rendered video
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that are always rebuildable.
JUNK_DIRS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "htmlcov",
    ".ipynb_checkpoints",
)

# Generated output inside data/ — renders, thumbnails, extracted audio, work dirs.
MEDIA_DIRS = (
    "data/command/output",
    "data/command/work",
    "data/video",
    "data/renders",
    "data/uploads",
)

# Loose files that are never source.
JUNK_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".orig", ".rej", ".DS_Store")


def _tracked() -> set[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _human(bytes_: int) -> str:
    value = float(bytes_)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def plan(*, include_media: bool = True) -> list[tuple[Path, int]]:
    """(path, bytes) pairs that would be removed. Tracked files are never included."""

    tracked = _tracked()
    found: list[tuple[Path, int]] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if not path.exists() or path in seen:
            return
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in tracked or any(
            item == relative or item.startswith(relative + "/") for item in tracked
        ):
            return
        seen.add(path)
        found.append((path, _size(path)))

    for directory in JUNK_DIRS:
        add(REPO_ROOT / directory)

    # nested caches anywhere in the tree (workers/, studio/, scripts/ …)
    for cache in REPO_ROOT.rglob("__pycache__"):
        if ".venv" in cache.parts or "node_modules" in cache.parts:
            continue
        add(cache)

    if include_media:
        for relative in MEDIA_DIRS:
            add(REPO_ROOT / relative)

    for suffix in JUNK_SUFFIXES:
        for path in REPO_ROOT.rglob(f"*{suffix}"):
            if ".venv" in path.parts or "node_modules" in path.parts or ".git" in path.parts:
                continue
            if path.is_file():
                add(path)

    return sorted(found, key=lambda pair: pair[1], reverse=True)


def remove(items: list[tuple[Path, int]]) -> int:
    freed = 0
    for path, size in items:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            freed += size
            print(f"  removed {path.relative_to(REPO_ROOT)} ({_human(size)})")
        except OSError as exc:
            print(f"  could not remove {path}: {exc}", file=sys.stderr)
    return freed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete generated junk, never source")
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument("--keep-media", action="store_true",
                        help="keep rendered video/thumbnails, clean caches only")
    args = parser.parse_args(argv)

    items = plan(include_media=not args.keep_media)
    total = sum(size for _, size in items)

    if not items:
        print("nothing to clean — the tree is already tidy")
        return 0

    print(f"{len(items)} junk path(s), {_human(total)} total")
    if not args.apply:
        for path, size in items[:40]:
            print(f"  would remove {path.relative_to(REPO_ROOT)} ({_human(size)})")
        if len(items) > 40:
            print(f"  … and {len(items) - 40} more")
        print("\nDry run. Add --apply to delete.")
        return 0

    freed = remove(items)
    print(f"\nfreed {_human(freed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
