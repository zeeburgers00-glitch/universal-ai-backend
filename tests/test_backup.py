"""Backup and restore: real archives, real round trip, unsafe archives refused."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import backup
from app.main import app


@pytest.fixture(autouse=True)
def data_root(monkeypatch, tmp_path):
    root = tmp_path / "data"
    (root / "nested").mkdir(parents=True)
    (root / "state.json").write_text('{"ok": true}', encoding="utf-8")
    (root / "nested" / "log.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "clip.mp4").write_bytes(b"x" * 2048)  # media, excluded by default
    monkeypatch.setenv("UAI_DATA_ROOT", str(root))
    monkeypatch.setenv("BACKEND_API_KEY", "data-key")
    return root


HEADERS = {"X-API-Key": "data-key"}


def test_manifest_reports_the_files(data_root):
    manifest = backup.manifest()
    assert manifest["files"] >= 3
    assert manifest["by_suffix"][".mp4"] == 1


def test_backup_writes_a_real_archive(data_root):
    result = backup.create_backup(label="nightly")
    path = Path(result["path"])
    assert path.is_file() and path.stat().st_size > 0
    assert result["files"] >= 2
    assert len(result["sha256"]) == 64
    assert "nightly" in result["name"]

    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    assert "state.json" in names
    assert "nested/log.jsonl" in names
    assert "clip.mp4" not in names, "media excluded unless asked"


def test_media_can_be_included(data_root):
    result = backup.create_backup(include_media=True)
    with tarfile.open(result["path"], "r:gz") as archive:
        assert "clip.mp4" in archive.getnames()


def test_restore_round_trip(data_root):
    original = (data_root / "state.json").read_text(encoding="utf-8")
    created = backup.create_backup()

    (data_root / "state.json").write_text('{"ok": false}', encoding="utf-8")
    (data_root / "nested" / "log.jsonl").unlink()

    restored = backup.restore_backup(created["name"])
    assert restored["files"] >= 2
    assert (data_root / "state.json").read_text(encoding="utf-8") == original
    assert (data_root / "nested" / "log.jsonl").exists()
    assert restored["pre_restore_snapshot"], "current state is snapshotted first"


def test_verify_reads_without_writing(data_root):
    created = backup.create_backup()
    (data_root / "state.json").write_text("changed", encoding="utf-8")
    check = backup.verify_backup(created["name"])
    assert check["members"] >= 2
    assert (data_root / "state.json").read_text(encoding="utf-8") == "changed"


def test_prune_keeps_the_newest_ten(data_root):
    for index in range(12):
        backup.create_backup(label=f"b{index}")
    assert backup.list_backups()["count"] == backup.MAX_BACKUPS


def test_archive_escaping_the_root_is_refused(data_root, tmp_path):
    evil = backup.backup_dir() / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as archive:
        data = b"pwnd"
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    with pytest.raises(backup.BackupError):
        backup.restore_backup("evil.tar.gz", snapshot_first=False)
    assert not (tmp_path / "escaped.txt").exists()


def test_absolute_paths_in_archive_are_refused(data_root):
    evil = backup.backup_dir() / "abs.tar.gz"
    with tarfile.open(evil, "w:gz") as archive:
        data = b"pwnd"
        info = tarfile.TarInfo("/etc/passwd")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with pytest.raises(backup.BackupError):
        backup.restore_backup("abs.tar.gz", snapshot_first=False)


def test_backup_name_traversal_is_refused():
    with pytest.raises(backup.BackupError):
        backup.backup_path("../../etc/passwd")


# --- HTTP ---------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_data_routes_require_key(client):
    assert client.get("/v1/data/manifest").status_code == 401


def test_backup_restore_and_download_over_http(client, data_root):
    created = client.post("/v1/data/backup", headers=HEADERS, json={"label": "http"})
    assert created.status_code == 200
    name = created.json()["name"]

    listed = client.get("/v1/data/backups", headers=HEADERS).json()
    assert any(entry["name"] == name for entry in listed["backups"])

    (data_root / "state.json").unlink()
    restored = client.post("/v1/data/restore", headers=HEADERS, json={"name": name})
    assert restored.status_code == 200
    assert (data_root / "state.json").exists()

    download = client.get("/v1/data/download", params={"name": name}, headers=HEADERS)
    assert download.status_code == 200
    assert download.content[:2] == b"\x1f\x8b"


def test_missing_backup_is_400(client):
    assert client.post("/v1/data/restore", headers=HEADERS, json={"name": "nope.tar.gz"}).status_code == 400
