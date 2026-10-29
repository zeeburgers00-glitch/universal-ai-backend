from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .app import ALLOWED_OPERATIONS, TARGETLESS_OPERATIONS, celery_app

MAX_STDOUT_BYTES = 4 * 1024 * 1024


@celery_app.task(name="rea_worker.run_inspection", bind=True)
def run_inspection(self, payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation", ""))
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(f"Unsupported REA operation: {operation}")

    rea_bin = os.getenv("REA_CLI_BIN", "rea")
    timeout_s = int(os.getenv("REA_JOB_TIMEOUT_SECONDS", "180"))
    cmd: list[str] = [rea_bin, operation]

    if operation not in TARGETLESS_OPERATIONS:
        target = str(payload.get("resolved_target") or "")
        workspace_root = Path(os.getenv("REA_ALLOWED_WORKSPACE_ROOT", "/workspace/targets")).resolve()
        resolved = Path(target).resolve()
        if resolved != workspace_root and workspace_root not in resolved.parents:
            raise ValueError("Resolved target is outside REA_ALLOWED_WORKSPACE_ROOT")
        cmd.append(str(resolved))

    cmd.append("--json")

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        shell=False,
        check=False,
    )
    stdout_bounded = (completed.stdout or "")[:MAX_STDOUT_BYTES].strip()
    parsed: Any = None
    if stdout_bounded.startswith("{") or stdout_bounded.startswith("["):
        try:
            parsed = json.loads(stdout_bounded)
        except json.JSONDecodeError:
            parsed = None

    return {
        "status": "succeeded" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "operation": operation,
        "evidence_id": parsed.get("evidence_id") if isinstance(parsed, dict) else None,
        "output": parsed if parsed is not None else {"raw_preview": stdout_bounded[:4000]},
    }
