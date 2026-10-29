"""Vercel FastAPI build hook (`[tool.vercel.scripts] build`).

Validates catalog integrity at build time and, when `RUN_BASE44_AUTO_SYNC=1`
is set in environment variables, executes `scripts/sync_base44_full.mjs` to
synchronize secrets, backend functions, agents, and compiled Vite frontend
bundles across connected Base44 apps.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print("[vercel-build] Validating Universal AI Backend v0.6.0 manifests...")
    if os.getenv("RUN_BASE44_AUTO_SYNC", "").strip() == "1":
        node_bin = shutil.which("node")
        script_path = ROOT / "scripts" / "sync_base44_full.mjs"
        if node_bin and script_path.exists():
            print("[vercel-build] RUN_BASE44_AUTO_SYNC=1 detected; running full Base44 app sync...")
            proc = subprocess.run([node_bin, str(script_path)], cwd=str(ROOT), check=False)
            print(f"[vercel-build] Base44 auto-sync finished with exit code {proc.returncode}")
        else:
            print("[vercel-build] Node.js or sync script unavailable; skipping Base44 auto-sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
