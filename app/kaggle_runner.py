"""Batch jobs on Kaggle through its API — and the honest limits of that idea.

A Kaggle API token (`kaggle.json` / `KAGGLE_USERNAME` + `KAGGLE_KEY`) is **not** a server
you can call. It can:

* push a notebook as a kernel (which runs on a Kaggle GPU/CPU machine),
* read that kernel's status,
* download what it wrote to ``/kaggle/working``.

It cannot open a port, keep a process alive past the session limit, or answer a request
while it runs. So the API path is **batch**: send a job, wait, download the artefact. For an
interactive assistant on Kaggle you still need the kernel that starts uvicorn plus a
cloudflared tunnel (``deploy/kaggle/jarvis_kaggle.py``), started by hand.

This module builds those batch jobs from templates, submits them with the Kaggle CLI
(``python -m kaggle``), polls status, and downloads outputs. Everything degrades to
``unavailable: pip install kaggle`` / ``unavailable: KAGGLE_USERNAME ...`` rather than
pretending a job is running.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import governance

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_MARKER = "###UAI-RESULT###"
GPU_WEEKLY_HOURS = 30
SESSION_LIMIT_HOURS = {"gpu": 9, "cpu": 12}


class KaggleError(ValueError):
    """Bad job request."""


class KaggleUnavailable(RuntimeError):
    """Tooling or credentials missing — say which, exactly."""


# --------------------------------------------------------------------------- #
# Credentials and CLI
# --------------------------------------------------------------------------- #

def credentials_path() -> Path:
    return Path(os.getenv("KAGGLE_CONFIG_DIR") or (Path.home() / ".kaggle")) / "kaggle.json"


def username() -> str:
    explicit = (os.getenv("KAGGLE_USERNAME") or "").strip()
    if explicit:
        return explicit
    path = credentials_path()
    if path.exists():
        try:
            return str(json.loads(path.read_text())).get("username", "")
        except (json.JSONDecodeError, OSError):
            return ""
    return ""


def credentials_configured() -> bool:
    if (os.getenv("KAGGLE_USERNAME") or "").strip() and (os.getenv("KAGGLE_KEY") or "").strip():
        return True
    return credentials_path().exists()


def _cli() -> list[str]:
    """Preferred invocation: the module in this interpreter, then PATH."""

    try:
        if __import__("importlib").util.find_spec("kaggle") is not None:
            return [sys.executable, "-m", "kaggle"]
    except (ImportError, ValueError):
        pass
    found = shutil.which("kaggle")
    if found:
        return [found]
    raise KaggleUnavailable(
        "unavailable: pip install kaggle  (then put kaggle.json in ~/.kaggle/ or export "
        "KAGGLE_USERNAME + KAGGLE_KEY)"
    )


def _run_cli(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    base = _cli()
    completed = subprocess.run([*base, *args], capture_output=True, text=True,
                               timeout=timeout, check=False)
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return {"command": " ".join(base + args), "returncode": completed.returncode,
            "output": output[-4000:]}


def _require_credentials() -> str:
    if not credentials_configured():
        raise KaggleUnavailable(
            "unavailable: KAGGLE_USERNAME + KAGGLE_KEY (or ~/.kaggle/kaggle.json) — "
            "kaggle.com → Account → Create New Token"
        )
    user = username()
    if not user:
        raise KaggleUnavailable("unavailable: could not read the username from kaggle.json")
    return user


# --------------------------------------------------------------------------- #
# Job storage
# --------------------------------------------------------------------------- #

def _db() -> Path:
    root = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "kaggle.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db(), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " slug TEXT UNIQUE, kind TEXT, params TEXT, ref TEXT, status TEXT,"
            " message TEXT, created_at REAL, updated_at REAL, dir TEXT)"
        )


def status() -> dict[str, Any]:
    init_db()
    cli_ok, cli_detail = True, ""
    try:
        _cli()
    except KaggleUnavailable as exc:
        cli_ok, cli_detail = False, str(exc)
    with _connect() as connection:
        jobs = connection.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    return {
        "cli": cli_ok,
        "cli_detail": cli_detail or "kaggle CLI available",
        "credentials": credentials_configured(),
        "username": username() or None,
        "credentials_file": str(credentials_path()),
        "jobs_submitted": jobs,
        "templates": sorted(TEMPLATES),
        "limits": {
            "gpu_hours_per_week": GPU_WEEKLY_HOURS,
            "session_hours": SESSION_LIMIT_HOURS,
            "inbound_ports": False,
            "live_http_while_running": False,
        },
        "honesty": (
            "The Kaggle API submits batch kernels and downloads their output. It does not "
            "give you a live endpoint: for that run deploy/kaggle/jarvis_kaggle.py inside a "
            "notebook (uvicorn + cloudflared tunnel), started by hand."
        ),
    }


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

TEMPLATES: dict[str, dict[str, Any]] = {
    "toolbelt": {
        "label": "Run one belt tool on Kaggle",
        "params": ["tool", "args"],
        "gpu": False,
        "description": "Runs app/toolbelt.py inside the kernel and writes the JSON result.",
    },
    "transcribe": {
        "label": "Whisper transcription (GPU)",
        "params": ["input_path"],
        "gpu": True,
        "description": "Installs faster-whisper, transcribes a file from the attached dataset, "
                       "writes SRT + TXT to /kaggle/working.",
    },
    "assistant": {
        "label": "JARVIS answer, batch",
        "params": ["message", "session"],
        "gpu": False,
        "description": "Runs one jarvis.chat() turn in the kernel (rules mode unless "
                       "ANTHROPIC_API_KEY is added as a Kaggle secret) and prints the reply.",
    },
    "video": {
        "label": "Video processing (ffmpeg)",
        "params": ["op", "input_path"],
        "gpu": False,
        "description": "probe / thumbnails / chapters / cut_silence on a dataset file.",
    },
}


def _cell(source: str) -> dict[str, Any]:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": source.splitlines(keepends=True)}


def _markdown(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


SETUP_CELL = """\
import json, os, subprocess, sys, traceback
os.environ.setdefault("UAI_DATA_ROOT", "/kaggle/working/uai-data")
os.environ.setdefault("UAI_JOBS_DISABLE", "1")
print(subprocess.run(["git", "clone", "--depth", "1",
      "https://github.com/zeeburgers00-glitch/universal-ai-backend.git",
      "/kaggle/working/uai"], capture_output=True, text=True).stdout[-500:])
sys.path.insert(0, "/kaggle/working/uai")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                "/kaggle/working/uai/requirements.txt"])
print("setup done")
"""


def _work_cell(kind: str, params: dict[str, Any]) -> str:
    if kind == "toolbelt":
        tool = str(params.get("tool") or "")
        args = params.get("args") or {}
        return f"""\
from app import toolbelt
try:
    result = {{"ok": True, "run": toolbelt.run({tool!r}, {json.dumps(args)})}}
except Exception as exc:
    result = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
print({RESULT_MARKER!r})
print(json.dumps(result, default=str))
"""

    if kind == "transcribe":
        source = str(params.get("input_path") or "input.mp4")
        return f"""\
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "faster-whisper"])
from pathlib import Path
src = Path({source!r})
out_dir = Path("/kaggle/working/transcripts"); out_dir.mkdir(parents=True, exist_ok=True)
result = {{"ok": False}}
try:
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cuda", compute_type="float16")
    segments, info = model.transcribe(str(src), vad_filter=True)
    lines, text = [], []
    def stamp(t):
        h, rem = divmod(int(t), 3600); m, s = divmod(rem, 60)
        return f"{{h:02d}}:{{m:02d}}:{{s:02d}},000"
    for i, seg in enumerate(segments, 1):
        lines.append(f"{{i}}\\n{{stamp(seg.start)}} --> {{stamp(seg.end)}}\\n{{seg.text.strip()}}\\n")
        text.append(seg.text.strip())
    srt = out_dir / (src.stem + ".srt"); srt.write_text("\\n".join(lines))
    txt = out_dir / (src.stem + ".txt"); txt.write_text(" ".join(text))
    result = {{"ok": True, "language": info.language, "duration": info.duration,
               "srt": str(srt), "txt": str(txt)}}
except Exception as exc:
    result = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
print({RESULT_MARKER!r})
print(json.dumps(result, default=str))
"""

    if kind == "video":
        op = str(params.get("op") or "probe")
        source = str(params.get("input_path") or "input.mp4")
        return f"""\
from app import toolbelt
try:
    result = {{"ok": True, "result": toolbelt.run("ffmpeg", {{"op": {op!r}, "path": {source!r}}})}}
except Exception as exc:
    result = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
print({RESULT_MARKER!r})
print(json.dumps(result, default=str))
"""

    if kind == "assistant":
        message = str(params.get("message") or "hello")
        session = str(params.get("session") or "kaggle")
        return f"""\
try:
    from kaggle_secrets import UserSecretsClient
    key = UserSecretsClient().get_secret("ANTHROPIC_API_KEY")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
except Exception:
    pass
from app import jarvis
try:
    reply = jarvis.chat({message!r}, session={session!r})
    result = {{"ok": True, "reply": reply.get("reply"), "used_model": reply.get("used_model"),
               "mood": reply.get("mood")}}
except Exception as exc:
    result = {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
print({RESULT_MARKER!r})
print(json.dumps(result, default=str))
"""

    raise KaggleError(f"unknown template: {kind} (choose {', '.join(TEMPLATES)})")


def render_notebook(kind: str, params: dict[str, Any], *, title: str = "") -> dict[str, Any]:
    """Build a nbformat-4 notebook that runs one job and prints a parseable result."""

    if kind not in TEMPLATES:
        raise KaggleError(f"unknown template: {kind} (choose {', '.join(TEMPLATES)})")
    header = _markdown(
        f"# {title or TEMPLATES[kind]['label']}\n\n"
        f"Generated by universal-ai-backend (`app/kaggle_runner.py`).\n"
        f"Template: `{kind}` · params: `{json.dumps(params)}`\n\n"
        "Output is printed after the `###UAI-RESULT###` marker."
    )
    return {
        "cells": [header, _cell(SETUP_CELL), _cell(_work_cell(kind, params))],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                    "name": "python3"},
                     "language_info": {"name": "python", "version": "3.11"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


# --------------------------------------------------------------------------- #
# Submit / poll / fetch
# --------------------------------------------------------------------------- #

def _slug(kind: str) -> str:
    return f"uai-{kind}-{time.strftime('%Y%m%d-%H%M%S')}"


def submit(kind: str, params: dict[str, Any] | None = None, *,
           dataset_sources: list[str] | None = None, enable_gpu: bool | None = None,
           private: bool = True) -> dict[str, Any]:
    params = params or {}
    # Validate the request before asking about credentials: a typo is a 422, not a 503.
    notebook = render_notebook(kind, params)
    user = _require_credentials()
    _cli()

    slug = _slug(kind)
    job_dir = Path(os.getenv("UAI_DATA_ROOT") or "data").expanduser() / "kaggle" / "jobs" / slug
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.ipynb").write_text(json.dumps(notebook, indent=1), encoding="utf-8")

    gpu = TEMPLATES[kind]["gpu"] if enable_gpu is None else bool(enable_gpu)
    metadata = {
        "id": f"{user}/{slug}",
        "title": f"{slug}",
        "code_file": "job.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": bool(private),
        "enable_gpu": bool(gpu),
        "enable_internet": True,
        "dataset_sources": dataset_sources or [],
        "competition_sources": [],
        "kernel_sources": [],
    }
    (job_dir / "kernel-metadata.json").write_text(json.dumps(metadata, indent=1), encoding="utf-8")

    run = _run_cli(["kernels", "push", "-p", str(job_dir)], timeout=300)
    init_db()
    job_status = "queued" if run["returncode"] == 0 else "push_failed"
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO jobs (slug, kind, params, ref, status, message, created_at, updated_at, dir)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, kind, json.dumps(params), metadata["id"], job_status,
             run["output"][-500:], time.time(), time.time(), str(job_dir)),
        )
        job_id = cursor.lastrowid
    governance.record("kaggle.submit", target=metadata["id"], outcome=job_status,
                      detail={"kind": kind, "gpu": gpu})
    return {"id": job_id, "ref": metadata["id"], "status": job_status,
            "gpu": gpu, "dir": str(job_dir), "cli_output": run["output"][-800:],
            "next": f"POST /v1/kaggle/jobs/{job_id}/refresh to poll"}


MAP_STATUS = {
    "KernelWorkerStatus.QUEUED": "queued",
    "KernelWorkerStatus.RUNNING": "running",
    "KernelWorkerStatus.COMPLETE": "complete",
    "KernelWorkerStatus.ERROR": "error",
    "KernelWorkerStatus.CANCEL_ACKNOWLEDGED": "cancelled",
    "KernelWorkerStatus.CANCEL_REQUESTED": "cancelling",
}


def _parse_status(output: str) -> str:
    match = re.search(r"KernelWorkerStatus\.\w+", output or "")
    if match:
        return MAP_STATUS.get(match.group(0), match.group(0).split(".")[-1].lower())
    for word in ("queued", "running", "complete", "error", "cancel"):
        if word in (output or "").lower():
            return "complete" if word == "complete" else word
    return "unknown"


def refresh(job_id: int) -> dict[str, Any]:
    init_db()
    with _connect() as connection:
        job = connection.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    if job is None:
        raise KaggleError(f"no job with id {job_id}")
    run = _run_cli(["kernels", "status", job["ref"]], timeout=120)
    new_status = _parse_status(run["output"]) if run["returncode"] == 0 else job["status"]
    with _connect() as connection:
        connection.execute("UPDATE jobs SET status = ?, message = ?, updated_at = ? WHERE id = ?",
                           (new_status, run["output"][-500:], time.time(), int(job_id)))
    return {"id": job_id, "ref": job["ref"], "status": new_status,
            "cli_output": run["output"][-800:],
            "next": (f"POST /v1/kaggle/jobs/{job_id}/output once complete"
                     if new_status == "complete" else "keep polling")}


def list_jobs(limit: int = 20) -> dict[str, Any]:
    init_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, slug, kind, ref, status, created_at FROM jobs ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return {"count": len(rows), "jobs": [
        {"id": row["id"], "slug": row["slug"], "kind": row["kind"], "ref": row["ref"],
         "status": row["status"],
         "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(row["created_at"]))}
        for row in rows]}


def fetch_output(job_id: int) -> dict[str, Any]:
    init_db()
    with _connect() as connection:
        job = connection.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    if job is None:
        raise KaggleError(f"no job with id {job_id}")
    if job["status"] != "complete":
        raise KaggleError(f"job {job_id} is '{job['status']}', not complete — nothing to fetch yet")
    dest = Path(job["dir"]) / "output"
    dest.mkdir(parents=True, exist_ok=True)
    run = _run_cli(["kernels", "output", job["ref"], "-p", str(dest)], timeout=600)
    files = sorted(str(path.relative_to(dest)) for path in dest.rglob("*") if path.is_file())
    result: dict[str, Any] = {"id": job_id, "ref": job["ref"], "dest": str(dest),
                              "files": files, "cli_output": run["output"][-800:]}
    marker_file = next((dest / name for name in files if name.endswith(".ipynb")), None)
    if marker_file:
        text = marker_file.read_text(errors="replace")
        if RESULT_MARKER in text:
            tail = text.split(RESULT_MARKER)[-1]
            match = re.search(r"\{.*\}", tail, re.DOTALL)
            if match:
                try:
                    result["job_result"] = json.loads(match.group(0))
                except json.JSONDecodeError:
                    result["job_result"] = {"raw": match.group(0)[:2000]}
    return result


def estimate(kind: str) -> dict[str, Any]:
    template = TEMPLATES.get(kind)
    if template is None:
        raise KaggleError(f"unknown template: {kind}")
    return {
        "kind": kind,
        "label": template["label"],
        "gpu": template["gpu"],
        "session_limit_hours": SESSION_LIMIT_HOURS["gpu" if template["gpu"] else "cpu"],
        "gpu_weekly_hours": GPU_WEEKLY_HOURS,
        "inbound_port": False,
        "note": "batch only: submit, poll, download. No live HTTP while it runs.",
    }
