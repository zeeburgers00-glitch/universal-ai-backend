"""The cleanup script must delete junk and absolutely nothing else."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load():
    import importlib.util

    spec = importlib.util.spec_from_file_location("clean", REPO / "scripts" / "clean.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A tiny git repo that looks like this project."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=False)

    git("init")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('real source')\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"x" * 500)
    (tmp_path / "data" / "command" / "output").mkdir(parents=True)
    (tmp_path / "data" / "command" / "output" / "render.mp4").write_bytes(b"y" * 2000)
    (tmp_path / "notes.log").write_text("noise\n")

    git("add", "app/main.py")
    git("commit", "-m", "init")

    module = _load()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    return module, tmp_path


def test_plan_finds_caches_and_renders_but_not_source(sandbox):
    module, root = sandbox
    planned = {path.relative_to(root).as_posix() for path, _ in module.plan()}

    assert "__pycache__" in planned
    assert "data/command/output" in planned
    assert "notes.log" in planned
    assert "app/main.py" not in planned


def test_tracked_files_are_never_deleted_even_if_they_look_like_junk(sandbox):
    module, root = sandbox
    tracked_junk = root / "kept.log"
    tracked_junk.write_text("tracked on purpose\n")
    subprocess.run(["git", "add", "-f", "kept.log"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "tracked junk"], cwd=root, capture_output=True)

    planned = {path.name for path, _ in module.plan()}
    assert "kept.log" not in planned


def test_keep_media_flag_spares_the_renders(sandbox):
    module, root = sandbox
    planned = {path.relative_to(root).as_posix() for path, _ in module.plan(include_media=False)}
    assert "data/command/output" not in planned
    assert "__pycache__" in planned


def test_dry_run_deletes_nothing(sandbox, capsys):
    module, root = sandbox
    code = module.main([])
    assert code == 0
    assert (root / "__pycache__").exists()
    assert "Dry run" in capsys.readouterr().out


def test_apply_removes_junk_and_reports_freed_space(sandbox, capsys):
    module, root = sandbox
    code = module.main(["--apply"])
    assert code == 0
    assert not (root / "__pycache__").exists()
    assert not (root / "data" / "command" / "output").exists()
    assert (root / "app" / "main.py").exists()
    assert "freed" in capsys.readouterr().out


def test_clean_reports_a_tidy_tree_without_work(sandbox, capsys):
    module, root = sandbox
    module.main(["--apply"])
    capsys.readouterr()
    code = module.main(["--apply"])
    assert code == 0
    assert "already tidy" in capsys.readouterr().out
