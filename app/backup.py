"""Backup and restore the data directory without leaving the box.

Everything durable lives under ``UAI_DATA_ROOT`` (SQLite DBs, quota state, JSONL
registry caches, media outputs). A backup is therefore a single tar.gz, and a
restore is a safe extraction that refuses to escape the data root.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

BACKUP_SUFFIX = ".tar.gz"
MAX_BACKUPS = 10


class BackupError(RuntimeError):
    """Bad input or an unsafe archive."""


def data_root() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT", "/data")).expanduser()
    return root


def backup_dir() -> Path:
    folder = data_root() / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skip_media(include_media: bool):
    media_suffixes = {".mp4", ".mkv", ".mov", ".webm", ".wav", ".mp3", ".m4a", ".flac", ".ogg"}
    skip_dirs = {"backups", "__pycache__", "node_modules", ".git"}

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(info.name).parts
        if any(part in skip_dirs for part in parts):
            return None
        if not include_media and Path(info.name).suffix.lower() in media_suffixes:
            return None
        return info

    return _filter


def create_backup(include_media: bool = False, label: str | None = None) -> dict[str, Any]:
    """Tar up the data root. Returns size, checksum and file count."""

    root = data_root()
    if not root.exists():
        raise BackupError(f"data root does not exist: {root}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(char for char in (label or "manual") if char.isalnum() or char in "-_")[:40] or "manual"
    target = backup_dir() / f"{stamp}-{safe_label}{BACKUP_SUFFIX}"

    files = 0
    with tarfile.open(target, "w:gz") as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in {"backups", "__pycache__"} for part in relative.parts):
                continue
            if not include_media and path.suffix.lower() in {
                ".mp4", ".mkv", ".mov", ".webm", ".wav", ".mp3", ".m4a", ".flac", ".ogg"
            }:
                continue
            archive.add(path, arcname=str(relative))
            files += 1

    _prune()
    return {
        "name": target.name,
        "path": str(target),
        "bytes": target.stat().st_size,
        "files": files,
        "sha256": _sha256(target),
        "include_media": include_media,
        "created_at": stamp,
    }


def _prune() -> None:
    backups = sorted(backup_dir().glob(f"*{BACKUP_SUFFIX}"), key=lambda p: p.stat().st_mtime)
    for stale in backups[:-MAX_BACKUPS]:
        stale.unlink(missing_ok=True)


def list_backups() -> dict[str, Any]:
    entries = []
    for path in sorted(backup_dir().glob(f"*{BACKUP_SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        entries.append({
            "name": path.name,
            "bytes": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        })
    return {"count": len(entries), "backups": entries}


def backup_path(name: str) -> Path:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise BackupError("invalid backup name")
    candidate = backup_dir() / name
    if not candidate.is_file():
        raise BackupError(f"backup not found: {name}")
    return candidate


def _safe_members(archive: tarfile.TarFile, destination: Path) -> list[tarfile.TarInfo]:
    root = destination.resolve()
    safe: list[tarfile.TarInfo] = []
    for member in archive.getmembers():
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            raise BackupError(f"unsafe path in archive: {member.name}")
        resolved = (destination / member.name).resolve()
        if root != resolved and root not in resolved.parents:
            raise BackupError(f"archive escapes the data root: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise BackupError(f"unsupported member type: {member.name}")
        safe.append(member)
    return safe


def restore_backup(name: str, snapshot_first: bool = True) -> dict[str, Any]:
    """Extract a backup over the data root, snapshotting the current state first."""

    archive_path = backup_path(name)
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)

    snapshot = create_backup(include_media=False, label="pre-restore") if snapshot_first else None

    restored: list[str] = []
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _safe_members(archive, root)
        for member in members:
            archive.extract(member, path=root, set_attrs=False)
            if member.isfile():
                restored.append(member.name)

    return {
        "restored_from": name,
        "files": len(restored),
        "sample": restored[:10],
        "pre_restore_snapshot": snapshot["name"] if snapshot else None,
        "data_root": str(root),
    }


def verify_backup(name: str) -> dict[str, Any]:
    """Check an archive opens and every member is safe — no writes."""

    archive_path = backup_path(name)
    root = data_root()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _safe_members(archive, root)
    return {
        "name": name,
        "members": len(members),
        "bytes": archive_path.stat().st_size,
        "sha256": _sha256(archive_path),
    }


def wipe_tmp(root: Path | None = None) -> None:
    """Remove scratch dirs a crashed run may leave behind (used by ops scripts)."""

    base = root or data_root()
    for candidate in base.glob("tmp-*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def manifest() -> dict[str, Any]:
    root = data_root()
    files = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
    by_suffix: dict[str, int] = {}
    for path in files:
        key = path.suffix.lower() or "(none)"
        by_suffix[key] = by_suffix.get(key, 0) + 1
    return {
        "data_root": str(root),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "by_suffix": dict(sorted(by_suffix.items(), key=lambda pair: -pair[1])[:12]),
        "backups": list_backups()["count"],
    }


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
