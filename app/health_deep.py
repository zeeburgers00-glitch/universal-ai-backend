"""Deep health: is this process actually able to do work, or just answering?

`/health` is a liveness probe — it stays cheap so a load balancer can poll it.
`/health/deep` is the readiness/diagnostic probe: it checks the things that break
silently in a container (read-only volume, full disk, missing ffmpeg, dead queue
worker) and reports each one, rather than a single boolean.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from . import jobs


def _check_data_root() -> dict[str, Any]:
    root = Path(os.getenv("UAI_DATA_ROOT", "/data")).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".health-{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
        detail = str(root)
    except OSError as exc:
        writable = False
        detail = f"{root}: {exc}"
    return {"name": "data_root", "ok": writable, "critical": True, "detail": detail}


def _check_disk() -> dict[str, Any]:
    root = Path(os.getenv("UAI_DATA_ROOT", tempfile.gettempdir())).expanduser()
    path = root if root.exists() else Path(tempfile.gettempdir())
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return {"name": "disk", "ok": False, "critical": False, "detail": str(exc)}
    free_gb = round(usage.free / 1024 ** 3, 2)
    # Renders need room; under 1 GB is a warning, not a failure.
    return {
        "name": "disk",
        "ok": free_gb >= 1.0,
        "critical": False,
        "detail": f"{free_gb} GB free of {round(usage.total / 1024 ** 3, 1)} GB",
    }


def _check_database() -> dict[str, Any]:
    try:
        path = jobs.db_path()
        connection = sqlite3.connect(path, timeout=5)
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            connection.close()
        return {"name": "job_db", "ok": True, "critical": True, "detail": str(path)}
    except Exception as exc:  # noqa: BLE001 - report, never raise from a health probe
        return {"name": "job_db", "ok": False, "critical": True, "detail": f"{type(exc).__name__}: {exc}"}


def _check_ffmpeg() -> dict[str, Any]:
    try:
        from videoengine.assembly import find_ffmpeg

        binary = find_ffmpeg()
        return {"name": "ffmpeg", "ok": bool(binary), "critical": False, "detail": str(binary)}
    except Exception as exc:  # noqa: BLE001
        return {"name": "ffmpeg", "ok": False, "critical": False, "detail": f"unavailable: {exc}"}


def _check_queue() -> dict[str, Any]:
    try:
        stats = jobs.stats()
        counts = stats.get("counts", {})
        workers_up = bool(stats.get("worker_threads_running"))
        concurrency = stats.get("concurrency", 0)
        failed = counts.get("failed", 0)
        detail = (
            f"queued={counts.get('queued', 0)} running={counts.get('running', 0)} "
            f"done={counts.get('done', 0)} failed={failed} "
            f"workers={'up x' + str(concurrency) if workers_up else 'off'}"
        )
        ok = True
        if not workers_up and counts.get("queued", 0) > 0:
            ok = False  # jobs piling up with nobody to run them
            detail += " (queued jobs but no worker thread)"
        return {"name": "queue", "ok": ok, "critical": False, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"name": "queue", "ok": False, "critical": False, "detail": f"{type(exc).__name__}: {exc}"}


def _check_api_key() -> dict[str, Any]:
    configured = bool(os.getenv("BACKEND_API_KEY", "").strip())
    return {
        "name": "api_key",
        "ok": configured,
        "critical": False,
        "detail": "configured" if configured else "BACKEND_API_KEY is empty — every keyed route returns 503",
    }


def probe() -> dict[str, Any]:
    started = time.perf_counter()
    checks = [
        _check_api_key(),
        _check_data_root(),
        _check_database(),
        _check_disk(),
        _check_ffmpeg(),
        _check_queue(),
    ]
    critical_failed = [check["name"] for check in checks if check["critical"] and not check["ok"]]
    warnings = [check["name"] for check in checks if not check["critical"] and not check["ok"]]
    return {
        "status": "fail" if critical_failed else ("degraded" if warnings else "ok"),
        "critical_failed": critical_failed,
        "warnings": warnings,
        "checks": checks,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "uptime_seconds": round(time.time() - _STARTED, 1),
    }


_STARTED = time.time()
